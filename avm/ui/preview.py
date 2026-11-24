"""プレビュー（別ウインドウで動画再生）と、書き出し処理のスレッド。"""
from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout)

from ..model import Project
from ..renderer import export_video
from ..timeline import Cancelled

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    HAS_MM = True
except Exception:  # noqa: BLE001
    HAS_MM = False


class RenderWorker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(str, list)  # 出力パス, 警告
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, project: Project, out_path: str, scale: float, start_time: float, preview: bool):
        super().__init__()
        # 書き出し中に編集されても影響しないようにコピー
        self.project = Project.from_dict(project.to_dict())
        self.project.folder = project.folder
        self.out_path, self.scale, self.start_time, self.preview = out_path, scale, start_time, preview
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            tl = export_video(
                self.project, self.out_path, self.scale, self.start_time,
                progress=lambda m, f: self.progress.emit(m, f),
                cancel=lambda: self._cancel, preview=self.preview,
            )
            self.finished_ok.emit(self.out_path, tl.warnings)
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(e))


def fmt_time(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


class PreviewWindow(QDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("プレビュー")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(960, 640)
        self.path = path
        lay = QVBoxLayout(self)
        if not HAS_MM:
            lay.addWidget(QLabel("このPCでは内蔵プレーヤーが使えないため、既定のプレーヤーで開きます。"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        self.video = QVideoWidget(self)
        self.video.setStyleSheet("background:black")
        lay.addWidget(self.video, 1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        bar = QHBoxLayout()
        self.play_btn = QPushButton("一時停止")
        self.play_btn.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("0:00 / 0:00")
        ext = QPushButton("外部プレーヤーで開く")
        ext.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.path)))
        bar.addWidget(self.play_btn)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.time)
        bar.addWidget(ext)
        lay.addLayout(bar)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.positionChanged.connect(self._pos)
        self.player.setSource(QUrl.fromLocalFile(path))
        QTimer.singleShot(100, self.player.play)

    def _pos(self, p):
        if not self.slider.isSliderDown():
            self.slider.setValue(p)
        self.time.setText(f"{fmt_time(p)} / {fmt_time(self.player.duration())}")

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_btn.setText("再生")
        else:
            self.player.play()
            self.play_btn.setText("一時停止")

    def closeEvent(self, e):
        if HAS_MM:
            self.player.stop()
            self.player.setSource(QUrl())
        super().closeEvent(e)


def open_folder(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))
