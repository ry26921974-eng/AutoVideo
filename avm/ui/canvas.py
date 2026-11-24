"""配置用キャンバス。画像をドラッグで動かし、OKで固定、クリック→解除で再配置。"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QImage, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsObject, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsView)

from .. import media
from ..model import Item, Project
from ..renderer import draw_subtitle

ASSET_MIME_PREFIX = "avm-asset:"

_thumb_cache: dict[tuple[str, float], QPixmap] = {}


def item_pixmap(project: Project, it: Item) -> QPixmap:
    path = project.abspath(it.file)
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        key = (path, 0.0)
    if key in _thumb_cache:
        return _thumb_cache[key]
    pm = QPixmap()
    if it.kind == "video":
        data = media.video_first_frame(path, 960) if os.path.exists(path) else None
        if data:
            pm.loadFromData(data)
    else:
        pm.load(path)
    if pm.isNull():
        pm = QPixmap(160, 120)
        pm.fill(QColor("#884444"))
        p = QPainter(pm)
        p.setPen(Qt.white)
        p.drawText(pm.rect(), Qt.AlignCenter, "ファイルが\n見つかりません")
        p.end()
    _thumb_cache[key] = pm
    return pm


class OkButton(QGraphicsObject):
    """未固定の素材の右上に出る OK ボタン（画面上の大きさは一定）。"""

    def __init__(self, parent: "ItemGfx"):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return QRectF(-58, 4, 54, 28)

    def paint(self, p: QPainter, *_):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#ffffff"), 1.5))
        p.setBrush(QColor("#2e9d4f"))
        p.drawRoundedRect(self.boundingRect(), 6, 6)
        f = QFont()
        f.setBold(True)
        f.setPixelSize(15)
        p.setFont(f)
        p.drawText(self.boundingRect(), Qt.AlignCenter, "OK")

    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        self.parentItem().lock_requested.emit(self.parentItem().item.name)  # type: ignore[union-attr]


class ResizeHandle(QGraphicsObject):
    """右下のサイズ変更つまみ。Shift を押しながらで縦横比を自由に。"""

    def __init__(self, parent: "ItemGfx"):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setZValue(10)
        self._ratio = 1.0

    def boundingRect(self) -> QRectF:
        return QRectF(-9, -9, 18, 18)

    def paint(self, p: QPainter, *_):
        p.setPen(QPen(QColor("#ffffff"), 1.5))
        p.setBrush(QColor("#ff9800"))
        p.drawRect(QRectF(-7, -7, 14, 14))

    def mousePressEvent(self, e):
        it = self.parentItem().item  # type: ignore[union-attr]
        self._ratio = it.h / it.w if it.w else 1.0
        e.accept()

    def mouseMoveEvent(self, e):
        g: ItemGfx = self.parentItem()  # type: ignore[assignment]
        local = g.mapFromScene(e.scenePos())
        w = max(10.0, local.x())
        h = max(10.0, local.y()) if e.modifiers() & Qt.ShiftModifier else w * self._ratio
        g.set_size(w, h)

    def mouseReleaseEvent(self, e):
        g: ItemGfx = self.parentItem()  # type: ignore[assignment]
        g.changed.emit(g.item.name)


class ItemGfx(QGraphicsObject):
    changed = Signal(str)
    lock_requested = Signal(str)
    locked_clicked = Signal(str, QPoint)

    def __init__(self, project: Project, item: Item):
        super().__init__()
        self.project = project
        self.item = item
        self.pixmap = item_pixmap(project, item)
        self.setPos(item.x, item.y)
        self.setZValue(item.z)
        self.ok = OkButton(self)
        self.handle = ResizeHandle(self)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.apply_lock()

    def apply_lock(self) -> None:
        locked = self.item.locked
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        self.ok.setVisible(not locked)
        self.handle.setVisible(not locked)
        self.setCursor(Qt.PointingHandCursor if locked else Qt.SizeAllCursor)
        self._place_children()
        self.update()

    def _place_children(self) -> None:
        self.ok.setPos(self.item.w, 0)
        self.handle.setPos(self.item.w, self.item.h)

    def set_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self.item.w, self.item.h = round(w), round(h)
        self._place_children()
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.item.w, self.item.h)

    def paint(self, p: QPainter, *_):
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(self.boundingRect(), self.pixmap, QRectF(self.pixmap.rect()))
        scale = p.transform().m11() or 1.0
        if not self.item.locked:
            pen = QPen(QColor("#ff9800"), 3 / scale, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.boundingRect())
        elif self.isSelected():
            p.setPen(QPen(QColor("#4fc3f7"), 2 / scale))
            p.drawRect(self.boundingRect())

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.item.x, self.item.y = round(self.pos().x()), round(self.pos().y())
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self.item.locked and e.button() == Qt.LeftButton:
            self.locked_clicked.emit(self.item.name, QCursor.pos())

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if not self.item.locked:
            self.changed.emit(self.item.name)

    def contextMenuEvent(self, e):
        self.locked_clicked.emit(self.item.name, QCursor.pos())


class CanvasView(QGraphicsView):
    asset_dropped = Signal(str, QPointF)  # ファイルパス, キャンバス上の位置
    item_changed = Signal(str)
    item_lock_requested = Signal(str)
    item_menu_requested = Signal(str, QPoint)
    selection_changed_name = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#3a3a3a")))
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.project: Project | None = None
        self.gfx: dict[str, ItemGfx] = {}
        self.bg: QGraphicsRectItem | None = None
        self.sub: QGraphicsPixmapItem | None = None
        self.scene().selectionChanged.connect(self._sel_changed)

    def _sel_changed(self):
        try:
            sel = self.scene().selectedItems()
        except RuntimeError:
            return
        name = sel[0].item.name if sel and isinstance(sel[0], ItemGfx) else ""
        self.selection_changed_name.emit(name)

    def selected_name(self) -> str:
        sel = [g for g in self.scene().selectedItems() if isinstance(g, ItemGfx)]
        return sel[0].item.name if sel else ""

    def select(self, name: str) -> None:
        self.scene().clearSelection()
        if name in self.gfx:
            self.gfx[name].setSelected(True)

    def show_frame(self, project: Project, visible: list[str], subtitle: str = "") -> None:
        sel = self.selected_name()
        self.project = project
        sc = self.scene()
        sc.blockSignals(True)
        sc.clear()
        sc.blockSignals(False)
        self.gfx.clear()
        W, H = project.width, project.height
        sc.setSceneRect(QRectF(-W * 0.05, -H * 0.05, W * 1.1, H * 1.1))
        self.bg = sc.addRect(QRectF(0, 0, W, H), QPen(QColor("#888888"), 0), QBrush(QColor(project.bg_color)))
        self.bg.setZValue(-1e6)
        order = {n: i for i, n in enumerate(visible)}
        for name in visible:
            it = project.item(name)
            if it is None:
                continue
            g = ItemGfx(project, it)
            g.setZValue(it.z * 1000 + order[name])
            g.changed.connect(self.item_changed)
            g.lock_requested.connect(self.item_lock_requested)
            g.locked_clicked.connect(self.item_menu_requested)
            sc.addItem(g)
            self.gfx[name] = g
        if project.subtitles and subtitle:
            img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            draw_subtitle(p, subtitle, W, H, project)
            p.end()
            self.sub = sc.addPixmap(QPixmap.fromImage(img))
            self.sub.setZValue(1e7)
            self.sub.setAcceptedMouseButtons(Qt.NoButton)
            self.sub.setOpacity(0.85)
        # 画面の外を薄暗く
        frame = sc.addRect(QRectF(0, 0, W, H), QPen(QColor("#dddddd"), 0))
        frame.setZValue(1e7 + 1)
        frame.setAcceptedMouseButtons(Qt.NoButton)
        self.select(sel)
        self.fit()

    def fit(self) -> None:
        if self.project:
            W, H = self.project.width, self.project.height
            self.fitInView(QRectF(-W * 0.03, -H * 0.03, W * 1.06, H * 1.06), Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    # ---- ドラッグ＆ドロップ ----
    def _drop_path(self, md) -> str:
        if md.hasText() and md.text().startswith(ASSET_MIME_PREFIX):
            return md.text()[len(ASSET_MIME_PREFIX):]
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    return u.toLocalFile()
        return ""

    def dragEnterEvent(self, e):
        if self._drop_path(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._drop_path(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        path = self._drop_path(e.mimeData())
        if path:
            e.acceptProposedAction()
            self.asset_dropped.emit(path, self.mapToScene(e.position().toPoint()))
        else:
            super().dropEvent(e)
