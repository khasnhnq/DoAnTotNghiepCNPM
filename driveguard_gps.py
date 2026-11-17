"""GPS event snapshots for DriveGuard AI.

The browser may refresh one current position in SQLite while monitoring is enabled.
Only alert rows receive permanent latitude/longitude snapshots via a SQLite trigger;
there is no stored GPS track/history.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import jsonify, request


GPS_MAX_AGE_SECONDS = 120


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_gps_database(db_path: str | Path) -> None:
    """Create the latest-fix table, add nullable GPS columns to alerts, and add trigger.

    Existing alerts and all other data are preserved. The migration is idempotent.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with _connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "alerts" not in tables:
            raise RuntimeError(
                "Không tìm thấy bảng 'alerts' trong database. "
                "Hãy kiểm tra DB_PATH và chạy init_database() của dự án trước."
            )

        existing = {
            row[1] for row in conn.execute('PRAGMA table_info("alerts")').fetchall()
        }
        columns_to_add = {
            "gps_latitude": "REAL",
            "gps_longitude": "REAL",
            "gps_accuracy_m": "REAL",
            "gps_captured_at": "TEXT",
        }
        for column, sql_type in columns_to_add.items():
            if column not in existing:
                conn.execute(
                    f'ALTER TABLE alerts ADD COLUMN "{column}" {sql_type}'
                )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gps_current_location (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy_m REAL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'browser-geolocation'
            )
            """
        )

        # Event snapshots are copied into the alert row at insertion time.
        # The current-fix table is a single row overwritten by the browser, not a track.
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_alerts_attach_gps
            AFTER INSERT ON alerts
            BEGIN
                UPDATE alerts
                   SET gps_latitude = (
                           SELECT latitude FROM gps_current_location
                            WHERE id = 1
                              AND julianday(updated_at) >= julianday('now', '-{GPS_MAX_AGE_SECONDS} seconds')
                       ),
                       gps_longitude = (
                           SELECT longitude FROM gps_current_location
                            WHERE id = 1
                              AND julianday(updated_at) >= julianday('now', '-{GPS_MAX_AGE_SECONDS} seconds')
                       ),
                       gps_accuracy_m = (
                           SELECT accuracy_m FROM gps_current_location
                            WHERE id = 1
                              AND julianday(updated_at) >= julianday('now', '-{GPS_MAX_AGE_SECONDS} seconds')
                       ),
                       gps_captured_at = (
                           SELECT updated_at FROM gps_current_location
                            WHERE id = 1
                              AND julianday(updated_at) >= julianday('now', '-{GPS_MAX_AGE_SECONDS} seconds')
                       )
                 WHERE rowid = NEW.rowid;
            END
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_gps_created "
            "ON alerts(gps_latitude, gps_longitude, created_at)"
        )
        conn.commit()


def _valid_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Trường {name} phải là số.")
    if not math.isfinite(number):
        raise ValueError(f"Trường {name} không hợp lệ.")
    return number


def register_gps_routes(app, db_path: str | Path | None = None) -> None:
    """Register the GPS API routes on the existing Flask app."""
    database_path = Path(db_path) if db_path else Path(app.root_path) / "drowsiness.db"
    init_gps_database(database_path)

    @app.post("/api/features/gps/location")
    def gps_update_location():
        payload = request.get_json(silent=True) or {}
        try:
            latitude = _valid_number(payload.get("latitude"), "latitude")
            longitude = _valid_number(payload.get("longitude"), "longitude")
            accuracy = payload.get("accuracy")
            accuracy_m = None if accuracy is None else _valid_number(accuracy, "accuracy")

            if not -90 <= latitude <= 90:
                raise ValueError("Vĩ độ phải nằm trong khoảng -90 đến 90.")
            if not -180 <= longitude <= 180:
                raise ValueError("Kinh độ phải nằm trong khoảng -180 đến 180.")
            if accuracy_m is not None and not 0 <= accuracy_m <= 100000:
                raise ValueError("Độ chính xác GPS không hợp lệ.")
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400

        captured_at = _utc_now()
        with _connect(database_path) as conn:
            conn.execute(
                """
                INSERT INTO gps_current_location
                    (id, latitude, longitude, accuracy_m, updated_at, source)
                VALUES (1, ?, ?, ?, ?, 'browser-geolocation')
                ON CONFLICT(id) DO UPDATE SET
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    accuracy_m = excluded.accuracy_m,
                    updated_at = excluded.updated_at,
                    source = excluded.source
                """,
                (latitude, longitude, accuracy_m, captured_at),
            )
            conn.commit()

        return jsonify({
            "success": True,
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy_m,
            "updated_at": captured_at,
            "message": "Đã cập nhật vị trí hiện tại. Tọa độ sẽ được lưu vào lịch sử khi có cảnh báo.",
        })

    @app.get("/api/features/gps/status")
    def gps_location_status():
        with _connect(database_path) as conn:
            row = conn.execute(
                "SELECT latitude, longitude, accuracy_m, updated_at "
                "FROM gps_current_location WHERE id = 1"
            ).fetchone()
        if row is None:
            return jsonify({"success": True, "enabled": False, "location": None})
        return jsonify({
            "success": True,
            "enabled": True,
            "location": dict(row),
        })

    @app.delete("/api/features/gps/location")
    def gps_clear_location():
        # Stop GPS: remove only the single current fix. Existing alert snapshots remain.
        with _connect(database_path) as conn:
            conn.execute("DELETE FROM gps_current_location WHERE id = 1")
            conn.commit()
        return jsonify({"success": True, "message": "Đã dừng chia sẻ vị trí hiện tại."})

    @app.get("/api/features/gps/events")
    def gps_event_locations():
        try:
            limit = int(request.args.get("limit", "50"))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))

        with _connect(database_path) as conn:
            rows = conn.execute(
                """
                SELECT rowid AS alert_rowid,
                       event_type,
                       created_at,
                       gps_latitude AS latitude,
                       gps_longitude AS longitude,
                       gps_accuracy_m AS accuracy_m,
                       gps_captured_at
                  FROM alerts
                 WHERE gps_latitude IS NOT NULL
                   AND gps_longitude IS NOT NULL
                 ORDER BY rowid DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return jsonify({"success": True, "events": [dict(row) for row in rows]})
