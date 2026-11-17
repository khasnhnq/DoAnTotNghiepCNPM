"""DriveGuard AI - advanced monitoring features.

This module extends the existing Flask + CameraStream project without
replacing the current CNN / FaceMesh detection pipeline.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "drowsiness.db"
STATIC_DIR = BASE_DIR / "static"
EVIDENCE_DIR = STATIC_DIR / "evidence"
FACE_AWAY_SECONDS = 2.5
CALIBRATION_SECONDS = 5.0
CALIBRATION_MIN_SAMPLES = 10

bp = Blueprint("driveguard_features", __name__)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_feature_schema() -> None:
    """Create new tables and safely add columns to the old alerts table."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        # Defensive creation: the original database.init_database normally
        # creates this table before the extensions are registered.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                ear REAL,
                mar REAL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS driver_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                ear_threshold REAL NOT NULL DEFAULT 0.21,
                drowsy_seconds REAL NOT NULL DEFAULT 2.0,
                mar_threshold REAL NOT NULL DEFAULT 0.50,
                yawn_seconds REAL NOT NULL DEFAULT 1.5,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitoring_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                driver_id INTEGER,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_seconds REAL,
                FOREIGN KEY(driver_id) REFERENCES driver_profiles(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feature_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()
        }
        migrations = {
            "session_id": "ALTER TABLE alerts ADD COLUMN session_id INTEGER",
            "severity": "ALTER TABLE alerts ADD COLUMN severity INTEGER NOT NULL DEFAULT 1",
            "snapshot_path": "ALTER TABLE alerts ADD COLUMN snapshot_path TEXT",
        }
        for column, sql in migrations.items():
            if column not in existing:
                conn.execute(sql)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_driveguard_alert_metadata
            AFTER INSERT ON alerts
            BEGIN
                UPDATE alerts
                SET
                    session_id = COALESCE(
                        NEW.session_id,
                        (SELECT CAST(value AS INTEGER)
                         FROM feature_settings WHERE key = 'active_session_id')
                    ),
                    severity = CASE
                        WHEN NEW.event_type = 'DROWSY' AND COALESCE(NEW.severity, 1) < 2 THEN 2
                        ELSE COALESCE(NEW.severity, 1)
                    END
                WHERE id = NEW.id;
            END;
        """)

        row = conn.execute(
            "SELECT id FROM driver_profiles WHERE name = ?", ("Tài xế mặc định",)
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                """INSERT INTO driver_profiles
                   (name, ear_threshold, drowsy_seconds, mar_threshold, yawn_seconds, created_at)
                   VALUES (?, 0.21, 2.0, 0.50, 1.5, ?)""",
                ("Tài xế mặc định", _now_text()),
            )
            default_driver_id = cursor.lastrowid
        else:
            default_driver_id = row["id"]

        conn.execute(
            "INSERT OR IGNORE INTO feature_settings(key, value) VALUES('active_driver_id', ?)",
            (str(default_driver_id),),
        )
        conn.execute(
            "INSERT OR IGNORE INTO feature_settings(key, value) VALUES('active_session_id', '')"
        )


def _get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM feature_settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def _set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO feature_settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, "" if value is None else str(value)),
    )


def get_driver_profiles() -> list[dict[str, Any]]:
    ensure_feature_schema()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM driver_profiles ORDER BY id ASC"
        ).fetchall()
        active_id = int(_get_setting(conn, "active_driver_id") or 0)
    result = []
    for row in rows:
        item = dict(row)
        item["is_active"] = item["id"] == active_id
        result.append(item)
    return result


def get_driver_profile(driver_id: int | None = None) -> dict[str, Any]:
    ensure_feature_schema()
    with _connect() as conn:
        if driver_id is None:
            driver_id = int(_get_setting(conn, "active_driver_id") or 1)
        row = conn.execute(
            "SELECT * FROM driver_profiles WHERE id = ?", (driver_id,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM driver_profiles ORDER BY id LIMIT 1"
            ).fetchone()
        return dict(row) if row else {}


def create_driver_profile(name: str) -> dict[str, Any]:
    ensure_feature_schema()
    name = (name or "").strip()
    if not name or len(name) > 60:
        raise ValueError("Tên tài xế phải có từ 1 đến 60 ký tự.")
    with _connect() as conn:
        cursor = conn.execute(
            """INSERT INTO driver_profiles
               (name, ear_threshold, drowsy_seconds, mar_threshold, yawn_seconds, created_at)
               VALUES (?, 0.21, 2.0, 0.50, 1.5, ?)""",
            (name, _now_text()),
        )
        driver_id = cursor.lastrowid
    return get_driver_profile(int(driver_id))


def update_driver_profile(driver_id: int, values: dict[str, Any]) -> dict[str, Any]:
    ensure_feature_schema()
    allowed = {
        "ear_threshold": (0.12, 0.35),
        "drowsy_seconds": (1.0, 6.0),
        "mar_threshold": (0.30, 1.20),
        "yawn_seconds": (1.0, 5.0),
    }
    updates: dict[str, float] = {}
    for key, bounds in allowed.items():
        if key in values:
            try:
                number = float(values[key])
            except (TypeError, ValueError):
                raise ValueError(f"Giá trị {key} không hợp lệ.")
            if not bounds[0] <= number <= bounds[1]:
                raise ValueError(
                    f"{key} phải nằm trong khoảng {bounds[0]} đến {bounds[1]}."
                )
            updates[key] = number
    if not updates:
        raise ValueError("Không có thông số hợp lệ để cập nhật.")
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with _connect() as conn:
        cursor = conn.execute(
            f"UPDATE driver_profiles SET {assignments} WHERE id = ?",
            [*updates.values(), driver_id],
        )
        if cursor.rowcount == 0:
            raise ValueError("Không tìm thấy hồ sơ tài xế.")
    return get_driver_profile(driver_id)


def set_active_driver(driver_id: int) -> dict[str, Any]:
    ensure_feature_schema()
    with _connect() as conn:
        exists = conn.execute(
            "SELECT id FROM driver_profiles WHERE id = ?", (driver_id,)
        ).fetchone()
        if exists is None:
            raise ValueError("Hồ sơ tài xế không tồn tại.")
        _set_setting(conn, "active_driver_id", driver_id)
    return get_driver_profile(driver_id)


def start_session(driver_id: int) -> int:
    ensure_feature_schema()
    with _connect() as conn:
        # Close an orphaned session if the previous process ended unexpectedly.
        old_id = _get_setting(conn, "active_session_id")
        if old_id:
            old = conn.execute(
                "SELECT started_at, ended_at FROM monitoring_sessions WHERE id = ?",
                (old_id,),
            ).fetchone()
            if old and old["ended_at"] is None:
                now = _now_text()
                try:
                    duration = max(
                        0.0,
                        (datetime.fromisoformat(now) - datetime.fromisoformat(old["started_at"])).total_seconds(),
                    )
                except ValueError:
                    duration = None
                conn.execute(
                    "UPDATE monitoring_sessions SET ended_at = ?, duration_seconds = ? WHERE id = ?",
                    (now, duration, old_id),
                )
        cursor = conn.execute(
            "INSERT INTO monitoring_sessions(driver_id, started_at) VALUES(?, ?)",
            (driver_id, _now_text()),
        )
        session_id = int(cursor.lastrowid)
        _set_setting(conn, "active_session_id", session_id)
        return session_id


def finish_session(session_id: int | None) -> None:
    if not session_id:
        return
    ensure_feature_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT started_at, ended_at FROM monitoring_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row and row["ended_at"] is None:
            ended = _now_text()
            try:
                duration = max(
                    0.0,
                    (datetime.fromisoformat(ended) - datetime.fromisoformat(row["started_at"])).total_seconds(),
                )
            except ValueError:
                duration = None
            conn.execute(
                "UPDATE monitoring_sessions SET ended_at = ?, duration_seconds = ? WHERE id = ?",
                (ended, duration, session_id),
            )
        if _get_setting(conn, "active_session_id") == str(session_id):
            _set_setting(conn, "active_session_id", "")


def get_active_session_id() -> int | None:
    ensure_feature_schema()
    with _connect() as conn:
        value = _get_setting(conn, "active_session_id")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def create_feature_alert(
    event_type: str,
    session_id: int | None,
    severity: int = 1,
    ear: float | None = None,
    mar: float | None = None,
) -> int:
    ensure_feature_schema()
    severity = max(1, min(3, int(severity)))
    with _connect() as conn:
        cursor = conn.execute(
            """INSERT INTO alerts
               (event_type, ear, mar, created_at, session_id, severity)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_type, ear, mar, _now_text(), session_id, severity),
        )
        return int(cursor.lastrowid)


def _latest_alert(session_id: int | None, event_type: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    ensure_feature_schema()
    with _connect() as conn:
        row = conn.execute(
            """SELECT id, event_type, created_at, snapshot_path, severity
               FROM alerts WHERE session_id = ? AND event_type = ?
               ORDER BY id DESC LIMIT 1""",
            (session_id, event_type),
        ).fetchone()
    return dict(row) if row else None


def _attach_snapshot(alert_id: int, frame: Any) -> str | None:
    """Save one JPEG for an event. No continuous video is stored."""
    try:
        import cv2

        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"alert_{alert_id}_{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"
        full_path = EVIDENCE_DIR / filename
        if not cv2.imwrite(
            str(full_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        ):
            return None
        relative = f"evidence/{filename}"
        with _connect() as conn:
            conn.execute(
                "UPDATE alerts SET snapshot_path = ? WHERE id = ? AND snapshot_path IS NULL",
                (relative, alert_id),
            )
        return relative
    except Exception as exc:  # evidence failure must not stop the camera stream
        print("DRIVEGUARD: khong luu duoc anh minh chung:", exc)
        return None


def _attach_recent_event_snapshot(session_id: int | None, event_type: str, frame: Any) -> None:
    item = _latest_alert(session_id, event_type)
    if not item or item.get("snapshot_path"):
        return
    try:
        created = datetime.fromisoformat(item["created_at"])
        age = (datetime.now() - created).total_seconds()
    except (ValueError, TypeError):
        return
    if 0 <= age <= 2.0:
        _attach_snapshot(int(item["id"]), frame)


def _update_event_severity(session_id: int | None, event_type: str, severity: int) -> None:
    item = _latest_alert(session_id, event_type)
    if not item or int(item.get("severity") or 1) >= severity:
        return
    with _connect() as conn:
        conn.execute(
            "UPDATE alerts SET severity = ? WHERE id = ?",
            (severity, item["id"]),
        )


def _session_rows(limit: int = 30) -> list[dict[str, Any]]:
    ensure_feature_schema()
    limit = max(1, min(100, int(limit)))
    with _connect() as conn:
        rows = conn.execute(
            """SELECT s.id, s.started_at, s.ended_at, s.duration_seconds,
                      d.name AS driver_name,
                      COUNT(a.id) AS total_alerts,
                      SUM(CASE WHEN a.event_type = 'DROWSY' THEN 1 ELSE 0 END) AS drowsy_count,
                      SUM(CASE WHEN a.event_type = 'YAWNING' THEN 1 ELSE 0 END) AS yawning_count,
                      SUM(CASE WHEN a.event_type = 'FACE_AWAY' THEN 1 ELSE 0 END) AS face_away_count,
                      SUM(CASE WHEN a.severity = 3 THEN 1 ELSE 0 END) AS critical_count
               FROM monitoring_sessions s
               LEFT JOIN driver_profiles d ON d.id = s.driver_id
               LEFT JOIN alerts a ON a.session_id = s.id
               GROUP BY s.id
               ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _session_report(session_id: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    ensure_feature_schema()
    with _connect() as conn:
        row = conn.execute(
            """SELECT s.*, d.name AS driver_name
               FROM monitoring_sessions s
               LEFT JOIN driver_profiles d ON d.id = s.driver_id
               WHERE s.id = ?""",
            (session_id,),
        ).fetchone()
        if row is None:
            return None, []
        alerts = conn.execute(
            """SELECT id, event_type, ear, mar, created_at, severity, snapshot_path
               FROM alerts WHERE session_id = ? ORDER BY id DESC""",
            (session_id,),
        ).fetchall()
    return dict(row), [dict(item) for item in alerts]


def _get_camera():
    return current_app.config["DRIVEGUARD_CAMERA_STREAM"]


def _camera_extension_status(camera) -> dict[str, Any]:
    payload = camera.get_status()
    session_id = getattr(camera, "ext_session_id", None)
    profile = getattr(camera, "ext_profile", None) or get_driver_profile()
    calibration = getattr(camera, "ext_calibration", None)
    calibration_result = getattr(camera, "ext_calibration_result", None)
    payload.update({
        "session_id": session_id,
        "driver": profile.get("name") if profile else None,
        "driver_id": profile.get("id") if profile else None,
        "fps": round(float(getattr(camera, "fps", 0.0) or 0.0), 2),
        "process_ms": round(float(getattr(camera, "ext_process_ms", 0.0) or 0.0), 2),
        "inference_ms": round(float(getattr(camera, "ext_inference_ms", 0.0) or 0.0), 2),
        "cnn_open_probability": getattr(camera, "last_cnn_probability", None),
        "cnn_threshold": 0.052847,
        "ear_threshold": profile.get("ear_threshold") if profile else None,
        "drowsy_seconds": profile.get("drowsy_seconds") if profile else None,
        "mar_threshold": profile.get("mar_threshold") if profile else None,
        "yawn_seconds": profile.get("yawn_seconds") if profile else None,
        "face_present": payload.get("status") not in ("NO_FACE", "STANDBY") and bool(payload.get("camera_on")),
        "calibration": {
            "active": bool(calibration),
            "sample_count": len(calibration.get("samples", [])) if calibration else 0,
            "seconds_left": max(0, round(calibration.get("until", 0) - time.monotonic(), 1)) if calibration else 0,
            "result": calibration_result,
        },
    })
    return payload


def install_camera_extensions() -> None:
    """Wrap existing CameraStream methods with session, calibration and metrics hooks."""
    import camera_stream as camera_module

    cls = camera_module.CameraStream
    if getattr(cls, "_driveguard_extensions_installed", False):
        return

    original_start = cls.start
    original_stop = cls.stop
    original_process_frame = cls.process_frame
    original_predict_eyes = cls.predict_eyes
    original_get_status = cls.get_status

    def extended_start(self, *args, **kwargs):
        was_running = bool(getattr(self, "running", False))
        result = original_start(self, *args, **kwargs)
        if not was_running and bool(getattr(self, "running", False)):
            ensure_feature_schema()
            profile = get_driver_profile()
            self.ext_profile = profile
            self.ext_session_id = start_session(int(profile["id"]))
            self.ext_face_missing_since = None
            self.ext_face_missing_logged = False
            self.ext_last_snapshot_ids = set()
            self.ext_process_ms = 0.0
            self.ext_inference_ms = 0.0
            self.ext_calibration = None
            self.ext_calibration_result = None
        return result

    def extended_stop(self, *args, **kwargs):
        session_id = getattr(self, "ext_session_id", None)
        try:
            return original_stop(self, *args, **kwargs)
        finally:
            if session_id:
                finish_session(session_id)
            self.ext_session_id = None
            self.ext_face_missing_since = None
            self.ext_face_missing_logged = False
            self.ext_calibration = None

    def extended_predict_eyes(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_predict_eyes(self, *args, **kwargs)
        finally:
            self.ext_inference_ms = (time.perf_counter() - started) * 1000.0

    def extended_process_frame(self, frame, face_mesh):
        profile = getattr(self, "ext_profile", None) or get_driver_profile()
        if profile:
            # These module constants are the thresholds consumed by the
            # original, already-tested process_frame implementation.
            camera_module.EAR_THRESHOLD = float(profile["ear_threshold"])
            camera_module.DROWSY_SECONDS = float(profile["drowsy_seconds"])
            camera_module.MAR_THRESHOLD = float(profile["mar_threshold"])
            camera_module.YAWN_SECONDS = float(profile["yawn_seconds"])

        started = time.perf_counter()
        output = original_process_frame(self, frame, face_mesh)
        self.ext_process_ms = (time.perf_counter() - started) * 1000.0

        with self.status_lock:
            raw_status = self.current_status
            ear = self.current_ear
            mar = self.current_mar

        now_mono = time.monotonic()
        session_id = getattr(self, "ext_session_id", None)

        # Face-away warning: require a continuous absence to avoid one-frame noise.
        if raw_status == "NO FACE":
            if getattr(self, "ext_face_missing_since", None) is None:
                self.ext_face_missing_since = now_mono
            missing_for = now_mono - self.ext_face_missing_since
            if missing_for >= FACE_AWAY_SECONDS and not getattr(self, "ext_face_missing_logged", False):
                alert_id = create_feature_alert(
                    "FACE_AWAY", session_id, severity=2, ear=ear, mar=mar
                )
                _attach_snapshot(alert_id, output)
                self.ext_face_missing_logged = True
        else:
            self.ext_face_missing_since = None
            self.ext_face_missing_logged = False

        # Store one evidence image for each newly generated DROWSY/YAWNING event.
        if raw_status == "DROWSY!":
            item = _latest_alert(session_id, "DROWSY")
            if item:
                if item["id"] not in getattr(self, "ext_last_snapshot_ids", set()):
                    _attach_recent_event_snapshot(session_id, "DROWSY", output)
                    self.ext_last_snapshot_ids.add(item["id"])
                closed_since = [
                    value for value in (
                        getattr(self, "closed_start", None),
                        getattr(self, "ear_closed_start", None),
                    ) if value is not None
                ]
                if closed_since and now_mono - min(closed_since) >= 4.0:
                    _update_event_severity(session_id, "DROWSY", 3)
        elif raw_status == "YAWNING!":
            item = _latest_alert(session_id, "YAWNING")
            if item and item["id"] not in getattr(self, "ext_last_snapshot_ids", set()):
                _attach_recent_event_snapshot(session_id, "YAWNING", output)
                self.ext_last_snapshot_ids.add(item["id"])

        # Five-second calibration: user must look straight at the camera with eyes open.
        calibration = getattr(self, "ext_calibration", None)
        if calibration:
            if now_mono < calibration["until"]:
                if raw_status == "EYES OPEN" and ear is not None:
                    calibration["samples"].append(float(ear))
            else:
                samples = calibration["samples"]
                if len(samples) >= CALIBRATION_MIN_SAMPLES:
                    baseline = float(median(samples))
                    calibrated_threshold = max(0.12, min(0.35, baseline * 0.72))
                    try:
                        updated = update_driver_profile(
                            int(calibration["driver_id"]),
                            {"ear_threshold": calibrated_threshold},
                        )
                        self.ext_profile = updated
                        self.ext_calibration_result = {
                            "success": True,
                            "samples": len(samples),
                            "open_ear_median": round(baseline, 4),
                            "ear_threshold": round(calibrated_threshold, 4),
                            "message": "Đã cập nhật ngưỡng EAR cho hồ sơ tài xế.",
                        }
                    except Exception as exc:
                        self.ext_calibration_result = {
                            "success": False,
                            "samples": len(samples),
                            "message": str(exc),
                        }
                else:
                    self.ext_calibration_result = {
                        "success": False,
                        "samples": len(samples),
                        "message": "Không đủ mẫu mắt mở. Hãy thử lại và nhìn thẳng camera.",
                    }
                self.ext_calibration = None

        return output

    def extended_get_status(self):
        payload = original_get_status(self)
        profile = getattr(self, "ext_profile", None) or get_driver_profile()
        calibration = getattr(self, "ext_calibration", None)
        drowsy_starts = [
            value for value in (
                getattr(self, "closed_start", None),
                getattr(self, "ear_closed_start", None),
            ) if value is not None
        ]
        drowsy_duration = (
            max(0.0, time.monotonic() - min(drowsy_starts))
            if drowsy_starts else 0.0
        )
        state = payload.get("status")
        warning_level = (
            3 if state == "DROWSY" and drowsy_duration >= 4.0
            else 2 if state in ("DROWSY", "NO_FACE")
            else 1 if state == "YAWNING"
            else 0
        )
        payload.update({
            "drowsy_duration": round(drowsy_duration, 2),
            "warning_level": warning_level,
            "fps": round(float(getattr(self, "fps", 0.0) or 0.0), 2),
            "process_ms": round(float(getattr(self, "ext_process_ms", 0.0) or 0.0), 2),
            "inference_ms": round(float(getattr(self, "ext_inference_ms", 0.0) or 0.0), 2),
            "cnn_open_probability": getattr(self, "last_cnn_probability", None),
            "cnn_threshold": float(getattr(camera_module, "CNN_THRESHOLD", 0.052847)),
            "driver": profile.get("name") if profile else None,
            "driver_id": profile.get("id") if profile else None,
            "ear_threshold": profile.get("ear_threshold") if profile else None,
            "drowsy_seconds": profile.get("drowsy_seconds") if profile else None,
            "mar_threshold": profile.get("mar_threshold") if profile else None,
            "yawn_seconds": profile.get("yawn_seconds") if profile else None,
            "session_id": getattr(self, "ext_session_id", None),
            "face_away_seconds": round(
                max(0.0, time.monotonic() - self.ext_face_missing_since), 1
            ) if getattr(self, "ext_face_missing_since", None) is not None else 0.0,
            "calibration": {
                "active": bool(calibration),
                "sample_count": len(calibration.get("samples", [])) if calibration else 0,
                "seconds_left": round(max(0.0, calibration["until"] - time.monotonic()), 1) if calibration else 0.0,
                "result": getattr(self, "ext_calibration_result", None),
            },
        })
        return payload

    cls.start = extended_start
    cls.stop = extended_stop
    cls.predict_eyes = extended_predict_eyes
    cls.process_frame = extended_process_frame
    cls.get_status = extended_get_status
    cls._driveguard_extensions_installed = True


def register_feature_routes(app, camera_stream) -> None:
    ensure_feature_schema()
    app.config["DRIVEGUARD_CAMERA_STREAM"] = camera_stream
    if "driveguard_features" not in app.blueprints:
        app.register_blueprint(bp)


@bp.route("/advanced")
def advanced_page():
    return render_template("advanced.html")


@bp.route("/api/features/status")
def feature_status():
    return jsonify(_camera_extension_status(_get_camera()))


@bp.route("/api/features/drivers", methods=["GET", "POST"])
def feature_drivers():
    if request.method == "GET":
        return jsonify({"drivers": get_driver_profiles()})
    data = request.get_json(silent=True) or {}
    try:
        profile = create_driver_profile(data.get("name", ""))
        return jsonify({"success": True, "driver": profile}), 201
    except (ValueError, sqlite3.IntegrityError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@bp.route("/api/features/drivers/active", methods=["POST"])
def feature_set_active_driver():
    camera = _get_camera()
    if camera.running:
        return jsonify({"success": False, "message": "Hãy tắt camera trước khi đổi hồ sơ tài xế."}), 409
    data = request.get_json(silent=True) or {}
    try:
        profile = set_active_driver(int(data.get("driver_id", 0)))
        return jsonify({"success": True, "driver": profile})
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@bp.route("/api/features/drivers/<int:driver_id>", methods=["POST"])
def feature_update_driver(driver_id: int):
    camera = _get_camera()
    if camera.running:
        return jsonify({"success": False, "message": "Hãy tắt camera trước khi chỉnh thông số."}), 409
    data = request.get_json(silent=True) or {}
    try:
        profile = update_driver_profile(driver_id, data)
        return jsonify({"success": True, "driver": profile})
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@bp.route("/api/features/calibration/start", methods=["POST"])
def feature_start_calibration():
    camera = _get_camera()
    if not camera.running:
        return jsonify({"success": False, "message": "Hãy bật camera trước khi hiệu chỉnh."}), 409
    if getattr(camera, "ext_calibration", None):
        return jsonify({"success": False, "message": "Đang có một phiên hiệu chỉnh."}), 409
    profile = getattr(camera, "ext_profile", None) or get_driver_profile()
    camera.ext_calibration_result = None
    camera.ext_calibration = {
        "driver_id": int(profile["id"]),
        "until": time.monotonic() + CALIBRATION_SECONDS,
        "samples": [],
    }
    return jsonify({
        "success": True,
        "message": "Giữ mắt mở, nhìn thẳng camera trong 5 giây.",
        "duration_seconds": CALIBRATION_SECONDS,
    })


@bp.route("/api/features/sessions")
def feature_sessions():
    return jsonify({"sessions": _session_rows(request.args.get("limit", 30, type=int) or 30)})


@bp.route("/api/features/sessions/<int:session_id>")
def feature_session_detail(session_id: int):
    session, alerts = _session_report(session_id)
    if session is None:
        return jsonify({"error": "Không tìm thấy phiên giám sát."}), 404
    return jsonify({"session": session, "alerts": alerts})


@bp.route("/api/features/sessions/<int:session_id>/export.csv")
def feature_session_csv(session_id: int):
    session, alerts = _session_report(session_id)
    if session is None:
        abort(404)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Loại sự kiện", "Mức cảnh báo", "EAR", "MAR", "Thời gian", "Ảnh minh chứng"])
    for item in alerts:
        writer.writerow([
            item["id"], item["event_type"], item["severity"],
            item["ear"], item["mar"], item["created_at"], item["snapshot_path"] or "",
        ])
    content = "\ufeff" + output.getvalue()
    return current_app.response_class(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="driveguard_session_{session_id}.csv"'},
    )


@bp.route("/sessions/<int:session_id>/report")
def feature_session_report_page(session_id: int):
    session, alerts = _session_report(session_id)
    if session is None:
        abort(404)
    return render_template("session_report.html", session=session, alerts=alerts)


@bp.route("/api/features/evidence")
def feature_evidence_list():
    ensure_feature_schema()
    limit = max(1, min(100, request.args.get("limit", 30, type=int) or 30))
    with _connect() as conn:
        rows = conn.execute(
            """SELECT a.id, a.event_type, a.severity, a.ear, a.mar, a.created_at,
                      a.snapshot_path, s.id AS session_id, d.name AS driver_name
               FROM alerts a
               LEFT JOIN monitoring_sessions s ON s.id = a.session_id
               LEFT JOIN driver_profiles d ON d.id = s.driver_id
               WHERE a.snapshot_path IS NOT NULL
               ORDER BY a.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return jsonify({"evidence": [dict(row) for row in rows]})


@bp.route("/api/features/evidence/<int:alert_id>/image")
def feature_evidence_image(alert_id: int):
    ensure_feature_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT snapshot_path FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
    if row is None or not row["snapshot_path"]:
        abort(404)
    filename = Path(row["snapshot_path"]).name
    return send_from_directory(EVIDENCE_DIR, filename, conditional=True)
