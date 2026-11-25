"""台本エディタ。右クリックで切り取り・コピー・貼り付け、素材の表示・消去の挿入。"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat,
                           QTextCursor)
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QInputDialog, QLabel,
                               QMenu, QPlainTextEdit, QSpinBox, QWidget)

from ..script import CMD_RE, MOTION_IN, MOTION_OUT, format_command


def ask_change(parent, kind: str, name: str) -> str | None:
    """大きさ／透明度の変更命令を作るダイアログ。"""
    d = QDialog(parent)
    d.setWindowTitle("大きさを変える" if kind == "scale" else "透明度を変える")
    f = QFormLayout(d)
    val = QSpinBox()
    if kind == "scale":
        val.setRange(1, 1000)
        val.setValue(150)
        f.addRow(QLabel(f"「{name}」の大きさを、元の大きさの何％にしますか？"))
        f.addRow("大きさ", val)
    else:
        val.setRange(0, 100)
        val.setValue(50)
        f.addRow(QLabel(f"「{name}」の透明度（0% = そのまま、100% = 見えない）"))
        f.addRow("透明度", val)
    val.setSuffix(" %")
    dur = QDoubleSpinBox()
    dur.setRange(0, 60)
    dur.setSingleStep(0.1)
    dur.setValue(1.0)
    dur.setSuffix(" 秒かけて")
    dur.setSpecialValueText("すぐに")
    f.addRow("変化の時間", dur)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    f.addRow(bb)
    if d.exec() != QDialog.Accepted:
        return None
    return format_command(kind, f"{name},{val.value()}%,{dur.value():g}秒")


class Highlighter(QSyntaxHighlighter):
    def __init__(self, doc, speakers: Callable[[], list[str]]):
        super().__init__(doc)
        self.speakers = speakers
        self.cmd = QTextCharFormat()
        self.cmd.setForeground(QColor("#4fc3f7"))
        self.cmd.setFontWeight(QFont.Bold)
        self.spk = QTextCharFormat()
        self.spk.setForeground(QColor("#ffb74d"))
        self.spk.setFontWeight(QFont.Bold)
        self.comment = QTextCharFormat()
        self.comment.setForeground(QColor("#888888"))

    def highlightBlock(self, text: str) -> None:
        if text.lstrip().startswith(("#", "＃")):
            self.setFormat(0, len(text), self.comment)
            return
        for sp in self.speakers():
            for sep in ("：", ":", "「"):
                if text.startswith(sp + sep):
                    self.setFormat(0, len(sp), self.spk)
        for m in CMD_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.cmd)


class LineNumberArea(QWidget):
    def __init__(self, editor: "ScriptEdit"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.number_width(), 0)

    def paintEvent(self, e):
        self.editor.paint_numbers(e)


class ScriptEdit(QPlainTextEdit):
    """台本エディタ。

    provider は右クリックメニュー用に (素材名一覧, BGM一覧, SE一覧, ボイス一覧) を返す関数。
    """

    frame_line_changed = Signal(int)  # カーソル行

    def __init__(self, parent=None):
        super().__init__(parent)
        f = QFont()
        f.setFamilies(["Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "Sans Serif"])
        f.setPointSize(12)
        self.setFont(f)
        self.setTabChangesFocus(False)
        self.provider: Callable[[], tuple[list[str], list[str], list[str], list[str]]] = lambda: ([], [], [], [])
        self.speakers: Callable[[], list[str]] = lambda: []
        self.frame_of_line: Callable[[int], int | None] = lambda n: None
        self.highlighter = Highlighter(self.document(), lambda: self.speakers())
        self.numbers = LineNumberArea(self)
        self.blockCountChanged.connect(lambda _: self._update_margin())
        self.updateRequest.connect(self._update_numbers)
        self.cursorPositionChanged.connect(lambda: self.frame_line_changed.emit(self.textCursor().blockNumber()))
        self._update_margin()
        self.setPlaceholderText(
            "ここに台本を書きます（1行 = 1フレーム）\n\n"
            "例）\n"
            "[画像:タイトル][BGM:bgm.mp3]\n"
            "ずんだもん：こんにちは、ずんだもんなのだ！\n"
            "[画像:ねこ][SE:ぽん.wav]\n"
            "今日はねこの話をするのだ。\n"
            "[消去:ねこ]\n"
            "[秒数:2]\n\n"
            "右クリックで切り取り・コピー・貼り付け、素材の表示・消去を入れられます。"
        )

    # ---- 行番号（フレーム番号） ----
    def number_width(self) -> int:
        return self.fontMetrics().horizontalAdvance("000 | F000") + 10

    def _update_margin(self):
        self.setViewportMargins(self.number_width(), 0, 0, 0)

    def _update_numbers(self, rect, dy):
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.numbers.setGeometry(QRect(cr.left(), cr.top(), self.number_width(), cr.height()))

    def paint_numbers(self, e):
        p = QPainter(self.numbers)
        p.fillRect(e.rect(), QColor("#2b2b2b"))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        cur = self.textCursor().blockNumber()
        while block.isValid() and top <= e.rect().bottom():
            bottom = top + round(self.blockBoundingRect(block).height())
            n = block.blockNumber()
            fr = self.frame_of_line(n)
            label = f"{n + 1:>3}" + (f" | F{fr + 1}" if fr is not None else "")
            p.setPen(QColor("#ffffff") if n == cur else QColor("#8a8a8a"))
            p.drawText(0, top, self.numbers.width() - 6, self.fontMetrics().height(), Qt.AlignRight, label)
            block = block.next()
            top = bottom
        p.end()

    # ---- 台本の差し替え（元に戻せるように） ----
    def replace_all(self, text: str) -> None:
        if text == self.toPlainText():
            return
        pos = self.textCursor().position()
        c = QTextCursor(self.document())
        c.beginEditBlock()
        c.select(QTextCursor.Document)
        c.insertText(text)
        c.endEditBlock()
        c = self.textCursor()
        c.setPosition(min(pos, len(text)))
        self.setTextCursor(c)

    def insert_command_line(self, cmd: str) -> None:
        """カーソル行の上に命令行を入れる（その行のフレームの頭で実行）。"""
        c = self.textCursor()
        c.movePosition(QTextCursor.StartOfBlock)
        c.insertText(cmd + "\n")
        self.setTextCursor(c)

    # ---- 右クリックメニュー ----
    def contextMenuEvent(self, e):
        m = QMenu(self)
        has_sel = self.textCursor().hasSelection()

        def act(text, fn, enabled=True, shortcut=None):
            a = QAction(text, m)
            a.triggered.connect(fn)
            a.setEnabled(enabled)
            if shortcut:
                a.setShortcut(shortcut)
            m.addAction(a)
            return a

        act("元に戻す", self.undo, self.document().isUndoAvailable(), "Ctrl+Z")
        act("やり直し", self.redo, self.document().isRedoAvailable(), "Ctrl+Y")
        m.addSeparator()
        act("切り取り", self.cut, has_sel, "Ctrl+X")
        act("コピー", self.copy, has_sel, "Ctrl+C")
        act("貼り付け", self.paste, self.canPaste(), "Ctrl+V")
        act("削除", lambda: self.textCursor().removeSelectedText(), has_sel, "Del")
        m.addSeparator()
        act("すべて選択", self.selectAll, True, "Ctrl+A")
        m.addSeparator()

        items, bgms, ses, voices = self.provider()
        sub = m.addMenu("この行で画像・動画を表示")
        for n in items:
            s2 = sub.addMenu(n)
            for key, label in MOTION_IN.items():
                arg = n if key == "none" else f"{n},{label}"
                s2.addAction("そのまま（素材の設定どおり）" if key == "none" else label + "入れる",
                             lambda a=arg: self.insert_command_line(format_command("show", a)))
        sub.setEnabled(bool(items))
        sub = m.addMenu("この行で画像・動画を消去")
        for n in items:
            s2 = sub.addMenu(n)
            for key, label in MOTION_OUT.items():
                arg = n if key == "none" else f"{n},{label}"
                s2.addAction("そのまま（素材の設定どおり）" if key == "none" else label + "消す",
                             lambda a=arg: self.insert_command_line(format_command("hide", a)))
        sub.setEnabled(bool(items))
        for kind, title in (("scale", "この行で大きさを変える"), ("alpha", "この行で透明度を変える")):
            sub = m.addMenu(title)
            for n in items:
                sub.addAction(n, lambda n=n, k=kind: self._ask_change(k, n))
            sub.setEnabled(bool(items))
        act("この行ですべて消去", lambda: self.insert_command_line(format_command("hideall")))
        m.addSeparator()
        sub = m.addMenu("この行でBGM開始")
        for n in bgms:
            sub.addAction(n, lambda n=n: self.insert_command_line(format_command("bgm", n)))
        sub.setEnabled(bool(bgms))
        act("この行でBGM停止", lambda: self.insert_command_line(format_command("bgm_stop")))
        sub = m.addMenu("この行でSEを鳴らす")
        for n in ses:
            sub.addAction(n, lambda n=n: self.insert_command_line(format_command("se", n)))
        sub.setEnabled(bool(ses))
        sub = m.addMenu("この行の音声ファイルを指定")
        for n in voices:
            sub.addAction(n, lambda n=n: self._append_to_line(format_command("voice", n)))
        sub.setEnabled(bool(voices))
        act("この行の秒数を指定…", self._ask_duration)
        act("セリフなしの待ち時間を入れる…", self._ask_wait)
        m.exec(e.globalPos())

    def _ask_change(self, kind: str, name: str) -> None:
        cmd = ask_change(self, kind, name)
        if cmd:
            self.insert_command_line(cmd)

    def _append_to_line(self, cmd: str) -> None:
        c = self.textCursor()
        c.movePosition(QTextCursor.EndOfBlock)
        c.insertText(" " + cmd)

    def _ask_duration(self):
        v, ok = QInputDialog.getDouble(self, "秒数を指定", "この行を表示する秒数:", 3.0, 0.1, 3600, 1)
        if ok:
            self._append_to_line(format_command("dur", f"{v:g}"))

    def _ask_wait(self):
        v, ok = QInputDialog.getDouble(self, "待ち時間", "セリフなしで待つ秒数:", 2.0, 0.1, 3600, 1)
        if ok:
            self.insert_command_line(format_command("dur", f"{v:g}"))
