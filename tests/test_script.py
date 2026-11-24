import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avm.model import Item, Project  # noqa: E402
from avm.script import (format_command, insert_command, parse_script, remove_command,  # noqa: E402
                        rename_in_script, visible_at)
from avm.timeline import build_timeline, parse_project  # noqa: E402

SCRIPT = """[画像:ずんだもん][BGM:bgm.mp3]
ずんだもん：こんにちは
# コメント
[画像:ねこ] [SE:pon.wav]
ねこの話
[消去:ねこ]
[秒数:2]
四国めたん「よろしく」
[BGM:停止]
"""


def test_parse_scenes():
    p = parse_script(SCRIPT, ["ずんだもん", "四国めたん"])
    assert [s.text for s in p.scenes] == ["こんにちは", "ねこの話", "", "よろしく"]
    assert p.scenes[0].speaker == "ずんだもん"
    assert p.scenes[3].speaker == "四国めたん"
    assert p.scenes[2].dur_override == 2.0
    assert [c.kind for c in p.scenes[0].commands] == ["show", "bgm"]
    assert p.trailing and p.trailing[0].kind == "bgm_stop"


def test_visibility_stays_until_removed():
    p = parse_script(SCRIPT, ["ずんだもん"])
    assert visible_at(p, 0) == ["ずんだもん"]
    assert visible_at(p, 1) == ["ずんだもん", "ねこ"]
    assert visible_at(p, 2) == ["ずんだもん"]
    assert visible_at(p, 3) == ["ずんだもん"]


def test_insert_and_remove_command():
    p = parse_script(SCRIPT, ["ずんだもん"])
    s2 = insert_command(SCRIPT, p.scenes[3], format_command("hide", "ずんだもん"))
    p2 = parse_script(s2, ["ずんだもん"])
    assert visible_at(p2, 3) == []
    cmd = [c for c in p2.scenes[3].commands if c.kind == "hide"][0]
    s3 = remove_command(s2, cmd)
    assert s3 == SCRIPT


def test_remove_inline_command_keeps_other():
    p = parse_script(SCRIPT, [])
    se = [c for c in p.scenes[1].commands if c.kind == "se"][0]
    s2 = remove_command(SCRIPT, se)
    assert "[画像:ねこ]" in s2 and "[SE:pon.wav]" not in s2


def test_rename():
    s = rename_in_script(SCRIPT, "ずんだもん", "ずんだ")
    assert "[画像:ずんだ]" in s and "ずんだ：こんにちは" in s


def test_timeline_duration_and_intervals(tmp_path):
    pr = Project.create(str(tmp_path / "p"))
    pr.items = [Item("ずんだもん", "character"), Item("ねこ", "image")]
    pr.script = SCRIPT
    pr.duration = 0
    tl = build_timeline(pr, parse_project(pr), {})
    names = {v.item.name: (v.start, v.end) for v in tl.visibles}
    assert names["ずんだもん"][0] == 0 and abs(names["ずんだもん"][1] - tl.total) < 1e-6
    assert names["ねこ"][1] < tl.total
    pr.duration = 30
    tl = build_timeline(pr, parse_project(pr), {})
    assert tl.total == 30 and tl.scenes[-1].end == 30
