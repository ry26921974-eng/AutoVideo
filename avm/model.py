"""プロジェクトのデータ構造と保存・読み込み。"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PROJECT_FILE = "project.avmproj"
FILE_VERSION = 1

# プロジェクトフォルダ内のサブフォルダ
FOLDERS = {
    "image": "画像",
    "video": "動画",
    "bgm": "BGM",
    "se": "SE",
    "voice": "ボイス",
    "character": "立ち絵",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}
AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".wma"}

ASPECTS: dict[str, tuple[int, int]] = {
    "16:9 横長 (1920x1080)": (1920, 1080),
    "9:16 縦長 (1080x1920)": (1080, 1920),
    "1:1 正方形 (1080x1080)": (1080, 1080),
    "4:3 (1440x1080)": (1440, 1080),
    "4:5 (1080x1350)": (1080, 1350),
    "16:9 HD (1280x720)": (1280, 720),
    "9:16 HD (720x1280)": (720, 1280),
}


@dataclass
class Item:
    """キャンバスに置く素材（画像・動画・立ち絵）。"""

    name: str
    kind: str = "image"  # image / video / character
    file: str = ""  # プロジェクトフォルダからの相対パス（または絶対パス）
    x: float = 0.0
    y: float = 0.0
    w: float = 400.0
    h: float = 300.0
    locked: bool = False
    z: int = 0
    # 動画用
    loop: bool = True
    use_audio: bool = False
    volume: float = 1.0
    # 立ち絵用
    file_open: str = ""  # 口開き画像
    file_half: str = ""  # 口半開き画像（任意）
    speaker_id: int = -1  # VOICEVOX 話者ID（-1 = プロジェクト既定）
    speed: float = 0.0  # 話速（0 = プロジェクト既定）

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Project:
    name: str = "新しいプロジェクト"
    aspect: str = "16:9 横長 (1920x1080)"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration: float = 0.0  # 0 = 台本の長さに合わせる
    bg_color: str = "#202020"
    # 字幕
    subtitles: bool = True
    subtitle_size: int = 0  # 0 = 自動
    subtitle_color: str = "#ffffff"
    subtitle_outline: str = "#000000"
    subtitle_box: bool = True
    # 音声
    voice_mode: str = "voicevox"  # voicevox / files
    voicevox_url: str = "http://127.0.0.1:50021"
    default_speaker: int = 3
    speed: float = 1.0
    scene_gap: float = 0.3
    voice_volume: float = 1.0
    bgm_volume: float = 0.3
    se_volume: float = 1.0
    # 中身
    script: str = ""
    items: list[Item] = field(default_factory=list)

    # 保存されない
    folder: str = field(default="", repr=False, compare=False)
    dirty: bool = field(default=False, repr=False, compare=False)

    # ---------- パス ----------
    def abspath(self, rel: str) -> str:
        if not rel:
            return ""
        if os.path.isabs(rel):
            return rel
        return os.path.normpath(os.path.join(self.folder, rel))

    def relpath(self, path: str) -> str:
        if not path:
            return ""
        try:
            rel = os.path.relpath(path, self.folder)
        except ValueError:  # 別ドライブ
            return path
        if rel.startswith(".."):
            return path
        return rel.replace("\\", "/")

    def subfolder(self, key: str) -> str:
        return os.path.join(self.folder, FOLDERS[key])

    def ensure_folders(self) -> None:
        for name in FOLDERS.values():
            os.makedirs(os.path.join(self.folder, name), exist_ok=True)

    # ---------- 素材 ----------
    def item(self, name: str) -> Item | None:
        for it in self.items:
            if it.name == name:
                return it
        return None

    def characters(self) -> list[Item]:
        return [it for it in self.items if it.kind == "character"]

    def unique_name(self, base: str) -> str:
        base = base.strip() or "素材"
        for ch in "[]［］:：":
            base = base.replace(ch, "_")
        names = {it.name for it in self.items}
        if base not in names:
            return base
        i = 2
        while f"{base}{i}" in names:
            i += 1
        return f"{base}{i}"

    def set_aspect(self, aspect: str) -> None:
        if aspect in ASPECTS:
            self.aspect = aspect
            self.width, self.height = ASPECTS[aspect]

    # ---------- 保存 ----------
    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("folder", None)
        d.pop("dirty", None)
        d["version"] = FILE_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        names = {f.name for f in fields(cls)} - {"items", "folder", "dirty"}
        p = cls(**{k: v for k, v in d.items() if k in names})
        p.items = [Item.from_dict(x) for x in d.get("items", [])]
        return p

    def save(self, path: str | None = None) -> str:
        if path is None:
            path = os.path.join(self.folder, PROJECT_FILE)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        self.dirty = False
        return path

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as f:
            p = cls.from_dict(json.load(f))
        p.folder = os.path.dirname(os.path.abspath(path))
        return p

    @classmethod
    def create(cls, folder: str, name: str | None = None) -> "Project":
        os.makedirs(folder, exist_ok=True)
        p = cls(name=name or Path(folder).name)
        p.folder = os.path.abspath(folder)
        p.ensure_folders()
        return p

    # ---------- まとめて保存 ----------
    def referenced_files(self) -> list[str]:
        """プロジェクトが参照しているすべてのファイル（相対/絶対）。"""
        from .script import parse_script  # 循環参照回避

        refs: list[str] = []
        for it in self.items:
            refs += [it.file, it.file_open, it.file_half]
        parsed = parse_script(self.script, [c.name for c in self.characters()])
        for sc in parsed.scenes:
            for cmd in sc.commands:
                if cmd.kind in ("bgm", "se", "voice") and cmd.arg:
                    refs.append(self.resolve_audio(cmd.kind, cmd.arg))
        return [r for r in refs if r]

    def resolve_audio(self, kind: str, arg: str) -> str:
        """台本中の音声ファイル名を実際のパスに変換。"""
        if os.path.isabs(arg) or "/" in arg or "\\" in arg:
            return self.abspath(arg)
        folder = {"bgm": "bgm", "se": "se", "voice": "voice"}[kind]
        cand = os.path.join(self.subfolder(folder), arg)
        if os.path.exists(cand):
            return cand
        # 他の音声フォルダも探す
        for key in ("bgm", "se", "voice"):
            c = os.path.join(self.subfolder(key), arg)
            if os.path.exists(c):
                return c
        return cand

    def collect_assets(self) -> list[str]:
        """プロジェクト外のファイルをプロジェクトフォルダにコピーし、参照を相対パスにする。

        戻り値: コピーしたファイルの一覧。
        """
        self.ensure_folders()
        copied: list[str] = []

        def bring(path: str, key: str) -> str:
            if not path:
                return path
            ap = self.abspath(path)
            if self.relpath(ap) != ap:  # すでにフォルダ内
                return self.relpath(ap)
            if not os.path.exists(ap):
                return path
            dst_dir = self.subfolder(key)
            dst = os.path.join(dst_dir, os.path.basename(ap))
            base, ext = os.path.splitext(dst)
            i = 2
            while os.path.exists(dst) and not _same_file(ap, dst):
                dst = f"{base}_{i}{ext}"
                i += 1
            if not os.path.exists(dst):
                shutil.copy2(ap, dst)
                copied.append(dst)
            return self.relpath(dst)

        for it in self.items:
            key = {"image": "image", "video": "video", "character": "character"}[it.kind]
            it.file = bring(it.file, key)
            it.file_open = bring(it.file_open, key)
            it.file_half = bring(it.file_half, key)
        self.save()
        return copied

    def export_zip(self, zip_path: str) -> None:
        """プロジェクトフォルダ一式を ZIP にまとめる（書き出し動画とキャッシュは除く）。"""
        root = Path(self.folder)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in root.rglob("*"):
                if p.is_dir():
                    continue
                rel = p.relative_to(root)
                if rel.parts and rel.parts[0] in (".cache", "書き出し"):
                    continue
                if os.path.abspath(p) == os.path.abspath(zip_path):
                    continue
                zf.write(p, Path(root.name) / rel)


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.getsize(a) == os.path.getsize(b) and open(a, "rb").read(65536) == open(b, "rb").read(65536)
    except OSError:
        return False


def natural_key(s: str):
    import re

    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def list_files(folder: str, exts: set[str]) -> list[str]:
    if not os.path.isdir(folder):
        return []
    out = [f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in exts]
    return sorted(out, key=natural_key)
