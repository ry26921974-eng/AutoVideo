"""台本からタイムライン（いつ何を表示・再生するか）を組み立てる。"""
from __future__ import annotations

import copy
import math
import os
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import media
from .model import AUDIO_EXTS, Item, Project, list_files
from .script import ParsedScript, Scene, parse_script
from .voicevox import Voicevox

ProgressFn = Callable[[str, float], None]  # (メッセージ, 0..1)


class Cancelled(Exception):
    pass


@dataclass
class SceneTiming:
    scene: Scene
    start: float
    end: float
    voice: str = ""  # 音声ファイルの絶対パス
    voice_len: float = 0.0


@dataclass
class Visible:
    item: Item
    start: float
    end: float
    enter: str = "none"
    enter_dur: float = 0.0
    exit: str = "none"
    exit_dur: float = 0.0
    # (開始, 終了, 前の値, 次の値) の並び
    scale_segs: list[tuple[float, float, float, float]] = field(default_factory=list)
    alpha_segs: list[tuple[float, float, float, float]] = field(default_factory=list)


@dataclass
class _Open:
    start: float
    enter: str
    enter_dur: float
    scale: float = 1.0
    alpha: float = 1.0
    scale_segs: list = field(default_factory=list)
    alpha_segs: list = field(default_factory=list)


@dataclass
class AudioEvent:
    path: str
    start: float
    end: float | None  # None = 最後まで1回
    gain: float
    loop: bool = False


@dataclass
class Timeline:
    fps: int
    total: float
    scenes: list[SceneTiming] = field(default_factory=list)
    visibles: list[Visible] = field(default_factory=list)
    audio: list[AudioEvent] = field(default_factory=list)
    subtitles: list[tuple[str, float, float]] = field(default_factory=list)
    mouth: dict[str, np.ndarray] = field(default_factory=dict)  # キャラ名 → フレームごとの口の開き(0..1)
    warnings: list[str] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return max(1, int(round(self.total * self.fps)))

    def scene_start(self, index: int) -> float:
        for st in self.scenes:
            if st.scene.index == index:
                return st.start
        return 0.0


def parse_project(project: Project) -> ParsedScript:
    return parse_script(project.script, [c.name for c in project.characters()])


def speaker_item(project: Project, scene: Scene) -> Item | None:
    if scene.speaker:
        return project.item(scene.speaker)
    chars = project.characters()
    return chars[0] if len(chars) == 1 else None


def resolve_voices(
    project: Project, parsed: ParsedScript, progress: ProgressFn | None = None,
    cancel: Callable[[], bool] | None = None,
) -> tuple[dict[int, str], list[str]]:
    """フレームごとの音声ファイルを決める（VOICEVOX ならここで合成）。"""
    voices: dict[int, str] = {}
    warnings: list[str] = []
    if project.voice_mode == "none":
        return voices, warnings
    text_scenes = [s for s in parsed.scenes if s.text]

    # 明示指定 [音声:xxx]
    for s in parsed.scenes:
        if s.voice_file:
            p = project.resolve_audio("voice", s.voice_file)
            if os.path.exists(p):
                voices[s.index] = p
            else:
                warnings.append(f"フレーム{s.index + 1}: 音声ファイルが見つかりません: {s.voice_file}")

    if project.voice_mode == "files":
        files = list_files(project.subfolder("voice"), AUDIO_EXTS)
        explicit = {os.path.basename(v) for v in voices.values()}
        files = [f for f in files if f not in explicit]
        fi = 0
        for s in text_scenes:
            if s.index in voices:
                continue
            if fi < len(files):
                voices[s.index] = os.path.join(project.subfolder("voice"), files[fi])
                fi += 1
        return voices, warnings

    # VOICEVOX
    todo = [s for s in text_scenes if s.index not in voices]
    if not todo:
        return voices, warnings
    vv = Voicevox(project.voicevox_url)
    cache = os.path.join(project.folder, ".cache", "voicevox")
    for n, s in enumerate(todo):
        if cancel and cancel():
            raise Cancelled()
        if progress:
            progress(f"VOICEVOX で音声を作成中… ({n + 1}/{len(todo)})", n / len(todo))
        it = speaker_item(project, s)
        spk = it.speaker_id if it and it.speaker_id >= 0 else project.default_speaker
        spd = it.speed if it and it.speed > 0 else project.speed
        voices[s.index] = vv.synthesize_cached(s.text, spk, spd, cache)
    return voices, warnings


def build_timeline(project: Project, parsed: ParsedScript, voices: dict[int, str]) -> Timeline:
    tl = Timeline(fps=project.fps, total=0.0)
    t = 0.0
    for s in parsed.scenes:
        vpath = voices.get(s.index, "")
        vlen = 0.0
        if vpath:
            try:
                vlen = media.audio_duration(vpath)
            except Exception as e:  # noqa: BLE001
                tl.warnings.append(f"フレーム{s.index + 1}: 音声を読めません ({e})")
                vpath = ""
        if s.dur_override is not None:
            d = max(0.0, s.dur_override)
        elif vlen > 0:
            d = vlen + project.scene_gap
        elif s.text:
            d = max(1.5, len(s.text) * 0.12 + 0.6)
        else:
            d = 1.0
        tl.scenes.append(SceneTiming(s, t, t + d, vpath, vlen))
        t += d

    script_len = t
    tl.total = project.duration if project.duration > 0 else max(script_len, 1.0 / project.fps)
    if not tl.scenes and project.duration <= 0:
        tl.total = 3.0
    total = tl.total

    # 最後のフレームは指定秒数まで延長する
    if tl.scenes and tl.scenes[-1].end < total:
        tl.scenes[-1].end = total

    open_items: dict[str, _Open] = {}
    order: list[str] = []
    bgm: tuple[str, float] | None = None

    def close_item(name: str, at: float, exit_motion: str | None = None, exit_dur: float | None = None,
                   final: bool = False) -> None:
        st = open_items.pop(name, None)
        it = project.item(name)
        if st is None or it is None:
            return
        ex = exit_motion if exit_motion is not None else it.exit
        exd = exit_dur if exit_dur is not None else it.exit_dur
        if final or ex == "none":
            ex, exd = "none", 0.0
        end = at + exd
        if end > st.start:
            tl.visibles.append(Visible(copy.copy(it), st.start, min(end, total), st.enter, st.enter_dur, ex, exd,
                                       st.scale_segs, st.alpha_segs))

    def close_bgm(at: float) -> None:
        nonlocal bgm
        if bgm and at > bgm[1]:
            tl.audio.append(AudioEvent(bgm[0], bgm[1], at, project.bgm_volume, loop=True))
        bgm = None

    for st in tl.scenes:
        if st.start >= total:
            break
        at = st.start
        for c in st.scene.commands:
            if c.kind == "show":
                it = project.item(c.name)
                if it is None:
                    tl.warnings.append(f"フレーム{st.scene.index + 1}: 素材「{c.name}」がありません")
                    continue
                if c.name not in open_items:
                    o = c.options()
                    open_items[c.name] = _Open(at, o.get("motion", it.enter), o.get("dur", it.enter_dur),
                                               1.0, it.opacity)
                    if c.name in order:
                        order.remove(c.name)
                    order.append(c.name)
            elif c.kind == "hide":
                o = c.options()
                close_item(c.name, at, o.get("motion"), o.get("dur"))
            elif c.kind == "hideall":
                for n in list(open_items):
                    close_item(n, at)
            elif c.kind in ("scale", "alpha"):
                ob = open_items.get(c.name)
                if ob is None:
                    tl.warnings.append(f"フレーム{st.scene.index + 1}: 「{c.name}」は表示されていないので変更できません")
                    continue
                o = c.options()
                if "percent" not in o:
                    tl.warnings.append(f"フレーム{st.scene.index + 1}: {c.raw} に % の値がありません")
                    continue
                dur = max(0.0, o.get("dur", 0.5))
                if c.kind == "scale":
                    target = max(0.0, o["percent"] / 100)
                    ob.scale_segs.append((at, at + dur, ob.scale, target))
                    ob.scale = target
                else:
                    target = min(1.0, max(0.0, 1 - o["percent"] / 100))
                    ob.alpha_segs.append((at, at + dur, ob.alpha, target))
                    ob.alpha = target
            elif c.kind == "bgm":
                close_bgm(at)
                p = project.resolve_audio("bgm", c.arg)
                if os.path.exists(p):
                    bgm = (p, at)
                else:
                    tl.warnings.append(f"フレーム{st.scene.index + 1}: BGMが見つかりません: {c.arg}")
            elif c.kind == "bgm_stop":
                close_bgm(at)
            elif c.kind == "se":
                p = project.resolve_audio("se", c.arg)
                if os.path.exists(p):
                    tl.audio.append(AudioEvent(p, at, None, project.se_volume))
                else:
                    tl.warnings.append(f"フレーム{st.scene.index + 1}: SEが見つかりません: {c.arg}")
        if st.voice:
            tl.audio.append(AudioEvent(st.voice, st.start, min(st.end, total), project.voice_volume))
        if st.scene.text:
            tl.subtitles.append((st.scene.text, st.start, min(st.end, total)))
    for n in list(open_items):
        close_item(n, total, final=True)
    close_bgm(total)

    # 表示の順番：z → 表示した順
    rank = {n: i for i, n in enumerate(order)}
    tl.visibles.sort(key=lambda v: (v.item.z, rank.get(v.item.name, 0), v.start))

    # 動画の音声
    for v in tl.visibles:
        if v.item.kind == "video" and v.item.use_audio:
            tl.audio.append(AudioEvent(project.abspath(v.item.file), v.start, v.end, v.item.volume, v.item.loop))
    return tl


def mix_audio(project: Project, tl: Timeline) -> np.ndarray:
    """全音声をミックスし、同時にリップシンク用の口の開きを計算する。"""
    n = int(math.ceil(tl.total * media.SR)) + 1
    out = np.zeros((n, media.CH), dtype=np.float32)
    for ev in tl.audio:
        try:
            a = media.load_audio(ev.path)
        except Exception as e:  # noqa: BLE001
            tl.warnings.append(f"音声を読めません: {os.path.basename(ev.path)} ({e})")
            continue
        if len(a) == 0:
            continue
        s = int(ev.start * media.SR)
        e = n if ev.end is None else min(n, int(ev.end * media.SR))
        if ev.end is None:
            e = min(n, s + len(a))
        length = e - s
        if length <= 0:
            continue
        if ev.loop and len(a) < length:
            reps = int(math.ceil(length / len(a)))
            a = np.tile(a, (reps, 1))
        seg = a[:length]
        out[s:s + len(seg)] += seg * ev.gain

    # リップシンク
    hop = media.SR / tl.fps
    fc = tl.frame_count
    for st in tl.scenes:
        if not st.voice:
            continue
        it = speaker_item(project, st.scene)
        if it is None or it.kind != "character":
            continue
        try:
            v = media.load_audio(st.voice).mean(axis=1)
        except Exception:  # noqa: BLE001
            continue
        arr = tl.mouth.setdefault(it.name, np.zeros(fc, dtype=np.float32))
        f0 = int(round(st.start * tl.fps))
        nf = int(len(v) / hop)
        rms = np.zeros(nf, dtype=np.float32)
        for i in range(nf):
            seg = v[int(i * hop): int((i + 1) * hop)]
            rms[i] = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
        ref = float(np.percentile(rms, 95)) if nf else 0.0
        if ref <= 1e-4:
            continue
        lv = np.clip(rms / ref, 0, 1)
        end = min(fc, f0 + nf, int(round(min(st.end, tl.total) * tl.fps)))
        if end > f0:
            arr[f0:end] = np.maximum(arr[f0:end], lv[: end - f0])
    return out
