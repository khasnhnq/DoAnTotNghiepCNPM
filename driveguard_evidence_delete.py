"""Safe per-image deletion route for DriveGuard AI evidence snapshots.

Deletes only the JPEG/PNG file referenced by alerts.snapshot_path and clears
that field. The alert row itself is retained, so history/session statistics stay.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from flask import jsonify


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_DIR / "drowsiness.db"
EVIDENCE_DIR = (PROJECT_DIR / "static" / "evidence").resolve()


def _resolve_evidence_file(snapshot_path: str) -> Path:
    """Resolve only paths under static/evidence; reject traversal/other paths."""
    normalized = str(snapshot_path).strip().replace("\\", "/")
    if not normalized:
        raise ValueError("Đường dẫn ảnh trống")

    # Current project values commonly look like evidence/name.jpg.
    # Also accept static/evidence/name.jpg for older records.
    if normalized.startswith("static/evidence/"):
        relative = normalized[len("static/evidence/"):]
    elif normalized.startswith("evidence/"):
        relative = normalized[len("evidence/"):]
    else:
        raise ValueError("Đường dẫn ảnh không thuộc static/evidence")

    # Only direct child files are allowed; no nested folders or traversal.
    rel = Path(relative)
    if rel.is_absolute() or len(rel.parts) != 1 or rel.name in ("", ".", ".."):
        raise ValueError("Đường dẫn ảnh không hợp lệ")

    if rel.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("Định dạng ảnh không được phép")

    candidate = (EVIDENCE_DIR / rel.name).resolve()
    if candidate.parent != EVIDENCE_DIR:
        raise ValueError("Đường dẫn ảnh nằm ngoài thư mục minh chứng")

    return candidate


def register_evidence_delete_route(app, db_path: Optional[str | Path] = None) -> None:
    """Register DELETE /api/features/evidence/<alert_id> on the Flask app."""
    database_path = Path(db_path) if db_path else Path(
        os.environ.get("DRIVEGUARD_DB_PATH", str(DEFAULT_DB_PATH))
    )
    if not database_path.is_absolute():
        database_path = (PROJECT_DIR / database_path).resolve()

    @app.route("/api/features/evidence/<int:alert_id>", methods=["DELETE"])
    def delete_evidence(alert_id: int):
        if not database_path.exists():
            return jsonify(success=False, message="Không tìm thấy database của DriveGuard AI."), 500

        conn = None
        try:
            conn = sqlite3.connect(str(database_path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT rowid AS alert_id, snapshot_path "
                "FROM alerts WHERE rowid = ?",
                (alert_id,),
            ).fetchone()

            if row is None:
                conn.rollback()
                return jsonify(success=False, message="Không tìm thấy sự kiện cảnh báo."), 404

            snapshot_path = row["snapshot_path"]
            if not snapshot_path:
                conn.rollback()
                return jsonify(success=False, message="Sự kiện này không còn ảnh minh chứng."), 404

            try:
                image_path = _resolve_evidence_file(snapshot_path)
            except ValueError as exc:
                conn.rollback()
                return jsonify(success=False, message=str(exc)), 400

            # Clear only the image reference. Keep the alert record unchanged.
            conn.execute(
                "UPDATE alerts SET snapshot_path = NULL WHERE rowid = ?",
                (alert_id,),
            )
            conn.commit()

            file_deleted = False
            file_error = None
            try:
                if image_path.exists() and image_path.is_file():
                    image_path.unlink()
                    file_deleted = True
            except OSError as exc:
                # The DB link is already cleared; report a leftover file for manual cleanup.
                file_error = str(exc)

            payload = {
                "success": True,
                "message": "Đã xóa ảnh minh chứng. Lịch sử cảnh báo vẫn được giữ.",
                "alert_id": alert_id,
                "file_deleted": file_deleted,
            }
            if file_error:
                payload["warning"] = "Đã gỡ liên kết trong database nhưng chưa xóa được file: " + file_error
            return jsonify(payload), 200

        except sqlite3.Error as exc:
            if conn is not None:
                conn.rollback()
            app.logger.exception("Không thể xóa ảnh minh chứng cho alert %s", alert_id)
            return jsonify(success=False, message="Lỗi SQLite khi xóa ảnh minh chứng: " + str(exc)), 500
        finally:
            if conn is not None:
                conn.close()
