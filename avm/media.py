"""FFmpeg を使った音声・動画の読み込み。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import wave

import numpy as np

SR = 48000  # 内部のサンプリングレート
CH = 2

_FFMPEG: str | None = None


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ffmpeg_exe() -> str:
    """FFmpeg の場所を探す。"""
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    cands = [os.environ.get("AVM_FFMPEG", "")]
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    cands += [os.path.join(app_dir(), "ffmpeg", exe), os.path.join(app_dir(), exe)]
    for c in cands:
        if c and os.path.isfile(c):
            _FFMPEG = c
            return c
    try:
        import imageio_ffmpeg

        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG
    except Exception:
        pass
    w = shutil.which("ffmpeg")
    if w:
        _FFMPEG = w
        return w
    raise RuntimeError(
        "FFmpeg が見つかりません。requirements.txt のインストール（imageio-ffmpeg）を確認するか、"
        "アプリのフォルダに ffmpeg フォルダを置いてください。"
    )


def _popen_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, **_popen_kwargs(), **kw)


def popen(args: list[str], **kw) -> subprocess.Popen:
    return subprocess.Popen(args, **_popen_kwargs(), **kw)


_audio_cache: dict[tuple[str, float], np.ndarray] = {}


def load_audio(path: str) -> np.ndarray:
    """音声（または動画の音声）を float32 の (N, 2) 配列で読み込む。"""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        raise FileNotFoundError(path)
    if key in _audio_cache:
        return _audio_cache[key]
    p = run([ffmpeg_exe(), "-v", "error", "-i", path, "-vn", "-f", "f32le", "-ac", str(CH), "-ar", str(SR), "-"])
    if p.returncode != 0 and not p.stdout:
        raise RuntimeError(f"音声を読み込めません: {path}\n{p.stderr.decode(errors='replace')[-500:]}")
    a = np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, CH).copy()
    if len(_audio_cache) > 64:
        _audio_cache.clear()
    _audio_cache[key] = a
    return a


def audio_duration(path: str) -> float:
    return len(load_audio(path)) / SR


def write_wav(path: str, audio: np.ndarray) -> None:
    a = np.clip(audio, -1.0, 1.0)
    data = (a * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(CH)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)


def video_first_frame(path: str, max_size: int = 640) -> bytes | None:
    """動画の最初のフレームを PNG で返す（サムネイル用）。"""
    p = run([
        ffmpeg_exe(), "-v", "error", "-i", path, "-frames:v", "1",
        "-vf", f"scale='min({max_size},iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-",
    ])
    return p.stdout if p.returncode == 0 and p.stdout else None


def video_size(path: str) -> tuple[int, int] | None:
    from PySide6.QtGui import QImage

    data = video_first_frame(path, 10000)
    if not data:
        return None
    img = QImage.fromData(data)
    return (img.width(), img.height()) if not img.isNull() else None


class VideoReader:
    """動画を指定サイズ・fps で1フレームずつ読む。"""

    def __init__(self, path: str, w: int, h: int, fps: int, loop: bool = True):
        self.path, self.w, self.h, self.fps, self.loop = path, max(2, w), max(2, h), fps, loop
        self.proc: subprocess.Popen | None = None
        self.last: bytes | None = None
        self.pos = -1
        self.ended = False
        self._start()

    def _start(self) -> None:
        self.close()
        self.proc = popen(
            [ffmpeg_exe(), "-v", "error", "-i", self.path, "-an",
             "-vf", f"fps={self.fps},scale={self.w}:{self.h}",
             "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.w * self.h * 4 * 2,
        )

    def _read_one(self) -> bytes | None:
        size = self.w * self.h * 4
        if self.proc is None or self.proc.stdout is None:
            return None
        buf = b""
        while len(buf) < size:
            chunk = self.proc.stdout.read(size - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def frame(self, index: int) -> bytes | None:
        """index 番目（0始まり）のフレームの RGBA バイト列。"""
        while self.pos < index and not self.ended:
            data = self._read_one()
            if data is None:
                if self.loop and self.pos >= 0:
                    self._start()
                    data = self._read_one()
                if data is None:
                    self.ended = True
                    break
            self.last = data
            self.pos += 1
        return self.last

    def close(self) -> None:
        if self.proc:
            try:
                if self.proc.stdout:
                    self.proc.stdout.close()
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None
