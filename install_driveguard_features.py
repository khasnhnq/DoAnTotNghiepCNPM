from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
INDEX = ROOT / "templates" / "index.html"
BACKUP_DIR = ROOT / ".driveguard_feature_backups"


def replace_once(text: str, old: str, new: str, filename: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Khong the tu dong cap nhat {filename}: can tim thay dung 1 lan chuoi neo, nhung tim thay {count}. "
            "Khong co file nao bi sua boi buoc nay."
        )
    return text.replace(old, new, 1)


def main() -> None:
    required = [APP, INDEX, ROOT / "camera_stream.py", ROOT / "database.py"]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        raise SystemExit("Thieu tep bat buoc: " + ", ".join(missing))

    app_text = APP.read_text(encoding="utf-8")
    index_text = INDEX.read_text(encoding="utf-8")

    app_new = replace_once(
        app_text,
        "from camera_stream import CameraStream\n",
        "from camera_stream import CameraStream\n"
        "from driveguard_features import install_camera_extensions, register_feature_routes\n\n"
        "install_camera_extensions()\n",
        "app.py (import)",
    )
    app_new = replace_once(
        app_new,
        "camera_stream = CameraStream()\n",
        "camera_stream = CameraStream()\n"
        "register_feature_routes(app, camera_stream)\n",
        "app.py (camera_stream)",
    )

    nav_link = (
        '        <a class="nav-item" href="/advanced">\n'
        '          <span class="nav-icon">✦</span> Chức năng nâng cao\n'
        '        </a>\n\n'
    )
    index_new = replace_once(
        index_text,
        '        <div class="sidebar-bottom">',
        nav_link + '        <div class="sidebar-bottom">',
        "templates/index.html",
    )

    BACKUP_DIR.mkdir(exist_ok=True)
    shutil.copy2(APP, BACKUP_DIR / "app.py.before_features")
    shutil.copy2(INDEX, BACKUP_DIR / "index.html.before_features")
    APP.write_text(app_new, encoding="utf-8")
    INDEX.write_text(index_new, encoding="utf-8")

    gitignore = ROOT / ".gitignore"
    gitignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    additions = []
    for item in ("# DriveGuard feature backups", ".driveguard_feature_backups/", "# Alert evidence contains camera images", "static/evidence/"):
        if item not in gitignore_text:
            additions.append(item)
    if additions:
        with gitignore.open("a", encoding="utf-8") as handle:
            if gitignore_text and not gitignore_text.endswith("\n"):
                handle.write("\n")
            handle.write("\n".join(additions) + "\n")

    print("Da cap nhat app.py va templates/index.html.")
    print("Da tao backup tai .driveguard_feature_backups/.")
    print("Da bo qua static/evidence/ va backup khi push len Git.")
    print("Tiep theo: python -m py_compile .\\driveguard_features.py .\\app.py .\\camera_stream.py")


if __name__ == "__main__":
    main()
