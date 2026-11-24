"""サンプルプロジェクト（サンプル/）を作り直すスクリプト。

    python tools/make_sample.py
"""
import math
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen, QPolygonF)

from avm import media  # noqa: E402
from avm.model import Item, Project  # noqa: E402

OUT = os.path.join(ROOT, "サンプル")


def canvas(w, h, transparent=True):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent if transparent else Qt.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    return img, p


def pen(color, width, cap=Qt.SquareCap, join=Qt.BevelJoin):
    pn = QPen(QColor(color), width)
    pn.setCapStyle(cap)
    pn.setJoinStyle(join)
    return pn


def font(px, bold=True):
    f = QFont()
    f.setFamilies(["Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "Sans Serif"])
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def title_card(path):
    img, p = canvas(1280, 720, False)
    g = QLinearGradient(0, 0, 1280, 720)
    g.setColorAt(0, QColor("#ff9a8b"))
    g.setColorAt(0.5, QColor("#ff6a88"))
    g.setColorAt(1, QColor("#7a5cff"))
    p.fillRect(img.rect(), g)
    p.setPen(QColor(255, 255, 255, 60))
    for i in range(14):
        p.setBrush(QColor(255, 255, 255, 25))
        r = 30 + (i * 37) % 90
        p.drawEllipse(QPointF((i * 211) % 1280, (i * 137) % 720), r, r)
    p.setPen(Qt.white)
    p.setFont(font(96))
    p.drawText(QRectF(0, 200, 1280, 160), Qt.AlignCenter, "自動動画メーカー")
    p.setFont(font(48, False))
    p.drawText(QRectF(0, 380, 1280, 80), Qt.AlignCenter, "サンプル動画")
    p.end()
    img.save(path)


def apple(path):
    img, p = canvas(500, 500)
    p.setPen(pen("#5d2a0c", 18, cap=Qt.RoundCap))
    p.drawLine(250, 130, 270, 50)
    leaf = QPainterPath()
    leaf.moveTo(270, 90)
    leaf.cubicTo(320, 20, 400, 40, 410, 70)
    leaf.cubicTo(380, 120, 300, 130, 270, 90)
    p.fillPath(leaf, QColor("#4caf50"))
    body = QPainterPath()
    body.moveTo(250, 140)
    body.cubicTo(120, 60, 20, 200, 70, 330)
    body.cubicTo(110, 450, 200, 480, 250, 440)
    body.cubicTo(300, 480, 390, 450, 430, 330)
    body.cubicTo(480, 200, 380, 60, 250, 140)
    g = QLinearGradient(100, 120, 400, 460)
    g.setColorAt(0, QColor("#ff5252"))
    g.setColorAt(1, QColor("#b71c1c"))
    p.fillPath(body, g)
    p.setBrush(QColor(255, 255, 255, 110))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(120, 190, 60, 110))
    p.end()
    img.save(path)


def star(path):
    img, p = canvas(400, 400)
    pts = []
    for i in range(10):
        r = 190 if i % 2 == 0 else 80
        a = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(200 + r * math.cos(a), 205 + r * math.sin(a)))
    p.setPen(pen("#f57f17", 10, join=Qt.RoundJoin))
    p.setBrush(QColor("#ffd54f"))
    p.drawPolygon(QPolygonF(pts))
    p.end()
    img.save(path)


def character(path, mouth_open, half=False):
    """丸いキャラクター「まる」。"""
    img, p = canvas(500, 640)
    # 体
    p.setPen(QPen(QColor("#2e5c8a"), 8))
    p.setBrush(QColor("#64b5f6"))
    p.drawEllipse(QRectF(60, 330, 380, 300))
    # 顔
    p.setBrush(QColor("#ffe0b2"))
    p.setPen(QPen(QColor("#8d6e63"), 8))
    p.drawEllipse(QRectF(70, 40, 360, 340))
    # 耳
    p.setBrush(QColor("#ffe0b2"))
    p.drawEllipse(QRectF(45, 170, 60, 80))
    p.drawEllipse(QRectF(395, 170, 60, 80))
    # 髪
    hair = QPainterPath()
    hair.moveTo(80, 200)
    hair.cubicTo(60, 20, 440, 20, 420, 200)
    hair.cubicTo(380, 120, 300, 100, 250, 140)
    hair.cubicTo(200, 100, 120, 120, 80, 200)
    p.fillPath(hair, QColor("#5d4037"))
    # 目
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#3e2723"))
    p.drawEllipse(QRectF(160, 200, 40, 56))
    p.drawEllipse(QRectF(300, 200, 40, 56))
    p.setBrush(Qt.white)
    p.drawEllipse(QRectF(172, 210, 14, 18))
    p.drawEllipse(QRectF(312, 210, 14, 18))
    # ほっぺ
    p.setBrush(QColor(255, 120, 120, 120))
    p.drawEllipse(QRectF(115, 265, 60, 34))
    p.drawEllipse(QRectF(325, 265, 60, 34))
    # 口
    if mouth_open:
        h = 30 if half else 62
        p.setBrush(QColor("#c62828"))
        p.setPen(QPen(QColor("#5d1a1a"), 5))
        p.drawEllipse(QRectF(220, 285, 60, h))
        if not half:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ef9a9a"))
            p.drawEllipse(QRectF(232, 320, 36, 22))
    else:
        p.setPen(pen("#5d1a1a", 6, cap=Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(220, 270, 60, 40), 200 * 16, 140 * 16)
    p.end()
    img.save(path)


def save_wav(path, a, sr=48000):
    a = np.clip(a, -1, 1)
    st = np.stack([a, a], axis=1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((st * 32767).astype("<i2").tobytes())


def tone(freq, dur, sr=48000, kind="square", vol=0.2):
    t = np.arange(int(dur * sr)) / sr
    if kind == "square":
        w = np.sign(np.sin(2 * np.pi * freq * t)) * 0.6
    elif kind == "tri":
        w = 2 / np.pi * np.arcsin(np.sin(2 * np.pi * freq * t))
    else:
        w = np.sin(2 * np.pi * freq * t)
    env = np.minimum(1, t / 0.01) * np.exp(-t * 3)
    return w * env * vol


def bgm(path):
    """ほのぼのした8小節のループ（自作・自由に使えます）。"""
    sr, bpm = 48000, 112
    beat = 60 / bpm
    note = lambda n: 440 * 2 ** ((n - 69) / 12)  # noqa: E731
    melody = [72, 76, 79, 76, 77, 76, 74, 72, 74, 77, 81, 77, 76, 74, 72, 71,
              72, 76, 79, 84, 81, 79, 77, 76, 74, 77, 76, 74, 72, 72, 72, 0]
    chords = [48, 48, 53, 53, 50, 50, 55, 55]
    total = len(melody) * beat / 2
    out = np.zeros(int(total * sr) + sr)
    for i, n in enumerate(melody):
        if n:
            s = int(i * beat / 2 * sr)
            w = tone(note(n), beat / 2 * 0.95, sr, "square", 0.08)
            out[s:s + len(w)] += w
    for i, c in enumerate(chords):
        for k in range(4):
            s = int((i * 4 + k) * beat / 2 * sr)
            for off in (0, 4, 7):
                w = tone(note(c + off + (12 if k % 2 else 0)), beat / 2, sr, "tri", 0.06)
                out[s:s + len(w)] += w
    out = out[: int(total * sr)]
    tmp = path + ".wav"
    save_wav(tmp, out)
    subprocess.run([media.ffmpeg_exe(), "-y", "-v", "error", "-i", tmp, "-c:a", "libmp3lame", "-b:a", "128k", path],
                   check=True)
    os.remove(tmp)


def pon(path):
    sr = 48000
    t = np.arange(int(0.35 * sr)) / sr
    f = 900 * np.exp(-t * 6) + 400
    w = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 12) * 0.6
    save_wav(path, w)


def kira(path):
    sr = 48000
    out = np.zeros(int(0.8 * sr))
    for i, n in enumerate([1568, 2093, 2637, 3136]):
        w = tone(n, 0.5, sr, "sine", 0.25)
        s = int(i * 0.07 * sr)
        out[s:s + len(w)] += w[: len(out) - s]
    save_wav(path, out)


def video(path):
    subprocess.run([media.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi",
                    "-i", "gradients=s=640x360:speed=0.03:c0=0x3949ab:c1=0x00acc1:c2=0x7cb342:c3=0xfdd835:n=4:d=5",
                    "-vf", "drawtext=text='SAMPLE VIDEO':fontcolor=white:fontsize=48:x=(w-tw)/2:y=(h-th)/2:"
                    "shadowcolor=black@0.5:shadowx=3:shadowy=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", path], check=True)


SCRIPT = """# ===== サンプル台本 =====
# 1行 = 1フレーム。[ ] は命令です。右クリックからも入れられます。
# 「動画の設定」の音声で VOICEVOX を選ぶと、まるが喋ります（VOICEVOX を起動しておいてください）。

[画像:タイトル][BGM:sample_bgm.mp3][SE:きらーん.wav]
[秒数:3]
[消去:タイトル][画像:まる]
まる：こんにちは！自動動画メーカーのサンプルへようこそ。
まる：この動画は、台本と素材だけで作られています。
[画像:りんご][SE:ぽん.wav]
まる：例えば、画像はこんなふうに好きな場所に置けます。
まる：消すまでは、ずっと表示されたままです。
[画像:星][SE:きらーん.wav]
まる：画像をもう一つ。星を出してみました。
[消去:りんご][消去:星][画像:サンプル動画]
まる：動画を流すこともできます。
まる：BGMや効果音も、画像と同じように出したり止めたりできます。
[消去:サンプル動画][BGM停止]
まる：BGMを止めました。
[SE:ぽん.wav]
まる：それでは、あなたも動画を作ってみてください！
[全消去][画像:タイトル]
[秒数:2]
"""


def main():
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    p = Project.create(OUT, "サンプル")
    p.set_aspect("16:9 横長 (1920x1080)")
    p.voice_mode = "none"
    p.bg_color = "#fff3e0"
    p.bgm_volume = 0.35

    title_card(os.path.join(p.subfolder("image"), "タイトル.png"))
    apple(os.path.join(p.subfolder("image"), "りんご.png"))
    star(os.path.join(p.subfolder("image"), "星.png"))
    character(os.path.join(p.subfolder("character"), "まる_口閉じ.png"), False)
    character(os.path.join(p.subfolder("character"), "まる_口開き.png"), True)
    character(os.path.join(p.subfolder("character"), "まる_半開き.png"), True, half=True)
    video(os.path.join(p.subfolder("video"), "サンプル動画.mp4"))
    bgm(os.path.join(p.subfolder("bgm"), "sample_bgm.mp3"))
    pon(os.path.join(p.subfolder("se"), "ぽん.wav"))
    kira(os.path.join(p.subfolder("se"), "きらーん.wav"))

    p.items = [
        Item("タイトル", "image", "画像/タイトル.png", 0, 0, 1920, 1080, True, z=0),
        Item("りんご", "image", "画像/りんご.png", 260, 220, 450, 450, True, z=1),
        Item("星", "image", "画像/星.png", 780, 140, 320, 320, True, z=1),
        Item("サンプル動画", "video", "動画/サンプル動画.mp4", 180, 160, 1120, 630, True, z=1),
        Item("まる", "character", "立ち絵/まる_口閉じ.png", 1380, 380, 440, 563, True, z=5,
             file_open="立ち絵/まる_口開き.png", file_half="立ち絵/まる_半開き.png", speaker_id=3),
    ]
    p.script = SCRIPT
    p.save()
    with open(os.path.join(OUT, "はじめにお読みください.txt"), "w", encoding="utf-8") as f:
        f.write(
            "サンプルプロジェクトです。\n"
            "アプリの「ファイル → サンプルを開く」で、このサンプルのコピーを開けます。\n"
            "プレビュー(F5)や書き出し(Ctrl+E)を試してみてください。\n"
            "VOICEVOX を起動して、動画の設定の音声を「VOICEVOX」にすると、まるが喋って口パクします。\n"
            "素材（画像・BGM・効果音・動画）はすべてこのアプリ用に作ったもので、自由に使えます。\n"
        )
    print("作成しました:", OUT)


if __name__ == "__main__":
    main()
