from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from voiceclean.database import Database
from voiceclean.ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ducky-voice-optimizer")
    app.setApplicationDisplayName("Ducky Voice Optimizer")
    app.setOrganizationName("Ducky Voice Optimizer")
    app.setStyle("Fusion")
    app.setFont(QFont("Inter, Noto Sans, Segoe UI", 10))
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon_path = root / "assets" / "ducky-voice-optimizer.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    data_root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    data_root.mkdir(parents=True, exist_ok=True)
    database = Database(data_root / "projects.sqlite3")
    window = MainWindow(database, data_root / "projects")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
