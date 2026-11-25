"""メインウインドウ。"""
from __future__ import annotations

import glob
import os
import re
import shutil
import time

from PySide6.QtCore import QFileSystemWatcher, QMimeData, QPointF, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QProgressDialog, QPushButton, QRadioButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, APP_VERSION, media
from ..model import (ASPECTS, AUDIO_EXTS, IMAGE_EXTS, MOTIONS, PROJECT_FILE, VIDEO_EXTS, Item, Project,
                     list_files)
from ..script import (Command, ParsedScript, Scene, format_command, insert_command, remove_command,
                      remove_item_commands, rename_in_script, visible_at)
from ..timeline import parse_project
from ..voicevox import Voicevox, VoicevoxError
from .canvas import ASSET_MIME_PREFIX, CanvasView, _thumb_cache
from .preview import PreviewWindow, RenderWorker, open_folder
from .script_editor import ScriptEdit, ask_change

AUTOSAVE_FILE = "project.autosave.avmproj"
KIND_NAMES = {"image": "画像", "video": "動画", "character": "立ち絵"}


def default_root() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(docs):
        docs = os.path.expanduser("~")
    return os.path.join(docs, "自動動画メーカー")


# ---------------------------------------------------------------- 素材一覧
class AssetList(QListWidget):
    """素材フォルダの中身。キャンバスへドラッグでき、エクスプローラーからのドロップで追加できる。"""

    def __init__(self, exts: set[str], thumbs: bool, parent=None):
        super().__init__(parent)
        self.exts = exts
        self.folder = ""
        self.thumbs = thumbs
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        if thumbs:
            self.setIconSize(QSize(56, 56))

    def reload(self, folder: str) -> None:
        self.folder = folder
        cur = self.current_name()
        self.clear()
        for f in list_files(folder, self.exts):
            li = QListWidgetItem(f)
            li.setData(Qt.UserRole, os.path.join(folder, f))
            if self.thumbs:
                path = os.path.join(folder, f)
                if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    img = QImage(path)
                    if not img.isNull():
                        li.setIcon(QIcon(QPixmap.fromImage(img.scaled(56, 56, Qt.KeepAspectRatio,
                                                                      Qt.SmoothTransformation))))
                else:
                    data = media.video_first_frame(path, 112)
                    if data:
                        pm = QPixmap()
                        pm.loadFromData(data)
                        li.setIcon(QIcon(pm))
            self.addItem(li)
            if f == cur:
                self.setCurrentItem(li)

    def current_name(self) -> str:
        it = self.currentItem()
        return it.text() if it else ""

    def current_path(self) -> str:
        it = self.currentItem()
        return it.data(Qt.UserRole) if it else ""

    def mimeData(self, items):
        md = QMimeData()
        if items:
            md.setText(ASSET_MIME_PREFIX + items[0].data(Qt.UserRole))
        return md

    def mimeTypes(self):
        return ["text/plain", "text/uri-list"]

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls() and self.folder:
            for u in e.mimeData().urls():
                p = u.toLocalFile()
                if p and os.path.splitext(p)[1].lower() in self.exts:
                    copy_into(p, self.folder)
            e.acceptProposedAction()
            self.reload(self.folder)


def copy_into(path: str, folder: str) -> str:
    """ファイルをフォルダにコピー（すでにフォルダ内ならそのまま）。コピー先を返す。"""
    os.makedirs(folder, exist_ok=True)
    if os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(os.path.abspath(folder)):
        return path
    dst = os.path.join(folder, os.path.basename(path))
    base, ext = os.path.splitext(dst)
    i = 2
    while os.path.exists(dst):
        if os.path.getsize(dst) == os.path.getsize(path):
            return dst
        dst = f"{base}_{i}{ext}"
        i += 1
    shutil.copy2(path, dst)
    return dst


class ColorButton(QPushButton):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.color = "#000000"
        self.clicked.connect(self._pick)
        self.on_change = lambda c: None

    def set_color(self, c: str) -> None:
        self.color = c
        q = QColor(c)
        fg = "#000000" if q.lightness() > 128 else "#ffffff"
        self.setText(c.upper())
        self.setStyleSheet(f"background:{c}; color:{fg}; padding:4px;")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, self.title)
        if c.isValid():
            self.set_color(c.name())
            self.on_change(c.name())


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新しいプロジェクト")
        lay = QFormLayout(self)
        self.name = QLineEdit(time.strftime("動画_%Y%m%d_%H%M"))
        self.loc = QLineEdit(default_root())
        b = QPushButton("参照…")
        b.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.loc, 1)
        row.addWidget(b)
        self.aspect = QComboBox()
        self.aspect.addItems(list(ASPECTS))
        lay.addRow("プロジェクト名", self.name)
        lay.addRow("保存する場所", row)
        lay.addRow("画面比率", self.aspect)
        lay.addRow(QLabel("プロジェクト名のフォルダが作られ、その中に 画像・動画・BGM・SE・ボイス・立ち絵 フォルダができます。\n"
                          "書き出した動画もこのフォルダに保存されます。"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("作成")
        bb.button(QDialogButtonBox.Cancel).setText("キャンセル")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.resize(560, 0)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "保存する場所", self.loc.text())
        if d:
            self.loc.setText(d)

    def folder(self) -> str:
        name = re.sub(r'[\\/:*?"<>|]', "_", self.name.text().strip()) or "動画"
        return os.path.join(self.loc.text().strip(), name)


# ---------------------------------------------------------------- メイン
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 900)
        self.project: Project | None = None
        self.parsed = ParsedScript([], [], [])
        self.line_to_frame: dict[int, int] = {}
        self.current_frame = 0
        self._loading = False
        self._no_line_sync = False
        self._select_after = ""
        self.speakers: list[tuple[str, int]] = []
        self.worker: RenderWorker | None = None
        self.preview_win: PreviewWindow | None = None
        self.qs = QSettings("AutoVideoMaker", "AutoVideoMaker")

        self.reparse_timer = QTimer(self, singleShot=True, interval=350)
        self.reparse_timer.timeout.connect(self.reparse)
        self.autosave_timer = QTimer(self, interval=120_000)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self.lib_timer.start())
        self.lib_timer = QTimer(self, singleShot=True, interval=500)
        self.lib_timer.timeout.connect(self.reload_libraries)

        self._build_actions()
        self._build_settings_dock()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_script_tab(), "① 台本")
        self.tabs.addTab(self._build_place_tab(), "② 配置")
        self.tabs.addTab(self._build_char_tab(), "③ 立ち絵・音声")
        self.tabs.currentChanged.connect(lambda _: self.refresh_canvas())
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage("準備完了")

    # ============================================================ UI 構築
    def _build_actions(self):
        tb = self.addToolBar("メイン")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        mb = self.menuBar()
        fm = mb.addMenu("ファイル(&F)")

        def mk(text, fn, shortcut=None, menu=fm, toolbar=True):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            menu.addAction(a)
            if toolbar:
                tb.addAction(a)
            return a

        mk("新規作成", self.new_project, "Ctrl+N")
        mk("開く", self.open_project, "Ctrl+O")
        mk("保存（一時保存）", self.save, "Ctrl+S")
        mk("まとめて保存", self.save_all, "Ctrl+Shift+S")
        mk("ZIPにまとめる…", self.export_zip, toolbar=False)
        fm.addSeparator()
        mk("サンプルを開く", self.open_sample, toolbar=False)
        fm.addSeparator()
        mk("プロジェクトのフォルダを開く", lambda: self.project and open_folder(self.project.folder), toolbar=False)
        fm.addSeparator()
        mk("終了", self.close, toolbar=False)
        tb.addSeparator()
        vm = mb.addMenu("動画(&V)")
        mk("▶ プレビュー", lambda: self.render(preview=True), "F5", menu=vm)
        mk("▶ このフレームから", lambda: self.render(preview=True, from_frame=True), "Shift+F5", menu=vm)
        tb.addSeparator()
        a = mk("書き出し", lambda: self.render(preview=False), "Ctrl+E", menu=vm)
        tb.widgetForAction(a).setStyleSheet("font-weight:bold; color:#ffffff; background:#c62828; padding:4px 14px;")
        hm = mb.addMenu("ヘルプ(&H)")
        mk("台本の書き方", self.show_help, "F1", menu=hm, toolbar=False)
        mk("バージョン情報", lambda: QMessageBox.about(self, APP_NAME, f"{APP_NAME} {APP_VERSION}"), menu=hm,
           toolbar=False)

    def _build_settings_dock(self):
        dock = QDockWidget("動画の設定", self)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        w = QWidget()
        lay = QVBoxLayout(w)

        g = QGroupBox("画面")
        f = QFormLayout(g)
        self.aspect_cb = QComboBox()
        self.aspect_cb.addItems(list(ASPECTS))
        self.aspect_cb.currentTextChanged.connect(self.on_aspect)
        self.fps_cb = QComboBox()
        self.fps_cb.addItems(["24", "30", "60"])
        self.fps_cb.currentTextChanged.connect(lambda v: self.set_prop("fps", int(v)))
        self.dur_sp = QDoubleSpinBox()
        self.dur_sp.setRange(0, 36000)
        self.dur_sp.setDecimals(1)
        self.dur_sp.setSuffix(" 秒")
        self.dur_sp.setSpecialValueText("自動（台本の長さ）")
        self.dur_sp.valueChanged.connect(lambda v: self.set_prop("duration", float(v)))
        self.bg_btn = ColorButton("背景色")
        self.bg_btn.on_change = lambda c: self.set_prop("bg_color", c, True)
        f.addRow("画面比率", self.aspect_cb)
        f.addRow("フレームレート", self.fps_cb)
        f.addRow("動画の長さ", self.dur_sp)
        f.addRow("背景色", self.bg_btn)
        lay.addWidget(g)

        g = QGroupBox("字幕")
        f = QFormLayout(g)
        self.sub_cb = QCheckBox("字幕を表示する（ON）")
        self.sub_cb.toggled.connect(lambda v: self.set_prop("subtitles", v, True))
        self.sub_size = QSpinBox()
        self.sub_size.setRange(0, 300)
        self.sub_size.setSpecialValueText("自動")
        self.sub_size.setSuffix(" px")
        self.sub_size.valueChanged.connect(lambda v: self.set_prop("subtitle_size", v, True))
        self.sub_color = ColorButton("文字の色")
        self.sub_color.on_change = lambda c: self.set_prop("subtitle_color", c, True)
        self.sub_outline = ColorButton("縁取りの色")
        self.sub_outline.on_change = lambda c: self.set_prop("subtitle_outline", c, True)
        self.sub_box = QCheckBox("半透明の帯を敷く")
        self.sub_box.toggled.connect(lambda v: self.set_prop("subtitle_box", v, True))
        f.addRow(self.sub_cb)
        f.addRow("文字の大きさ", self.sub_size)
        f.addRow("文字の色", self.sub_color)
        f.addRow("縁取り", self.sub_outline)
        f.addRow(self.sub_box)
        lay.addWidget(g)

        g = QGroupBox("音声")
        f = QFormLayout(g)
        self.mode_vv = QRadioButton("VOICEVOX で台本を読み上げる")
        self.mode_files = QRadioButton("用意した音声ファイルを使う（ボイスフォルダ）")
        self.mode_none = QRadioButton("声なし（BGM・SE・字幕だけ）")
        bg = QButtonGroup(self)
        bg.addButton(self.mode_vv)
        bg.addButton(self.mode_files)
        bg.addButton(self.mode_none)
        self.mode_none.toggled.connect(lambda v: v and self.set_prop("voice_mode", "none"))
        self.mode_vv.toggled.connect(lambda v: v and self.set_prop("voice_mode", "voicevox"))
        self.mode_files.toggled.connect(lambda v: v and self.set_prop("voice_mode", "files"))
        f.addRow(self.mode_vv)
        f.addRow(self.mode_files)
        f.addRow(self.mode_none)
        self.vv_url = QLineEdit()
        self.vv_url.editingFinished.connect(lambda: self.set_prop("voicevox_url", self.vv_url.text().strip()))
        f.addRow("VOICEVOX の URL", self.vv_url)
        row = QHBoxLayout()
        self.spk_cb = QComboBox()
        self.spk_cb.currentIndexChanged.connect(self.on_default_speaker)
        b = QPushButton("話者を取得")
        b.setToolTip("起動中の VOICEVOX から話者の一覧を読み込みます")
        b.clicked.connect(lambda: self.load_speakers(show_error=True))
        row.addWidget(self.spk_cb, 1)
        row.addWidget(b)
        f.addRow("既定の話者", row)
        self.speed_sp = QDoubleSpinBox()
        self.speed_sp.setRange(0.5, 2.0)
        self.speed_sp.setSingleStep(0.05)
        self.speed_sp.valueChanged.connect(lambda v: self.set_prop("speed", float(v)))
        f.addRow("話速", self.speed_sp)
        self.gap_sp = QDoubleSpinBox()
        self.gap_sp.setRange(0, 5)
        self.gap_sp.setSingleStep(0.1)
        self.gap_sp.setSuffix(" 秒")
        self.gap_sp.valueChanged.connect(lambda v: self.set_prop("scene_gap", float(v)))
        f.addRow("セリフの間", self.gap_sp)
        self.vol = {}
        for key, label in (("voice_volume", "声の音量"), ("bgm_volume", "BGMの音量"), ("se_volume", "SEの音量")):
            sp = QSpinBox()
            sp.setRange(0, 200)
            sp.setSuffix(" %")
            sp.valueChanged.connect(lambda v, k=key: self.set_prop(k, v / 100))
            self.vol[key] = sp
            f.addRow(label, sp)
        lay.addWidget(g)
        lay.addStretch(1)

        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        sa.setMinimumWidth(330)
        dock.setWidget(sa)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_script_tab(self) -> QWidget:
        sp = QSplitter()
        self.editor = ScriptEdit()
        self.editor.provider = self.menu_provider
        self.editor.speakers = lambda: [c.name for c in self.project.characters()] if self.project else []
        self.editor.frame_of_line = lambda n: self.line_to_frame.get(n) if n in self.scene_lines else None
        self.scene_lines: set[int] = set()
        self.editor.textChanged.connect(self.on_script_changed)
        self.editor.frame_line_changed.connect(self.on_editor_line)
        sp.addWidget(self.editor)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("フレーム一覧（クリックで移動）"))
        self.frame_list = QListWidget()
        self.frame_list.itemClicked.connect(lambda it: self.goto_frame(self.frame_list.row(it), move_cursor=True))
        rl.addWidget(self.frame_list, 1)
        self.err_label = QLabel()
        self.err_label.setWordWrap(True)
        self.err_label.setStyleSheet("color:#ff8a80")
        rl.addWidget(self.err_label)
        hb = QPushButton("台本の書き方")
        hb.clicked.connect(self.show_help)
        rl.addWidget(hb)
        sp.addWidget(right)
        sp.setSizes([900, 350])
        return sp

    def _frame_nav(self) -> QHBoxLayout:
        row = QHBoxLayout()
        prev = QPushButton("◀")
        prev.setFixedWidth(36)
        prev.clicked.connect(lambda: self.goto_frame(self.current_frame - 1))
        nxt = QPushButton("▶")
        nxt.setFixedWidth(36)
        nxt.clicked.connect(lambda: self.goto_frame(self.current_frame + 1))
        self.frame_cb = QComboBox()
        self.frame_cb.currentIndexChanged.connect(lambda i: i >= 0 and self.goto_frame(i))
        row.addWidget(QLabel("フレーム:"))
        row.addWidget(prev)
        row.addWidget(self.frame_cb, 1)
        row.addWidget(nxt)
        return row

    def _build_place_tab(self) -> QWidget:
        sp = QSplitter()
        # 左：素材ライブラリ
        lib = QWidget()
        ll = QVBoxLayout(lib)
        ll.addWidget(QLabel("素材（ドラッグでキャンバスへ）"))
        self.lib_tabs = QTabWidget()
        self.libs: dict[str, AssetList] = {}
        for key, label, exts, th in (("image", "画像", IMAGE_EXTS, True), ("video", "動画", VIDEO_EXTS, True),
                                     ("bgm", "BGM", AUDIO_EXTS, False), ("se", "SE", AUDIO_EXTS, False),
                                     ("voice", "ボイス", AUDIO_EXTS, False)):
            lw = AssetList(exts, th)
            if key in ("image", "video"):
                lw.itemDoubleClicked.connect(lambda it: self.place_asset(it.data(Qt.UserRole)))
            self.libs[key] = lw
            self.lib_tabs.addTab(lw, label)
        ll.addWidget(self.lib_tabs, 1)
        row = QHBoxLayout()
        for text, fn in (("追加…", self.add_files), ("フォルダを開く", self.open_lib_folder),
                         ("再読込", self.reload_libraries)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        ll.addLayout(row)
        b = QPushButton("選んだ素材をこのフレームに配置")
        b.clicked.connect(self.place_selected_asset)
        ll.addWidget(b)
        sp.addWidget(lib)

        # 中央：キャンバス
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.addLayout(self._frame_nav())
        self.canvas = CanvasView()
        self.canvas.asset_dropped.connect(lambda p, pos: self.place_asset(p, pos))
        self.canvas.item_changed.connect(self.on_item_moved)
        self.canvas.item_lock_requested.connect(self.lock_item)
        self.canvas.item_menu_requested.connect(self.item_menu)
        self.canvas.selection_changed_name.connect(self.on_canvas_select)
        ml.addWidget(self.canvas, 1)
        bar = QHBoxLayout()
        self.sel_label = QLabel("素材を選んでください")
        self.ok_btn = QPushButton("OK（固定）")
        self.ok_btn.clicked.connect(lambda: self.lock_item(self.canvas.selected_name()))
        self.unlock_btn = QPushButton("解除")
        self.unlock_btn.clicked.connect(lambda: self.unlock_item(self.canvas.selected_name()))
        self.geo = {}
        bar.addWidget(self.sel_label, 1)
        for k in ("x", "y", "w", "h"):
            s = QSpinBox()
            s.setRange(-10000, 10000)
            s.setPrefix({"x": "X ", "y": "Y ", "w": "幅 ", "h": "高さ "}[k])
            s.editingFinished.connect(self.on_geo_edit)
            self.geo[k] = s
            bar.addWidget(s)
        bar.addWidget(self.ok_btn)
        bar.addWidget(self.unlock_btn)
        ml.addLayout(bar)
        bar2 = QHBoxLayout()
        self.fx_alpha = QSpinBox()
        self.fx_alpha.setRange(0, 100)
        self.fx_alpha.setSuffix(" %")
        self.fx_alpha.setToolTip("0% = そのまま、100% = 見えない")
        self.fx_enter = QComboBox()
        self.fx_exit = QComboBox()
        for key, label in MOTIONS.items():
            self.fx_enter.addItem(label, key)
            self.fx_exit.addItem({"left": "左へ", "right": "右へ", "top": "上へ", "bottom": "下へ"}.get(key, label), key)
        self.fx_enter_dur = QDoubleSpinBox()
        self.fx_exit_dur = QDoubleSpinBox()
        for dsp in (self.fx_enter_dur, self.fx_exit_dur):
            dsp.setRange(0.1, 10)
            dsp.setSingleStep(0.1)
            dsp.setSuffix(" 秒")
        bar2.addWidget(QLabel("透明度"))
        bar2.addWidget(self.fx_alpha)
        bar2.addSpacing(12)
        bar2.addWidget(QLabel("登場"))
        bar2.addWidget(self.fx_enter)
        bar2.addWidget(self.fx_enter_dur)
        bar2.addSpacing(12)
        bar2.addWidget(QLabel("退場"))
        bar2.addWidget(self.fx_exit)
        bar2.addWidget(self.fx_exit_dur)
        bar2.addStretch(1)
        self.fx_alpha.valueChanged.connect(self.on_fx_edit)
        self.fx_enter.currentIndexChanged.connect(self.on_fx_edit)
        self.fx_exit.currentIndexChanged.connect(self.on_fx_edit)
        self.fx_enter_dur.valueChanged.connect(self.on_fx_edit)
        self.fx_exit_dur.valueChanged.connect(self.on_fx_edit)
        self.fx_widgets = [self.fx_alpha, self.fx_enter, self.fx_exit, self.fx_enter_dur, self.fx_exit_dur]
        ml.addLayout(bar2)
        ml.addWidget(QLabel("ヒント：配置したらOKで固定。固定した素材をクリックすると「解除」で動かせます。"
                            "右クリックで前面・背面、消去などができます。"))
        sp.addWidget(mid)

        # 右：フレームの素材・命令
        right = QWidget()
        rl = QVBoxLayout(right)
        self.frame_title = QLabel("フレーム")
        self.frame_title.setStyleSheet("font-weight:bold")
        rl.addWidget(self.frame_title)
        self.item_tree = QTreeWidget()
        self.item_tree.setHeaderLabels(["素材", "種類", "このフレーム", "固定"])
        self.item_tree.setRootIsDecorated(False)
        self.item_tree.itemClicked.connect(lambda it: self.canvas.select(it.text(0)))
        rl.addWidget(self.item_tree, 2)
        row = QHBoxLayout()
        b = QPushButton("このフレームで表示")
        b.clicked.connect(lambda: self.show_at_frame(self.tree_name()))
        row.addWidget(b)
        b = QPushButton("このフレームで消去")
        b.clicked.connect(lambda: self.hide_at_frame(self.tree_name()))
        row.addWidget(b)
        rl.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("このフレームで大きさを変える…")
        b.clicked.connect(lambda: self.change_at_frame("scale", self.tree_name()))
        row.addWidget(b)
        b = QPushButton("このフレームで透明度を変える…")
        b.clicked.connect(lambda: self.change_at_frame("alpha", self.tree_name()))
        row.addWidget(b)
        rl.addLayout(row)
        b = QPushButton("素材を削除（プロジェクトから）")
        b.clicked.connect(lambda: self.delete_item(self.tree_name()))
        rl.addWidget(b)

        g = QGroupBox("BGM・SE")
        gl = QFormLayout(g)
        self.bgm_cb = QComboBox()
        self.se_cb = QComboBox()
        b1 = QPushButton("このフレームでBGM開始")
        b1.clicked.connect(lambda: self.bgm_cb.currentText() and self.add_cmd(format_command("bgm", self.bgm_cb.currentText())))
        b2 = QPushButton("このフレームでBGM停止")
        b2.clicked.connect(lambda: self.add_cmd(format_command("bgm_stop")))
        b3 = QPushButton("このフレームでSEを鳴らす")
        b3.clicked.connect(lambda: self.se_cb.currentText() and self.add_cmd(format_command("se", self.se_cb.currentText())))
        gl.addRow("BGM", self.bgm_cb)
        gl.addRow(b1)
        gl.addRow(b2)
        gl.addRow("SE", self.se_cb)
        gl.addRow(b3)
        rl.addWidget(g)

        rl.addWidget(QLabel("このフレームの命令"))
        self.cmd_list = QListWidget()
        rl.addWidget(self.cmd_list, 1)
        b = QPushButton("選んだ命令を取り消す")
        b.clicked.connect(self.remove_selected_cmd)
        rl.addWidget(b)
        sp.addWidget(right)
        sp.setSizes([260, 900, 340])
        return sp

    def _build_char_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(QLabel("立ち絵（キャラクター）"))
        self.char_list = QListWidget()
        self.char_list.currentRowChanged.connect(self.load_char_form)
        left.addWidget(self.char_list, 1)
        b = QPushButton("立ち絵を追加…")
        b.clicked.connect(self.add_character)
        left.addWidget(b)
        b = QPushButton("削除")
        b.clicked.connect(lambda: self.char_list.currentItem() and self.delete_item(self.char_list.currentItem().text()))
        left.addWidget(b)
        lay.addLayout(left, 1)

        form_w = QGroupBox("設定")
        f = QFormLayout(form_w)
        row = QHBoxLayout()
        self.ch_name = QLineEdit()
        rb = QPushButton("名前を変更")
        rb.clicked.connect(self.rename_character)
        row.addWidget(self.ch_name, 1)
        row.addWidget(rb)
        f.addRow("名前", row)
        self.ch_files = {}
        for key, label in (("file", "口を閉じた画像"), ("file_open", "口を開けた画像"), ("file_half", "半開きの画像（任意）")):
            r = QHBoxLayout()
            le = QLineEdit()
            le.setReadOnly(True)
            bb = QPushButton("選ぶ…")
            bb.clicked.connect(lambda _=False, k=key: self.pick_char_file(k))
            r.addWidget(le, 1)
            r.addWidget(bb)
            self.ch_files[key] = le
            f.addRow(label, r)
        self.ch_spk = QComboBox()
        self.ch_spk.currentIndexChanged.connect(self.save_char_form)
        f.addRow("VOICEVOX の話者", self.ch_spk)
        self.ch_speed = QDoubleSpinBox()
        self.ch_speed.setRange(0, 2)
        self.ch_speed.setSingleStep(0.05)
        self.ch_speed.setSpecialValueText("既定")
        self.ch_speed.valueChanged.connect(self.save_char_form)
        f.addRow("話速", self.ch_speed)
        b = QPushButton("②配置タブで位置・大きさを調整")
        b.clicked.connect(self.goto_char_on_canvas)
        f.addRow(b)
        help_ = QLabel(
            "・台本で「名前：セリフ」または「名前「セリフ」」と書くと、そのキャラが話します。\n"
            "・立ち絵が1人だけなら、名前のないセリフもそのキャラが話します。\n"
            "・音声がある間は、口を開けた画像と閉じた画像が自動で切り替わります（リップシンク）。\n"
            "・VOICEVOX モードでは、キャラごとに話者を変えられます。\n"
            "・用意した音声を使う場合は、ボイスフォルダに 001.wav, 002.wav… の順で入れると、\n"
            "  セリフの順に自動で割り当てます。行ごとに [音声:ファイル名] で指定もできます。"
        )
        help_.setWordWrap(True)
        f.addRow(help_)
        lay.addWidget(form_w, 2)
        self._char_loading = False
        return w

    # ============================================================ プロジェクト
    def startup(self):
        last = self.qs.value("last_project", "")
        if last and os.path.exists(last):
            try:
                self.load_project_file(last)
                return
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, APP_NAME, f"前回のプロジェクトを開けませんでした。\n{e}")
        if os.path.isdir(media.resource_path("サンプル")):
            r = QMessageBox.question(self, APP_NAME, "ようこそ！まずはサンプルを開いてみますか？\n"
                                                     "（いいえ = 新しいプロジェクトを作る）")
            if r == QMessageBox.Yes and self.open_sample():
                return
        if not self.new_project():
            p = Project.create(os.path.join(default_root(), "プロジェクト1"))
            if os.path.exists(os.path.join(p.folder, PROJECT_FILE)):
                p = Project.load(os.path.join(p.folder, PROJECT_FILE))
            self.set_project(p)

    def maybe_save(self) -> bool:
        if self.project and self.project.dirty:
            r = QMessageBox.question(self, APP_NAME, "変更を保存しますか？",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                self.save()
        return True

    def new_project(self) -> bool:
        if not self.maybe_save():
            return False
        d = NewProjectDialog(self)
        if d.exec() != QDialog.Accepted:
            return False
        folder = d.folder()
        if os.path.exists(os.path.join(folder, PROJECT_FILE)):
            QMessageBox.warning(self, APP_NAME, "そのフォルダにはすでにプロジェクトがあります。別の名前にしてください。")
            return self.new_project()
        p = Project.create(folder)
        p.set_aspect(d.aspect.currentText())
        p.save()
        self.set_project(p)
        return True

    def open_sample(self) -> bool:
        """同梱のサンプルを「ドキュメント/自動動画メーカー」にコピーして開く。"""
        if not self.maybe_save():
            return False
        src = media.resource_path("サンプル")
        if not os.path.isdir(src):
            QMessageBox.warning(self, APP_NAME, "サンプルが見つかりません。")
            return False
        dst = os.path.join(default_root(), "サンプル")
        i = 2
        while os.path.exists(dst):
            dst = os.path.join(default_root(), f"サンプル{i}")
            i += 1
        shutil.copytree(src, dst)
        p = Project.load(os.path.join(dst, PROJECT_FILE))
        p.name = os.path.basename(dst)
        p.save()
        self.set_project(p)
        self.statusBar().showMessage(f"サンプルをコピーして開きました: {dst}", 8000)
        return True

    def open_project(self):
        if not self.maybe_save():
            return
        start = self.project.folder if self.project else default_root()
        path, _ = QFileDialog.getOpenFileName(self, "プロジェクトを開く", start, "プロジェクト (*.avmproj)")
        if path:
            try:
                self.load_project_file(path)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, APP_NAME, f"開けませんでした。\n{e}")

    def load_project_file(self, path: str):
        auto = os.path.join(os.path.dirname(path), AUTOSAVE_FILE)
        if os.path.exists(auto) and os.path.getmtime(auto) > os.path.getmtime(path):
            r = QMessageBox.question(self, APP_NAME, "保存されていない一時保存データがあります。復元しますか？")
            if r == QMessageBox.Yes:
                p = Project.load(auto)
                p.dirty = True
                self.set_project(p)
                return
        self.set_project(Project.load(path))

    def set_project(self, p: Project):
        self.project = p
        p.ensure_folders()
        self.qs.setValue("last_project", os.path.join(p.folder, PROJECT_FILE))
        self._loading = True
        try:
            self.aspect_cb.setCurrentText(p.aspect)
            self.fps_cb.setCurrentText(str(p.fps))
            self.dur_sp.setValue(p.duration)
            self.bg_btn.set_color(p.bg_color)
            self.sub_cb.setChecked(p.subtitles)
            self.sub_size.setValue(p.subtitle_size)
            self.sub_color.set_color(p.subtitle_color)
            self.sub_outline.set_color(p.subtitle_outline)
            self.sub_box.setChecked(p.subtitle_box)
            {"voicevox": self.mode_vv, "files": self.mode_files}.get(p.voice_mode, self.mode_none).setChecked(True)
            self.vv_url.setText(p.voicevox_url)
            self.speed_sp.setValue(p.speed)
            self.gap_sp.setValue(p.scene_gap)
            for k, sp in self.vol.items():
                sp.setValue(int(round(getattr(p, k) * 100)))
            self.editor.setPlainText(p.script)
            self.editor.document().clearUndoRedoStacks()
        finally:
            self._loading = False
        dirs = self.watcher.directories()
        if dirs:
            self.watcher.removePaths(dirs)
        self.watcher.addPaths([p.subfolder(k) for k in self.libs])
        self.load_speakers(show_error=False)
        self.reload_libraries()
        self.current_frame = 0
        self.reparse()
        self.refresh_chars()
        self.update_title()

    def update_title(self):
        if self.project:
            mark = "*" if self.project.dirty else ""
            self.setWindowTitle(f"{mark}{self.project.name} - {APP_NAME}")

    def mark_dirty(self):
        if self.project:
            self.project.dirty = True
            self.update_title()

    def save(self):
        if not self.project:
            return
        self.project.script = self.editor.toPlainText()
        self.project.save()
        auto = os.path.join(self.project.folder, AUTOSAVE_FILE)
        if os.path.exists(auto):
            os.remove(auto)
        self.update_title()
        self.statusBar().showMessage("保存しました", 4000)

    def autosave(self):
        if self.project and self.project.dirty:
            self.project.script = self.editor.toPlainText()
            dirty = self.project.dirty
            self.project.save(os.path.join(self.project.folder, AUTOSAVE_FILE))
            self.project.dirty = dirty
            self.statusBar().showMessage("一時保存しました（自動）", 3000)

    def save_all(self):
        if not self.project:
            return
        self.project.script = self.editor.toPlainText()
        copied = self.project.collect_assets()
        self.save()
        self.reload_libraries()
        msg = "プロジェクトと素材をすべてプロジェクトフォルダにまとめて保存しました。"
        if copied:
            msg += f"\n外部の素材 {len(copied)} 個をフォルダにコピーしました。"
        r = QMessageBox.question(self, "まとめて保存", msg + "\n\n持ち運び用に ZIP ファイルも作りますか？")
        if r == QMessageBox.Yes:
            self.export_zip()

    def export_zip(self):
        if not self.project:
            return
        self.save()
        default = os.path.join(os.path.dirname(self.project.folder), f"{self.project.name}.zip")
        path, _ = QFileDialog.getSaveFileName(self, "ZIPにまとめる", default, "ZIP (*.zip)")
        if path:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.project.export_zip(path)
            finally:
                QApplication.restoreOverrideCursor()
            self.statusBar().showMessage(f"ZIPを作成しました: {path}", 6000)

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, APP_NAME, "書き出し中です。完了またはキャンセルしてから閉じてください。")
            e.ignore()
            return
        if self.maybe_save():
            if self.project:
                auto = os.path.join(self.project.folder, AUTOSAVE_FILE)
                if not self.project.dirty and os.path.exists(auto):
                    os.remove(auto)
            e.accept()
        else:
            e.ignore()

    # ============================================================ 設定
    def set_prop(self, key: str, value, visual: bool = False):
        if self._loading or not self.project:
            return
        setattr(self.project, key, value)
        self.mark_dirty()
        if visual:
            self.refresh_canvas()

    def on_aspect(self, text: str):
        if self._loading or not self.project or text == self.project.aspect:
            return
        p = self.project
        ow, oh = p.width, p.height
        p.set_aspect(text)
        if p.items and (ow, oh) != (p.width, p.height):
            r = QMessageBox.question(self, "画面比率の変更", "配置した素材の位置と大きさを新しい画面に合わせて調整しますか？")
            if r == QMessageBox.Yes:
                s = min(p.width / ow, p.height / oh)
                dx, dy = (p.width - ow * s) / 2, (p.height - oh * s) / 2
                for it in p.items:
                    it.x, it.y = round(it.x * s + dx), round(it.y * s + dy)
                    it.w, it.h = round(it.w * s), round(it.h * s)
        self.mark_dirty()
        self.refresh_canvas()

    def load_speakers(self, show_error: bool):
        if not self.project:
            return
        try:
            self.speakers = Voicevox(self.project.voicevox_url, timeout=3).speakers()
            if show_error:
                QMessageBox.information(self, "VOICEVOX", f"{len(self.speakers)} 人分の話者を読み込みました。")
        except VoicevoxError as e:
            if show_error:
                QMessageBox.warning(self, "VOICEVOX", str(e))
        except Exception as e:  # noqa: BLE001
            if show_error:
                QMessageBox.warning(self, "VOICEVOX", f"話者を読み込めませんでした。\n{e}")
        self._fill_speaker_combo(self.spk_cb, self.project.default_speaker, with_default=False)
        self.load_char_form(self.char_list.currentRow())

    def _fill_speaker_combo(self, cb: QComboBox, current: int, with_default: bool):
        cb.blockSignals(True)
        cb.clear()
        if with_default:
            cb.addItem("（既定の話者）", -1)
        ids = set()
        for name, sid in self.speakers:
            cb.addItem(f"{name}  [ID {sid}]", sid)
            ids.add(sid)
        if not self.speakers:
            for sid in range(0, 100):
                cb.addItem(f"ID {sid}", sid)
                ids.add(sid)
        if current >= 0 and current not in ids:
            cb.addItem(f"ID {current}", current)
        i = cb.findData(current)
        cb.setCurrentIndex(max(0, i))
        cb.blockSignals(False)

    def on_default_speaker(self, i: int):
        if i >= 0:
            self.set_prop("default_speaker", int(self.spk_cb.itemData(i)))

    # ============================================================ 台本
    def on_script_changed(self):
        if self._loading or not self.project:
            return
        self.project.script = self.editor.toPlainText()
        self.mark_dirty()
        self.reparse_timer.start()

    def reparse(self):
        if not self.project:
            return
        self.project.script = self.editor.toPlainText()
        self.parsed = parse_project(self.project)
        self.line_to_frame = {}
        self.scene_lines = set()
        for sc in self.parsed.scenes:
            self.scene_lines.add(sc.line_no)
            for ln in range(sc.first_line, sc.line_no + 1):
                self.line_to_frame[ln] = sc.index
        self.editor.numbers.update()
        labels = [sc.label() for sc in self.parsed.scenes]
        self.frame_list.clear()
        self.frame_list.addItems(labels)
        self.frame_cb.blockSignals(True)
        self.frame_cb.clear()
        self.frame_cb.addItems(labels)
        self.frame_cb.blockSignals(False)
        errs = list(self.parsed.errors)
        names = {it.name for it in self.project.items}
        for sc in self.parsed.scenes:
            for c in sc.commands:
                if c.kind in ("show", "hide", "scale", "alpha") and c.name not in names:
                    errs.append(f"{c.line_no + 1}行目: 素材「{c.name}」がありません")
        if self.parsed.trailing:
            errs.append("最後のセリフより後ろの命令は使われません")
        self.err_label.setText("\n".join(errs[:8]))
        n = len(self.parsed.scenes)
        self.current_frame = max(0, min(self.current_frame, n - 1))
        self.statusBar().showMessage(f"フレーム数: {n}")
        self.goto_frame(self.current_frame, force=True)

    def on_editor_line(self, line: int):
        if self._no_line_sync:
            return
        fr = self.line_to_frame.get(line)
        if fr is None:
            # 次のフレームを探す
            later = [s.index for s in self.parsed.scenes if s.line_no >= line]
            fr = later[0] if later else (len(self.parsed.scenes) - 1 if self.parsed.scenes else None)
        if fr is not None and fr != self.current_frame:
            self.goto_frame(fr)

    def goto_frame(self, i: int, move_cursor: bool = False, force: bool = False):
        n = len(self.parsed.scenes)
        if n == 0:
            self.current_frame = 0
        else:
            i = max(0, min(i, n - 1))
            if i == self.current_frame and not force and not move_cursor:
                return
            self.current_frame = i
        self.frame_cb.blockSignals(True)
        self.frame_cb.setCurrentIndex(self.current_frame if n else -1)
        self.frame_cb.blockSignals(False)
        self.frame_list.blockSignals(True)
        self.frame_list.setCurrentRow(self.current_frame if n else -1)
        self.frame_list.blockSignals(False)
        if move_cursor and n:
            ln = self.parsed.scenes[self.current_frame].line_no
            block = self.editor.document().findBlockByNumber(ln)
            c = self.editor.textCursor()
            c.setPosition(block.position())
            self.editor.blockSignals(True)
            self.editor.setTextCursor(c)
            self.editor.blockSignals(False)
            self.editor.centerCursor()
            self.editor.setFocus()
        self.refresh_canvas()

    def scene(self) -> Scene | None:
        s = self.parsed.scenes
        return s[self.current_frame] if s and self.current_frame < len(s) else None

    def set_script(self, text: str):
        """配置タブなどからの台本の書き換え（元に戻す可能）。"""
        self._no_line_sync = True
        try:
            self.editor.replace_all(text)
        finally:
            self._no_line_sync = False
        self.reparse_timer.stop()
        self.reparse()

    def ensure_frame(self) -> Scene | None:
        sc = self.scene()
        if sc is None and self.project:
            QMessageBox.information(self, APP_NAME, "まだフレームがないので、3秒の空のフレームを1つ作ります。\n"
                                                    "台本タブでセリフを書くとフレームが増えます。")
            text = self.editor.toPlainText()
            self.set_script((text.rstrip("\n") + "\n" if text.strip() else "") + format_command("dur", "3") + "\n")
            sc = self.scene()
        return sc

    def add_cmd(self, cmd_text: str):
        if not self.project:
            return
        sc = self.ensure_frame()
        if sc is None:
            return
        self.set_script(insert_command(self.editor.toPlainText(), sc, cmd_text))

    def menu_provider(self):
        if not self.project:
            return [], [], [], []
        p = self.project
        return ([it.name for it in p.items], list_files(p.subfolder("bgm"), AUDIO_EXTS),
                list_files(p.subfolder("se"), AUDIO_EXTS), list_files(p.subfolder("voice"), AUDIO_EXTS))

    # ============================================================ 配置
    def refresh_canvas(self):
        if not self.project:
            return
        sc = self.scene()
        visible = visible_at(self.parsed, self.current_frame) if sc else []
        self.canvas.show_frame(self.project, visible, sc.text if sc else "")
        if self._select_after:
            self.canvas.select(self._select_after)
            self._select_after = ""
        self.refresh_frame_panel(visible)

    def refresh_frame_panel(self, visible: list[str]):
        sc = self.scene()
        self.frame_title.setText(f"フレーム {sc.index + 1}: {sc.text[:20]}" if sc else "フレームがありません")
        cur = self.tree_name()
        self.item_tree.clear()
        for it in self.project.items:
            row = QTreeWidgetItem([it.name, KIND_NAMES.get(it.kind, it.kind),
                                   "表示中" if it.name in visible else "－", "固定" if it.locked else "未固定"])
            if it.name in visible:
                row.setForeground(2, QColor("#81c784"))
            self.item_tree.addTopLevelItem(row)
            if it.name == cur:
                self.item_tree.setCurrentItem(row)
        for i in range(4):
            self.item_tree.resizeColumnToContents(i)
        self.cmd_list.clear()
        if sc:
            for c in sc.commands:
                li = QListWidgetItem(c.describe())
                li.setData(Qt.UserRole, c)
                self.cmd_list.addItem(li)
        self.on_canvas_select(self.canvas.selected_name())

    def tree_name(self) -> str:
        it = self.item_tree.currentItem()
        return it.text(0) if it else self.canvas.selected_name()

    def on_canvas_select(self, name: str):
        it = self.project.item(name) if (self.project and name) else None
        self.ok_btn.setEnabled(bool(it and not it.locked))
        self.unlock_btn.setEnabled(bool(it and it.locked))
        for s in self.geo.values():
            s.setEnabled(bool(it and not it.locked))
        for wdg in self.fx_widgets:
            wdg.setEnabled(bool(it))
            wdg.blockSignals(True)
        if it:
            self.fx_alpha.setValue(int(round((1 - it.opacity) * 100)))
            self.fx_enter.setCurrentIndex(max(0, self.fx_enter.findData(it.enter)))
            self.fx_exit.setCurrentIndex(max(0, self.fx_exit.findData(it.exit)))
            self.fx_enter_dur.setValue(it.enter_dur)
            self.fx_exit_dur.setValue(it.exit_dur)
        for wdg in self.fx_widgets:
            wdg.blockSignals(False)
        if it:
            self.sel_label.setText(f"選択中: {it.name}（{'固定' if it.locked else '未固定 - 動かしてOK'}）")
            for k, s in self.geo.items():
                s.blockSignals(True)
                s.setValue(int(getattr(it, k)))
                s.blockSignals(False)
            for i in range(self.item_tree.topLevelItemCount()):
                if self.item_tree.topLevelItem(i).text(0) == name:
                    self.item_tree.setCurrentItem(self.item_tree.topLevelItem(i))
        else:
            self.sel_label.setText("素材を選んでください")

    def on_fx_edit(self, *_):
        name = self.canvas.selected_name() or self.tree_name()
        it = self.project.item(name) if (self.project and name) else None
        if not it:
            return
        it.opacity = 1 - self.fx_alpha.value() / 100
        it.enter = self.fx_enter.currentData()
        it.exit = self.fx_exit.currentData()
        it.enter_dur = float(self.fx_enter_dur.value())
        it.exit_dur = float(self.fx_exit_dur.value())
        self.mark_dirty()
        if name in self.canvas.gfx:
            self.canvas.gfx[name].setOpacity(max(0.15, it.opacity))

    def change_at_frame(self, kind: str, name: str):
        if not name or not self.project or not self.scene():
            return
        if name not in visible_at(self.parsed, self.current_frame):
            QMessageBox.information(self, APP_NAME, f"「{name}」はこのフレームで表示されていません。先に表示してください。")
            return
        cmd = ask_change(self, kind, name)
        if cmd:
            self.add_cmd(cmd)

    def on_geo_edit(self):
        name = self.canvas.selected_name()
        it = self.project.item(name) if self.project else None
        if not it or it.locked:
            return
        for k, s in self.geo.items():
            setattr(it, k, s.value())
        it.w, it.h = max(2, it.w), max(2, it.h)
        self.mark_dirty()
        self._select_after = name
        self.refresh_canvas()

    def on_item_moved(self, name: str):
        self.mark_dirty()
        self.on_canvas_select(name)

    def lock_item(self, name: str):
        it = self.project.item(name) if (self.project and name) else None
        if not it:
            return
        it.locked = True
        self.mark_dirty()
        if name in self.canvas.gfx:
            self.canvas.gfx[name].apply_lock()
        self.refresh_frame_panel(visible_at(self.parsed, self.current_frame) if self.scene() else [])
        self.statusBar().showMessage(f"「{name}」をこの場所で固定しました", 3000)

    def unlock_item(self, name: str):
        it = self.project.item(name) if (self.project and name) else None
        if not it:
            return
        it.locked = False
        self.mark_dirty()
        if name in self.canvas.gfx:
            self.canvas.gfx[name].apply_lock()
            self.canvas.select(name)
        self.refresh_frame_panel(visible_at(self.parsed, self.current_frame) if self.scene() else [])

    def item_menu(self, name: str, pos):
        it = self.project.item(name)
        if not it:
            return
        self.canvas.select(name)
        m = QMenu(self)
        if it.locked:
            m.addAction("解除（再配置する）", lambda: self.unlock_item(name))
        else:
            m.addAction("OK（この場所で固定）", lambda: self.lock_item(name))
        m.addSeparator()
        m.addAction("このフレームで消去", lambda: self.hide_at_frame(name))
        m.addAction("このフレームで大きさを変える…", lambda: self.change_at_frame("scale", name))
        m.addAction("このフレームで透明度を変える…", lambda: self.change_at_frame("alpha", name))
        m.addAction("最前面へ", lambda: self.set_z(name, max((i.z for i in self.project.items), default=0) + 1))
        m.addAction("最背面へ", lambda: self.set_z(name, min((i.z for i in self.project.items), default=0) - 1))
        m.addAction("元の縦横比に戻す", lambda: self.reset_ratio(name))
        m.addAction("名前を変更…", lambda: self.rename_item(name))
        if it.kind == "video":
            a = m.addAction("繰り返し再生する")
            a.setCheckable(True)
            a.setChecked(it.loop)
            a.toggled.connect(lambda v: (setattr(it, "loop", v), self.mark_dirty()))
            a = m.addAction("動画の音声も使う")
            a.setCheckable(True)
            a.setChecked(it.use_audio)
            a.toggled.connect(lambda v: (setattr(it, "use_audio", v), self.mark_dirty()))
        m.addSeparator()
        m.addAction("素材を削除…", lambda: self.delete_item(name))
        m.exec(pos)

    def set_z(self, name: str, z: int):
        it = self.project.item(name)
        if it:
            it.z = z
            self.mark_dirty()
            self._select_after = name
            self.refresh_canvas()

    def reset_ratio(self, name: str):
        from .canvas import item_pixmap

        it = self.project.item(name)
        pm = item_pixmap(self.project, it)
        if it and pm.width():
            it.h = round(it.w * pm.height() / pm.width())
            self.mark_dirty()
            self._select_after = name
            self.refresh_canvas()

    def _frame_cmd(self, kind: str, name: str) -> Command | None:
        sc = self.scene()
        if not sc:
            return None
        for c in sc.commands:
            if c.kind == kind and c.name == name:
                return c
        return None

    def show_at_frame(self, name: str):
        if not name or not self.project:
            return
        sc = self.ensure_frame()
        if sc is None:
            return
        hide = self._frame_cmd("hide", name)
        if hide:
            self.set_script(remove_command(self.editor.toPlainText(), hide))
        if name not in visible_at(self.parsed, self.current_frame):
            self.add_cmd(format_command("show", name))
        self._select_after = name
        self.refresh_canvas()

    def hide_at_frame(self, name: str):
        if not name or not self.scene():
            return
        show = self._frame_cmd("show", name)
        if show:
            # このフレームで表示した素材なら、表示命令を取り消す
            self.set_script(remove_command(self.editor.toPlainText(), show))
        elif name in visible_at(self.parsed, self.current_frame):
            self.add_cmd(format_command("hide", name))

    def remove_selected_cmd(self):
        li = self.cmd_list.currentItem()
        if li:
            self.set_script(remove_command(self.editor.toPlainText(), li.data(Qt.UserRole)))

    def delete_item(self, name: str):
        if not name or not self.project or not self.project.item(name):
            return
        r = QMessageBox.question(self, "素材を削除", f"「{name}」をプロジェクトから削除し、台本の表示・消去の命令も消しますか？\n"
                                                    "（素材フォルダのファイルは消えません）")
        if r != QMessageBox.Yes:
            return
        self.project.items = [i for i in self.project.items if i.name != name]
        self.mark_dirty()
        self.set_script(remove_item_commands(self.editor.toPlainText(), name))
        self.refresh_chars()

    def rename_item(self, name: str, new: str | None = None) -> str:
        it = self.project.item(name)
        if not it:
            return name
        if new is None:
            new, ok = QInputDialog.getText(self, "名前を変更", "新しい名前:", text=name)
            if not ok:
                return name
        new = new.strip()
        if not new or new == name:
            return name
        new = self.project.unique_name(new)
        it.name = new
        self.mark_dirty()
        self.set_script(rename_in_script(self.editor.toPlainText(), name, new))
        self.refresh_chars()
        return new

    def place_selected_asset(self):
        key = ["image", "video", "bgm", "se", "voice"][self.lib_tabs.currentIndex()]
        path = self.libs[key].current_path()
        if not path:
            return
        if key == "bgm":
            self.add_cmd(format_command("bgm", os.path.basename(path)))
        elif key == "se":
            self.add_cmd(format_command("se", os.path.basename(path)))
        elif key == "voice":
            QMessageBox.information(self, APP_NAME, "ボイスは台本の行で右クリック →「この行の音声ファイルを指定」で使えます。")
        else:
            self.place_asset(path)

    def place_asset(self, path: str, pos: QPointF | None = None):
        if not self.project or not path:
            return
        p = self.project
        ext = os.path.splitext(path)[1].lower()
        if ext in AUDIO_EXTS:
            r = QMessageBox.question(self, "音声の配置", "このフレームから BGM として流しますか？\n（いいえ = SE として1回鳴らす）",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return
            key = "bgm" if r == QMessageBox.Yes else "se"
            dst = copy_into(path, p.subfolder(key))
            self.add_cmd(format_command(key, os.path.basename(dst)))
            self.reload_libraries()
            return
        if ext in IMAGE_EXTS:
            kind, key = "image", "image"
        elif ext in VIDEO_EXTS:
            kind, key = "video", "video"
        else:
            QMessageBox.warning(self, APP_NAME, "この種類のファイルは使えません。")
            return
        if p.relpath(os.path.abspath(path)) == os.path.abspath(path):  # プロジェクト外
            path = copy_into(path, p.subfolder(key))
            self.reload_libraries()
        if self.ensure_frame() is None:
            return
        if kind == "image":
            img = QImage(path)
            sz = (img.width(), img.height()) if not img.isNull() else (400, 300)
        else:
            sz = media.video_size(path) or (640, 360)
        w, h = sz
        s = min(1.0, p.width * 0.6 / max(1, w), p.height * 0.6 / max(1, h))
        w, h = max(2, round(w * s)), max(2, round(h * s))
        if pos is None:
            x, y = (p.width - w) / 2, (p.height - h) / 2
        else:
            x, y = pos.x() - w / 2, pos.y() - h / 2
        name = p.unique_name(os.path.splitext(os.path.basename(path))[0])
        z = max((i.z for i in p.items if i.kind != "character"), default=0)
        p.items.append(Item(name=name, kind=kind, file=p.relpath(path), x=round(x), y=round(y), w=w, h=h, z=z))
        self.mark_dirty()
        self._select_after = name
        self.add_cmd(format_command("show", name))
        self.statusBar().showMessage(f"「{name}」を配置しました。位置を決めたら OK を押してください。", 6000)

    # ============================================================ 素材ライブラリ
    def reload_libraries(self):
        if not self.project:
            return
        for key, lw in self.libs.items():
            lw.reload(self.project.subfolder(key))
        for cb, key in ((self.bgm_cb, "bgm"), (self.se_cb, "se")):
            cur = cb.currentText()
            cb.clear()
            cb.addItems(list_files(self.project.subfolder(key), AUDIO_EXTS))
            cb.setCurrentText(cur)

    def _lib_key(self) -> str:
        return ["image", "video", "bgm", "se", "voice"][self.lib_tabs.currentIndex()]

    def add_files(self):
        if not self.project:
            return
        key = self._lib_key()
        exts = {"image": IMAGE_EXTS, "video": VIDEO_EXTS}.get(key, AUDIO_EXTS)
        flt = " ".join("*" + e for e in sorted(exts))
        paths, _ = QFileDialog.getOpenFileNames(self, "素材を追加", "", f"素材 ({flt})")
        for path in paths:
            copy_into(path, self.project.subfolder(key))
        self.reload_libraries()

    def open_lib_folder(self):
        if self.project:
            open_folder(self.project.subfolder(self._lib_key()))

    # ============================================================ 立ち絵
    def refresh_chars(self):
        if not self.project:
            return
        cur = self.char_list.currentItem().text() if self.char_list.currentItem() else ""
        self.char_list.blockSignals(True)
        self.char_list.clear()
        for c in self.project.characters():
            self.char_list.addItem(c.name)
        self.char_list.blockSignals(False)
        items = self.char_list.findItems(cur, Qt.MatchExactly)
        if items:
            self.char_list.setCurrentItem(items[0])
        elif self.char_list.count():
            self.char_list.setCurrentRow(0)
        self.load_char_form(self.char_list.currentRow())
        self.editor.highlighter.rehighlight()

    def current_char(self) -> Item | None:
        li = self.char_list.currentItem()
        return self.project.item(li.text()) if (li and self.project) else None

    def load_char_form(self, _row: int):
        c = self.current_char()
        self._char_loading = True
        try:
            self.ch_name.setText(c.name if c else "")
            for k, le in self.ch_files.items():
                le.setText(getattr(c, k) if c else "")
            self._fill_speaker_combo(self.ch_spk, c.speaker_id if c else -1, with_default=True)
            self.ch_speed.setValue(c.speed if c else 0)
        finally:
            self._char_loading = False

    def save_char_form(self, *_):
        if self._char_loading:
            return
        c = self.current_char()
        if not c:
            return
        c.speaker_id = int(self.ch_spk.currentData()) if self.ch_spk.currentData() is not None else -1
        c.speed = float(self.ch_speed.value())
        self.mark_dirty()

    def pick_char_file(self, key: str):
        c = self.current_char()
        if not c:
            QMessageBox.information(self, APP_NAME, "先に「立ち絵を追加」してください。")
            return
        flt = " ".join("*" + e for e in sorted(IMAGE_EXTS))
        path, _ = QFileDialog.getOpenFileName(self, "画像を選ぶ", self.project.subfolder("character"), f"画像 ({flt})")
        if not path:
            return
        path = copy_into(path, self.project.subfolder("character"))
        setattr(c, key, self.project.relpath(path))
        _thumb_cache.clear()
        self.mark_dirty()
        self.load_char_form(0)
        self.refresh_canvas()

    def add_character(self):
        if not self.project:
            return
        name, ok = QInputDialog.getText(self, "立ち絵を追加", "キャラクターの名前（台本の「名前：セリフ」で使います）:")
        if not ok or not name.strip():
            return
        flt = " ".join("*" + e for e in sorted(IMAGE_EXTS))
        closed, _ = QFileDialog.getOpenFileName(self, "口を閉じた画像を選ぶ", self.project.subfolder("character"),
                                                f"画像 ({flt})")
        if not closed:
            return
        opened, _ = QFileDialog.getOpenFileName(self, "口を開けた画像を選ぶ（リップシンク用・なければキャンセル）",
                                                os.path.dirname(closed), f"画像 ({flt})")
        p = self.project
        closed = copy_into(closed, p.subfolder("character"))
        opened = copy_into(opened, p.subfolder("character")) if opened else ""
        img = QImage(closed)
        w, h = (img.width(), img.height()) if not img.isNull() else (400, 600)
        s = min(1.0, p.height * 0.7 / max(1, h), p.width * 0.4 / max(1, w))
        w, h = round(w * s), round(h * s)
        z = max((i.z for i in p.items), default=0) + 1
        name = p.unique_name(name.strip())
        p.items.append(Item(name=name, kind="character", file=p.relpath(closed), file_open=p.relpath(opened),
                            x=p.width - w - round(p.width * 0.03), y=p.height - h, w=w, h=h, z=z))
        self.mark_dirty()
        self.refresh_chars()
        items = self.char_list.findItems(name, Qt.MatchExactly)
        if items:
            self.char_list.setCurrentItem(items[0])
        # 最初のフレームから表示
        if self.parsed.scenes:
            text = insert_command(self.editor.toPlainText(), self.parsed.scenes[0], format_command("show", name))
            self.set_script(text)
        else:
            self.set_script(format_command("show", name) + "\n" + self.editor.toPlainText())
        self.reparse()

    def rename_character(self):
        c = self.current_char()
        if c:
            self.rename_item(c.name, self.ch_name.text())

    def goto_char_on_canvas(self):
        c = self.current_char()
        if not c:
            return
        self.tabs.setCurrentIndex(1)
        # 表示されているフレームへ
        for sc in self.parsed.scenes:
            if c.name in visible_at(self.parsed, sc.index):
                self.goto_frame(sc.index)
                break
        self.canvas.select(c.name)

    # ============================================================ プレビュー・書き出し
    def render(self, preview: bool, from_frame: bool = False):
        if not self.project:
            return
        if self.worker and self.worker.isRunning():
            return
        self.reparse()
        p = self.project
        if not self.parsed.scenes and p.duration <= 0:
            QMessageBox.information(self, APP_NAME, "台本が空です。台本を書くか、動画の長さを指定してください。")
            return
        start = 0.0
        if preview:
            cache = os.path.join(p.folder, ".cache")
            os.makedirs(cache, exist_ok=True)
            for old in glob.glob(os.path.join(cache, "preview_*.mp4")):
                try:
                    os.remove(old)
                except OSError:
                    pass
            out = os.path.join(cache, f"preview_{int(time.time())}.mp4")
            scale = min(1.0, 960 / max(p.width, p.height))
            if from_frame and self.scene():
                start = self._estimate_start()
        else:
            safe = re.sub(r'[\\/:*?"<>|]', "_", p.name)
            out = os.path.join(p.folder, f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
            scale = 1.0
            self.save()
        self.worker = RenderWorker(p, out, scale, start, preview)
        dlg = QProgressDialog("準備中…", "キャンセル", 0, 1000, self)
        dlg.setWindowTitle("プレビューを作成中" if preview else "書き出し中")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setMinimumWidth(460)
        dlg.canceled.connect(self.worker.cancel)
        self.worker.progress.connect(lambda m, f: (dlg.setLabelText(m), dlg.setValue(int(f * 1000))))

        def done(path, warnings):
            dlg.reset()
            dlg.close()
            if warnings:
                QMessageBox.warning(self, "注意", "\n".join(warnings[:15]))
            if preview:
                if self.preview_win:
                    self.preview_win.close()
                self.preview_win = PreviewWindow(path, self)
                self.preview_win.show()
            else:
                r = QMessageBox.information(self, "書き出し完了", f"動画を書き出しました。\n{path}",
                                            QMessageBox.Open | QMessageBox.Ok)
                if r == QMessageBox.Open:
                    open_folder(path)

        def failed(msg):
            dlg.reset()
            dlg.close()
            QMessageBox.critical(self, "エラー", msg)

        self.worker.finished_ok.connect(done)
        self.worker.failed.connect(failed)
        self.worker.cancelled.connect(lambda: (dlg.close(), self.statusBar().showMessage("キャンセルしました", 3000)))
        self.worker.start()

    def _estimate_start(self) -> float:
        """このフレームの開始時刻（VOICEVOX のキャッシュ/音声ファイルから計算）。"""
        from ..timeline import build_timeline, resolve_voices

        try:
            voices, _ = resolve_voices(self.project, self.parsed)
            tl = build_timeline(self.project, self.parsed, voices)
            return tl.scene_start(self.current_frame)
        except Exception:  # noqa: BLE001
            return 0.0

    # ============================================================ ヘルプ
    def show_help(self):
        QMessageBox.information(self, "台本の書き方", HELP_TEXT)


HELP_TEXT = """【基本】1行 = 1フレーム（1場面）です。
  ずんだもん：こんにちは！    ← 立ち絵の名前：セリフ
  ナレーションの文            ← 名前なし（立ち絵が1人ならその人が話します）
  # メモ                      ← # で始まる行は無視されます

【命令】[ ] で書きます。その行（または次のセリフ行）の頭で実行されます。
  [画像:名前]     画像・動画・立ち絵を表示（名前は②配置タブの素材名）
  [消去:名前]     消す（消さない限り表示され続けます）
  [全消去]        全部消す
  [BGM:ファイル名]  BGMを開始（ループ）  [BGM停止] で止める
  [SE:ファイル名]   効果音を1回鳴らす
  [音声:ファイル名] この行の音声ファイルを指定（用意した音声モード）
  [秒数:3]        この行の長さを指定／単独の行ならセリフなしで3秒待つ
  [画像:名前,左から,0.5秒]  動きを付けて表示（左から/右から/上から/下から/フェード/ズーム）
  [消去:名前,右へ]   動きを付けて消す（左へ/右へ/上へ/下へ/フェード/ズーム）
  [大きさ:名前,150%,1秒]  1秒かけて元の150%の大きさに（中心を基準）
  [透明度:名前,50%,1秒]   1秒かけて透明度50%に（0%=そのまま、100%=見えない）

【操作】
・右クリック：切り取り／コピー／貼り付け、命令の挿入
・②配置：素材をキャンバスへドラッグ → 位置を決めて OK → 固定
         固定した素材をクリック → 解除 で再配置
         キャンバスの下で、素材ごとの透明度・登場/退場の動きを設定
・F5：プレビュー　Ctrl+E：書き出し（プロジェクトフォルダに保存）
"""
