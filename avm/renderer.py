"""フレームの描画と動画の書き出し。"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from . import media
from .model import Item, Project
from .timeline import (Cancelled, Timeline, build_timeline, mix_audio, parse_project,
                       resolve_voices)

ProgressFn = Callable[[str, float], None]

FONT_FAMILIES = ["Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "Noto Sans JP", "MS Gothic", "Sans Serif"]


def subtitle_font(px: float) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(max(8, int(px)))
    f.setBold(True)
    return f


def wrap_text(text: str, fm: QFontMetricsF, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\\n"):
        cur = ""
        for ch in para:
            if fm.horizontalAdvance(cur + ch) > max_w and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def draw_subtitle(p: QPainter, text: str, W: int, H: int, project: Project) -> None:
    if not text:
        return
    px = project.subtitle_size * (min(W, H) / min(project.width, project.height)) if project.subtitle_size > 0 \
        else min(W, H) * 0.055
    font = subtitle_font(px)
    fm = QFontMetricsF(font)
    lines = wrap_text(text, fm, W * 0.88)
    lh = fm.height() * 1.1
    block_h = lh * len(lines)
    bottom = H - H * 0.05
    top = bottom - block_h
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    if project.subtitle_box:
        bw = max(fm.horizontalAdvance(line) for line in lines) + px * 1.2
        rect = QRectF((W - bw) / 2, top - px * 0.35, bw, block_h + px * 0.7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(rect, px * 0.3, px * 0.3)
    path = QPainterPath()
    for i, line in enumerate(lines):
        x = (W - fm.horizontalAdvance(line)) / 2
        y = top + i * lh + fm.ascent()
        path.addText(QPointF(x, y), font, line)
    pen = QPen(QColor(project.subtitle_outline), max(2.0, px * 0.14))
    pen.setJoinStyle(Qt.RoundJoin)
    p.strokePath(path, pen)
    p.fillPath(path, QColor(project.subtitle_color))
    p.restore()


def ease_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def seg_value(segs, base: float, t: float) -> float:
    v = base
    for t0, t1, a, b in segs:
        if t < t0:
            break
        if t >= t1 or t1 <= t0:
            v = b
        else:
            v = a + (b - a) * ease_out((t - t0) / (t1 - t0))
            break
    return v


def motion_state(v, t: float, W: float, H: float, x: float, y: float, w: float, h: float):
    """登場・退場の動き → (dx, dy, 拡大率, 不透明度の倍率)。"""
    dx = dy = 0.0
    sc = al = 1.0
    phases = []
    if v.enter != "none" and v.enter_dur > 0 and t < v.start + v.enter_dur:
        phases.append((v.enter, 1 - ease_out((t - v.start) / v.enter_dur)))
    if v.exit != "none" and v.exit_dur > 0 and t > v.end - v.exit_dur:
        k = (t - (v.end - v.exit_dur)) / v.exit_dur
        phases.append((v.exit, min(1.0, max(0.0, k)) ** 2))
    for kind, k in phases:  # k: 0 = 定位置, 1 = 画面の外
        if kind == "left":
            dx += -(x + w) * k
        elif kind == "right":
            dx += (W - x) * k
        elif kind == "top":
            dy += -(y + h) * k
        elif kind == "bottom":
            dy += (H - y) * k
        elif kind == "fade":
            al *= 1 - k
        elif kind == "zoom":
            sc *= 1 - k
            al *= 1 - k * 0.5
    return dx, dy, sc, al


class FrameRenderer:
    def __init__(self, project: Project, tl: Timeline, scale: float = 1.0):
        self.project = project
        self.tl = tl
        self.scale = scale
        self.W = max(2, int(round(project.width * scale / 2)) * 2)
        self.H = max(2, int(round(project.height * scale / 2)) * 2)
        self._img_cache: dict[tuple, QImage] = {}
        self._videos: dict[int, media.VideoReader] = {}
        self.bg = QColor(project.bg_color)

    def _image(self, path: str, w: int, h: int) -> QImage | None:
        key = (path, w, h)
        if key in self._img_cache:
            return self._img_cache[key]
        img = QImage(path)
        if img.isNull():
            self._img_cache[key] = None  # type: ignore[assignment]
            return None
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(
            w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._img_cache[key] = img
        return img

    def _char_file(self, it: Item, fi: int) -> str:
        arr = self.tl.mouth.get(it.name)
        lv = float(arr[fi]) if arr is not None and fi < len(arr) else 0.0
        if it.file_half:
            if lv > 0.55 and it.file_open:
                return it.file_open
            if lv > 0.2:
                return it.file_half
            return it.file
        if lv > 0.3 and it.file_open:
            return it.file_open
        return it.file

    def render(self, fi: int) -> QImage:
        t = fi / self.tl.fps
        s = self.scale
        img = QImage(self.W, self.H, QImage.Format_RGBA8888)
        img.fill(self.bg)
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for vi, v in enumerate(self.tl.visibles):
            if not (v.start <= t < v.end):
                if vi in self._videos and t >= v.end:
                    self._videos.pop(vi).close()
                continue
            it = v.item
            x, y = int(round(it.x * s)), int(round(it.y * s))
            w, h = max(2, int(round(it.w * s))), max(2, int(round(it.h * s)))
            scale = seg_value(v.scale_segs, 1.0, t)
            alpha = seg_value(v.alpha_segs, it.opacity, t)
            dx, dy, msc, mal = motion_state(v, t, self.W, self.H, x, y, w, h)
            scale *= msc
            alpha *= mal
            if alpha <= 0.001 or scale <= 0.001:
                if it.kind == "video":  # 見えなくても再生位置は進める
                    rd = self._videos.get(vi)
                    if rd is not None:
                        rd.frame(int(round((t - v.start) * self.tl.fps)))
                continue
            im = None
            if it.kind == "video":
                rd = self._videos.get(vi)
                if rd is None:
                    rd = media.VideoReader(self.project.abspath(it.file), w, h, self.tl.fps, it.loop)
                    self._videos[vi] = rd
                local = int(round((t - v.start) * self.tl.fps))
                data = rd.frame(local)
                if data:
                    im = QImage(data, rd.w, rd.h, rd.w * 4, QImage.Format_RGBA8888)
            else:
                path = self._char_file(it, fi) if it.kind == "character" else it.file
                ms = max([1.0] + [b for *_, b in v.scale_segs])  # 拡大してもぼやけないように
                im = self._image(self.project.abspath(path), int(round(w * ms)), int(round(h * ms)))
            if im is None:
                continue
            if abs(scale - 1) < 1e-4 and alpha >= 0.999 and im.width() == w:
                p.drawImage(int(round(x + dx)), int(round(y + dy)), im)
            else:
                p.save()
                p.setOpacity(alpha)
                p.translate(x + dx + w / 2, y + dy + h / 2)
                p.scale(scale, scale)
                p.drawImage(QRectF(-w / 2, -h / 2, w, h), im)
                p.restore()
        if self.project.subtitles:
            for text, st, en in self.tl.subtitles:
                if st <= t < en:
                    draw_subtitle(p, text, self.W, self.H, self.project)
                    break
        p.end()
        return img

    def close(self) -> None:
        for rd in self._videos.values():
            rd.close()
        self._videos.clear()


def prepare(project: Project, progress: ProgressFn | None = None, cancel=None) -> Timeline:
    parsed = parse_project(project)
    voices, warns = resolve_voices(project, parsed, progress, cancel)
    tl = build_timeline(project, parsed, voices)
    tl.warnings = warns + tl.warnings
    return tl


def export_video(
    project: Project, out_path: str, scale: float = 1.0, start_time: float = 0.0,
    progress: ProgressFn | None = None, cancel: Callable[[], bool] | None = None, preview: bool = False,
) -> Timeline:
    """動画を書き出す。preview=True なら軽い設定で書き出す。"""
    progress = progress or (lambda m, f: None)
    cancel = cancel or (lambda: False)
    progress("準備中…", 0.0)
    tl = prepare(project, progress, cancel)
    progress("音声をミックス中…", 0.0)
    audio = mix_audio(project, tl)

    fps = tl.fps
    f_start = min(int(round(start_time * fps)), tl.frame_count - 1)
    f_end = tl.frame_count
    audio = audio[int(f_start / fps * media.SR):]

    rend = FrameRenderer(project, tl, scale)
    tmpdir = tempfile.mkdtemp(prefix="avm_")
    wav = os.path.join(tmpdir, "audio.wav")
    media.write_wav(wav, audio)
    dur = (f_end - f_start) / fps
    tmp_out = out_path + ".part.mp4"
    args = [
        media.ffmpeg_exe(), "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{rend.W}x{rend.H}", "-r", str(fps), "-i", "-",
        "-i", wav,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "ultrafast" if preview else "medium", "-crf", "28" if preview else "20",
        "-c:a", "aac", "-b:a", "128k" if preview else "192k",
        "-t", f"{dur:.3f}", "-movflags", "+faststart", tmp_out,
    ]
    errf = open(os.path.join(tmpdir, "ffmpeg.log"), "w+b")
    proc = media.popen(args, stdin=subprocess.PIPE, stderr=errf)
    t0 = time.time()
    try:
        assert proc.stdin is not None
        for fi in range(f_start, f_end):
            if cancel():
                raise Cancelled()
            img = rend.render(fi)
            proc.stdin.write(bytes(img.constBits()))
            if (fi - f_start) % 5 == 0:
                done = (fi - f_start + 1) / max(1, f_end - f_start)
                el = time.time() - t0
                rest = el / done - el if done > 0 else 0
                progress(f"{'プレビュー' if preview else '動画'}を作成中… {fi - f_start + 1}/{f_end - f_start} フレーム"
                         f"（残り約{int(rest)}秒）", done)
        proc.stdin.close()
        rc = proc.wait()
        if rc != 0:
            errf.seek(0)
            raise RuntimeError("FFmpeg でエラーが起きました:\n" + errf.read().decode(errors="replace")[-1500:])
        os.replace(tmp_out, out_path)
    except BaseException:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        proc.wait()
        if os.path.exists(tmp_out):
            try:
                os.remove(tmp_out)
            except OSError:
                pass
        raise
    finally:
        rend.close()
        errf.close()
        try:
            os.remove(wav)
        except OSError:
            pass
    progress("完了", 1.0)
    return tl
