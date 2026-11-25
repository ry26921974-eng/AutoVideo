"""自動動画メーカー 起動スクリプト。"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    base, alt, text = QColor(45, 45, 48), QColor(37, 37, 38), QColor(230, 230, 230)
    p.setColor(QPalette.Window, base)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, alt)
    p.setColor(QPalette.AlternateBase, base)
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(60, 60, 64))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, QColor(38, 120, 200))
    p.setColor(QPalette.HighlightedText, Qt.white)
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    app.setPalette(p)


def main() -> int:
    if hasattr(sys, "_MEIPASS"):
        os.chdir(os.path.dirname(sys.executable))
    app = QApplication(sys.argv)
    app.setApplicationName("自動動画メーカー")
    dark_palette(app)
    from avm.ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and sys.argv[1].endswith(".avmproj") and os.path.exists(sys.argv[1]):
        w.load_project_file(sys.argv[1])
    else:
        w.startup()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
