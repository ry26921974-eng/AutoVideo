"""台本の解析と編集。

台本の書き方（1行 = 1フレーム）:

    ずんだもん：こんにちは、ずんだもんなのだ！
    [画像:ねこ]
    ねこの写真を表示するのだ。
    [消去:ねこ] [SE:ぽん.wav]
    次の話題なのだ。
    [秒数:2]            ← セリフ無しで2秒待つフレーム

- 「キャラ名：セリフ」「キャラ名「セリフ」」で話者を指定（キャラ名は立ち絵の名前）。
- [ ] の命令は、その行または次のセリフ行（フレーム）の頭で実行されます。
- # で始まる行はコメント。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CMD_RE = re.compile(r"[\[［]([^\]］\n]*)[\]］]")

# 命令名 → 種類
CMD_ALIASES = {
    "画像": "show", "動画": "show", "表示": "show", "立ち絵": "show",
    "消去": "hide", "非表示": "hide", "消す": "hide",
    "全消去": "hideall", "すべて消去": "hideall", "全て消去": "hideall",
    "bgm": "bgm", "ｂｇｍ": "bgm",
    "bgm停止": "bgm_stop", "ｂｇｍ停止": "bgm_stop",
    "se": "se", "ｓｅ": "se", "効果音": "se",
    "音声": "voice", "ボイス": "voice",
    "秒数": "dur", "時間": "dur", "待機": "dur",
}

# 種類 → 書き出すときの表記
CMD_LABELS = {
    "show": "画像",
    "hide": "消去",
    "hideall": "全消去",
    "bgm": "BGM",
    "bgm_stop": "BGM停止",
    "se": "SE",
    "voice": "音声",
    "dur": "秒数",
}


@dataclass
class Command:
    kind: str
    arg: str
    line_no: int
    raw: str

    def describe(self) -> str:
        names = {
            "show": "表示", "hide": "消去", "hideall": "全消去", "bgm": "BGM開始",
            "bgm_stop": "BGM停止", "se": "SE再生", "voice": "音声ファイル", "dur": "秒数",
        }
        n = names.get(self.kind, self.kind)
        return f"{n}: {self.arg}" if self.arg else n


@dataclass
class Scene:
    """1フレーム（台本の1行）。"""

    index: int
    line_no: int  # このフレームのセリフ行（または待機行）の行番号（0始まり）
    first_line: int  # このフレームに属する命令の開始行
    text: str = ""
    speaker: str = ""
    commands: list[Command] = field(default_factory=list)

    @property
    def voice_file(self) -> str:
        for c in self.commands:
            if c.kind == "voice" and c.arg:
                return c.arg
        return ""

    @property
    def dur_override(self) -> float | None:
        val = None
        for c in self.commands:
            if c.kind == "dur":
                try:
                    val = float(c.arg.replace("秒", "").strip())
                except ValueError:
                    pass
        return val

    def label(self) -> str:
        t = self.text or "（セリフなし）"
        if len(t) > 28:
            t = t[:28] + "…"
        sp = f"[{self.speaker}] " if self.speaker else ""
        return f"{self.index + 1}: {sp}{t}"


@dataclass
class ParsedScript:
    scenes: list[Scene]
    trailing: list[Command]  # 最後のセリフより後ろの命令
    errors: list[str]


def parse_command(body: str, line_no: int, raw: str) -> Command | None:
    body = body.strip()
    if not body:
        return None
    m = re.match(r"^([^:：=＝]+)[:：=＝]?(.*)$", body)
    if not m:
        return None
    name = m.group(1).strip()
    arg = m.group(2).strip()
    key = name.lower().replace(" ", "")
    kind = CMD_ALIASES.get(key)
    if kind is None:
        return None
    if kind == "bgm" and arg in ("停止", "止める", "stop", "オフ", "OFF", "off"):
        kind, arg = "bgm_stop", ""
    if kind == "hide" and arg in ("", "全部", "すべて", "全て"):
        kind, arg = "hideall", ""
    return Command(kind, arg, line_no, raw)


def split_speaker(text: str, speakers: list[str]) -> tuple[str, str]:
    t = text.strip()
    for sp in sorted(speakers, key=len, reverse=True):
        if not sp:
            continue
        for sep in ("：", ":"):
            if t.startswith(sp + sep):
                return sp, t[len(sp) + 1:].strip()
        if t.startswith(sp + "「"):
            body = t[len(sp) + 1:]
            if body.endswith("」"):
                body = body[:-1]
            return sp, body.strip()
    return "", t


def parse_script(script: str, speakers: list[str] | None = None) -> ParsedScript:
    speakers = speakers or []
    scenes: list[Scene] = []
    pending: list[Command] = []
    pending_start: int | None = None
    errors: list[str] = []

    for no, line in enumerate(script.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("＃"):
            continue
        cmds: list[Command] = []
        for m in CMD_RE.finditer(line):
            c = parse_command(m.group(1), no, m.group(0))
            if c is None:
                errors.append(f"{no + 1}行目: 不明な命令 {m.group(0)}")
            else:
                cmds.append(c)
        text = CMD_RE.sub("", line).strip()
        if pending_start is None:
            pending_start = no
        pending.extend(cmds)
        has_dur = any(c.kind == "dur" for c in cmds)
        if text or has_dur:
            speaker, body = split_speaker(text, speakers) if text else ("", "")
            scenes.append(
                Scene(
                    index=len(scenes), line_no=no, first_line=pending_start,
                    text=body, speaker=speaker, commands=pending,
                )
            )
            pending = []
            pending_start = None
    return ParsedScript(scenes, pending, errors)


# ---------------- 台本の編集（配置タブから使う） ----------------

def format_command(kind: str, arg: str = "") -> str:
    label = CMD_LABELS[kind]
    return f"[{label}:{arg}]" if arg else f"[{label}]"


def insert_command(script: str, scene: Scene | None, cmd_text: str) -> str:
    """フレームの直前に命令行を追加する。scene が None なら末尾に追加。"""
    lines = script.splitlines()
    if scene is None:
        lines.append(cmd_text)
    else:
        lines.insert(scene.line_no, cmd_text)
    return "\n".join(lines) + ("\n" if script.endswith("\n") or not script else "")


def remove_command(script: str, cmd: Command) -> str:
    """命令を台本から取り除く。その行が空になれば行ごと消す。"""
    lines = script.splitlines()
    if not (0 <= cmd.line_no < len(lines)):
        return script
    line = lines[cmd.line_no]
    idx = line.find(cmd.raw)
    if idx < 0:
        return script
    new = (line[:idx] + line[idx + len(cmd.raw):]).rstrip()
    if new.strip():
        lines[cmd.line_no] = new.strip() if not line[:idx].strip() else new
    else:
        del lines[cmd.line_no]
    return "\n".join(lines) + ("\n" if script.endswith("\n") else "")


def visible_at(parsed: ParsedScript, scene_index: int) -> list[str]:
    """フレーム開始時点（命令実行後）に表示されている素材名（表示順）。"""
    visible: list[str] = []
    for sc in parsed.scenes[: scene_index + 1]:
        for c in sc.commands:
            if c.kind == "show" and c.arg and c.arg not in visible:
                visible.append(c.arg)
            elif c.kind == "hide" and c.arg in visible:
                visible.remove(c.arg)
            elif c.kind == "hideall":
                visible.clear()
    return visible


def rename_in_script(script: str, old: str, new: str) -> str:
    def repl(m: re.Match) -> str:
        c = parse_command(m.group(1), 0, m.group(0))
        if c and c.kind in ("show", "hide") and c.arg == old:
            return format_command(c.kind, new)
        return m.group(0)

    script = CMD_RE.sub(repl, script)
    out = []
    for line in script.splitlines():
        for sep in ("：", ":", "「"):
            if line.startswith(old + sep):
                line = new + line[len(old):]
                break
        out.append(line)
    return "\n".join(out) + ("\n" if script.endswith("\n") else "")


def remove_item_commands(script: str, name: str) -> str:
    def repl(m: re.Match) -> str:
        c = parse_command(m.group(1), 0, m.group(0))
        if c and c.kind in ("show", "hide") and c.arg == name:
            return ""
        return m.group(0)

    lines = []
    for line in script.splitlines():
        had_cmd = bool(CMD_RE.search(line))
        new = CMD_RE.sub(repl, line)
        if had_cmd and not new.strip():
            continue
        lines.append(new.rstrip() if new != line else line)
    return "\n".join(lines) + ("\n" if script.endswith("\n") else "")
