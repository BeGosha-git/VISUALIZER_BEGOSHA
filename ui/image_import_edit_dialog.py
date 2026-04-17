"""
Диалог перед импортом изображения: удаление фона по цвету (хромакей)
и по связной области (клик — соседние пиксели в допуске по цвету).
"""
from __future__ import annotations

import ctypes
import logging
import os
import tempfile
from collections import deque
from functools import partial
from typing import List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QImage, QImageReader, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr

logger = logging.getLogger(__name__)

_MAX_WORK_SIDE = 640
_FLOOD_PIXEL_CAP = 200_000
_PREVIEW_DEBOUNCE_MS = 45
# Полный экспорт в numpy держит несколько больших массивов — сверх лимита OOM/краш приложения.
_MAX_EXPORT_PIXELS = 12_000_000

_CHECKER_BRUSH: Optional[QBrush] = None


def _checkerboard_brush() -> QBrush:
    global _CHECKER_BRUSH
    if _CHECKER_BRUSH is not None:
        return _CHECKER_BRUSH
    pm = QPixmap(24, 24)
    pm.fill(QColor(52, 52, 52))
    qp = QPainter(pm)
    qp.setBrush(QColor(88, 88, 88))
    qp.setPen(Qt.PenStyle.NoPen)
    qp.drawRect(0, 0, 12, 12)
    qp.drawRect(12, 12, 12, 12)
    qp.end()
    _CHECKER_BRUSH = QBrush(pm)
    return _CHECKER_BRUSH


def _qimage_to_rgba_np(img: QImage) -> np.ndarray:
    """Копирование RGBA в numpy; быстрый путь без построчного ctypes при плотном буфере (типичный случай)."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        raise ValueError("empty image")
    bpl = img.bytesPerLine()
    rb = w * 4
    bits = img.constBits()
    nbytes = img.sizeInBytes()
    try:
        bits.setsize(nbytes)
    except Exception:
        pass
    ptr = int(bits)
    # Плотная упаковка строк (без padding) — один копирующий проход вместо h вызовов string_at.
    if bpl == rb and nbytes >= h * rb:
        raw = ctypes.string_at(ptr, h * rb)
        return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4).copy()
    out = np.empty((h, w, 4), dtype=np.uint8)
    for y in range(h):
        row = ctypes.string_at(ptr + y * bpl, rb)
        out[y, :, :] = np.frombuffer(row, dtype=np.uint8).reshape(1, w, 4)
    return out


def _rgba_np_to_qimage(arr: np.ndarray) -> QImage:
    """numpy RGBA → QImage; быстрый путь при плотном буфере (один memmove)."""
    arr = np.ascontiguousarray(arr.astype(np.uint8, copy=False))
    h, w, _ = arr.shape
    out = QImage(w, h, QImage.Format.Format_RGBA8888)
    if out.isNull():
        raise MemoryError("QImage allocation failed")
    out.fill(0)
    bpl = out.bytesPerLine()
    rb = w * 4
    if bpl == rb:
        nb = h * rb
        qbits = out.bits()
        try:
            qbits.setsize(nb)
        except Exception:
            pass
        ctypes.memmove(int(qbits), arr.ctypes.data, nb)
        return out
    for y in range(h):
        line = out.scanLine(y)
        try:
            line.setsize(bpl)
        except Exception:
            pass
        ctypes.memmove(int(line), arr[y].ctypes.data, rb)
    return out


def _load_preview_and_orig_size(path: str, max_side: int) -> Tuple[QImage, int, int]:
    """Читает уменьшенную копию для редактирования и размер оригинала без полного декода в RAM."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    if not reader.canRead():
        img = QImage(path)
        if img.isNull():
            raise ValueError("bad image")
        w0, h0 = img.width(), img.height()
        work, _scale = _scale_qimage_long_side(img.convertToFormat(QImage.Format.Format_RGBA8888), max_side)
        return work, w0, h0
    sz = reader.size()
    if not sz.isValid() or sz.width() <= 0 or sz.height() <= 0:
        img = QImage(path)
        if img.isNull():
            raise ValueError("bad image")
        w0, h0 = img.width(), img.height()
        work, _ = _scale_qimage_long_side(img.convertToFormat(QImage.Format.Format_RGBA8888), max_side)
        return work, w0, h0
    w0, h0 = sz.width(), sz.height()
    m = max(w0, h0)
    if m > max_side:
        scale = max_side / float(m)
        nw = max(1, int(round(w0 * scale)))
        nh = max(1, int(round(h0 * scale)))
        reader.setScaledSize(QSize(nw, nh))
    work = reader.read()
    if work.isNull():
        raise ValueError("read failed")
    return work.convertToFormat(QImage.Format.Format_RGBA8888), w0, h0


def _scale_qimage_long_side(src: QImage, max_side: int) -> Tuple[QImage, float]:
    """Масштаб с сохранением пропорций; возвращает (картинка, масштаб относительно оригинала work/orig)."""
    w, h = src.width(), src.height()
    if w <= 0 or h <= 0:
        return src, 1.0
    m = max(w, h)
    if m <= max_side:
        return src.copy(), 1.0
    scale = max_side / float(m)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    scaled = src.scaled(nw, nh, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return scaled, scaled.width() / float(w)


def _chroma_alpha_channel(rgb: np.ndarray, refs: List[Tuple[int, int, int]], tol: int, feather: int) -> np.ndarray:
    """Альфа: 0 — убрано (близко к одному из ref), 255 — оставить. feather — мягкий переход по расстоянию (L∞)."""
    h, w, _ = rgb.shape
    if not refs:
        return np.full((h, w), 255, dtype=np.uint8)
    dmin = np.full((h, w), 999, dtype=np.int16)
    rch = rgb[:, :, 0].astype(np.int16)
    gch = rgb[:, :, 1].astype(np.int16)
    bch = rgb[:, :, 2].astype(np.int16)
    for rr, gg, bb in refs:
        d = np.maximum(np.maximum(np.abs(rch - rr), np.abs(gch - gg)), np.abs(bch - bb))
        dmin = np.minimum(dmin, d)
    dmin_f = dmin.astype(np.float32)
    if feather <= 0:
        return np.where(dmin_f > float(tol), 255, 0).astype(np.uint8)
    t = np.clip((dmin_f - float(tol)) / float(max(feather, 1)), 0.0, 1.0)
    return (t * 255.0).astype(np.uint8)


def _flood_mask_at(rgb: np.ndarray, sx: int, sy: int, tol: int) -> Tuple[np.ndarray, bool]:
    """Связная область от (sx,sy), 8-соседство; L∞ от цвета семени <= tol.

    В очередь добавляются только ещё не обработанные клетки — иначе миллионы
    дубликатов координат и зависание UI.
    """
    h, w, _ = rgb.shape
    if not (0 <= sx < w and 0 <= sy < h):
        return np.zeros((h, w), dtype=bool), False
    seed = rgb[sy, sx].astype(np.int16)
    visited = np.zeros((h, w), dtype=bool)
    out = np.zeros((h, w), dtype=bool)
    dq: deque[Tuple[int, int]] = deque()
    dq.append((sx, sy))
    steps = 0
    truncated = False
    neigh = (
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    )
    while dq:
        x, y = dq.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or visited[y, x]:
            continue
        px = rgb[y, x].astype(np.int16)
        if int(np.max(np.abs(px - seed))) > tol:
            visited[y, x] = True
            continue
        visited[y, x] = True
        out[y, x] = True
        steps += 1
        if steps >= _FLOOD_PIXEL_CAP:
            truncated = True
            break
        for dx, dy in neigh:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx]:
                dq.append((nx, ny))
    return out, truncated


def _upsample_mask_nearest(mask: np.ndarray, H: int, W: int) -> np.ndarray:
    h, w = mask.shape
    if h == H and w == W:
        return mask
    ys = np.minimum((np.arange(H, dtype=np.float64) * h / H).astype(np.int32), h - 1)
    xs = np.minimum((np.arange(W, dtype=np.float64) * w / W).astype(np.int32), w - 1)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    return mask[yy, xx]


def _separable_box_blur_01(x: np.ndarray, r: int) -> np.ndarray:
    """Раздельный box blur для массива 0..1, r — радиус в пикселях (1..8)."""
    r = int(max(1, min(8, r)))
    k = 2 * r + 1
    ker = np.ones(k, dtype=np.float64) / float(k)
    pad = r
    h, w = x.shape
    xp = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    tmp = np.empty((h, w), dtype=np.float64)
    for i in range(h):
        tmp[i] = np.convolve(xp[i], ker, mode="valid")
    xp2 = np.pad(tmp, ((pad, pad), (0, 0)), mode="reflect")
    out = np.empty((h, w), dtype=np.float64)
    for j in range(w):
        out[:, j] = np.convolve(xp2[:, j], ker, mode="valid")
    return out


def _refine_alpha_edges(alpha: np.ndarray, signed_r: int) -> np.ndarray:
    """signed_r > 0 — размыть альфу (мягче контур). signed_r < 0 — обострить край (unsharp по α). 0 — без изменений."""
    sr = int(np.clip(signed_r, -8, 8))
    if sr == 0 or alpha.size == 0:
        return alpha
    x = alpha.astype(np.float64) / 255.0
    if sr > 0:
        out = _separable_box_blur_01(x, sr)
        return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)
    k = -sr
    blurred = _separable_box_blur_01(x, k)
    lam = 0.14 * float(k)
    sharp = np.clip(x + lam * (x - blurred), 0.0, 1.0)
    return np.clip(np.round(sharp * 255.0), 0, 255).astype(np.uint8)


class _PreviewView(QGraphicsView):
    """Превью с шахматкой: Ctrl+колесо — масштаб; кнопка «Подогнать» сбрасывает вид."""

    def __init__(self, owner: "ImageImportEditDialog"):
        super().__init__()
        self._owner = owner
        self._item: Optional[QGraphicsPixmapItem] = None
        self.setMinimumHeight(340)
        self.setMinimumWidth(400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def set_pixmap(self, pm: QPixmap) -> None:
        if self._item is None:
            scene = QGraphicsScene(self)
            self.setScene(scene)
            self._item = QGraphicsPixmapItem(pm)
            scene.addItem(self._item)
        else:
            self._item.setPixmap(pm)
        self.resetTransform()
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_fit(self) -> None:
        if self._item is None:
            return
        self.resetTransform()
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.12 if delta > 0 else 1.0 / 1.12
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._item and event.button() == Qt.MouseButton.LeftButton:
            p = self.mapToScene(event.position().toPoint())
            lp = self._item.mapFromScene(p)
            x, y = int(lp.x()), int(lp.y())
            br = self._item.boundingRect()
            if 0 <= x < int(br.width()) and 0 <= y < int(br.height()):
                self._owner.on_canvas_click(x, y)
        super().mousePressEvent(event)


class ImageImportEditDialog(QDialog):
    """Диалог импорта: тяжёлая загрузка превью — в слоте после показа окна, иначе после выбора файла UI «мёртвый»."""

    def __init__(self, source_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("image_import.title"))
        self.resize(1180, 800)
        self._source_path = source_path
        self._ready = False
        self._heavy_init_started = False
        self._boot_cancelled = False
        self._result_path: Optional[str] = None
        self._skip_edit = False
        self._refs: List[Tuple[int, int, int]] = []
        self._preview_timer: Optional[QTimer] = None
        # Заполняются в _heavy_init_step
        self._work_q: Optional[QImage] = None
        self._w0 = 0
        self._h0 = 0
        self._base = None
        self._rgb = None
        self._flood_mask = None

        root = QVBoxLayout(self)
        boot = QLabel(tr("image_import.loading_preview"))
        boot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        boot.setWordWrap(True)
        root.addWidget(boot, 1)
        boot_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        boot_btns.rejected.connect(self._on_boot_cancel)
        root.addWidget(boot_btns)

        QTimer.singleShot(0, self._heavy_init_step)

    def _on_boot_cancel(self) -> None:
        self._boot_cancelled = True
        self.reject()

    def _heavy_init_step(self) -> None:
        if self._heavy_init_started:
            return
        self._heavy_init_started = True
        if self._boot_cancelled:
            return
        try:
            from PyQt6 import sip

            if sip.isdeleted(self):
                return
        except Exception:
            pass
        try:
            self._work_q, self._w0, self._h0 = _load_preview_and_orig_size(self._source_path, _MAX_WORK_SIDE)
            self._base = _qimage_to_rgba_np(self._work_q)
            self._rgb = self._base[:, :, :3].copy()
            self._flood_mask = np.zeros(self._rgb.shape[:2], dtype=bool)
        except Exception as e:
            logger.warning("image import preview init failed: %s", e, exc_info=True)
            QMessageBox.critical(self, tr("msg.error"), str(e))
            self.reject()
            return

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._do_refresh_preview)

        if self._boot_cancelled:
            return
        try:
            from PyQt6 import sip

            if sip.isdeleted(self):
                return
        except Exception:
            pass

        lay = self.layout()
        if not isinstance(lay, QVBoxLayout):
            return
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self._build_main_ui(lay)
        self._ready = True
        QTimer.singleShot(0, self._do_refresh_preview)

    def _build_main_ui(self, root: QVBoxLayout) -> None:
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 8, 0)
        left_l.setSpacing(6)
        self._view = _PreviewView(self)
        self._view.setBackgroundBrush(_checkerboard_brush())
        left_l.addWidget(self._view, 1)
        zoom_row = QHBoxLayout()
        self._btn_fit = QPushButton(tr("image_import.fit_view"))
        self._btn_fit.clicked.connect(self._view.zoom_fit)
        zoom_row.addWidget(self._btn_fit)
        zoom_hint = QLabel(tr("image_import.zoom_hint"))
        zoom_hint.setStyleSheet("color: #888; font-size: 11px;")
        zoom_hint.setWordWrap(True)
        zoom_row.addWidget(zoom_hint, 1)
        left_l.addLayout(zoom_row)

        right = QWidget()
        right.setMinimumWidth(360)
        right.setMaximumWidth(520)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(8, 0, 0, 0)
        right_l.setSpacing(10)

        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._btn_mode_chroma = QPushButton(tr("image_import.mode_chroma_short"))
        self._btn_mode_chroma.setCheckable(True)
        self._btn_mode_flood = QPushButton(tr("image_import.mode_flood_short"))
        self._btn_mode_flood.setCheckable(True)
        self._btn_mode_chroma.setMinimumHeight(36)
        self._btn_mode_flood.setMinimumHeight(36)
        self._mode_group.addButton(self._btn_mode_chroma, 0)
        self._mode_group.addButton(self._btn_mode_flood, 1)
        self._btn_mode_chroma.setChecked(True)
        self._mode_group.idClicked.connect(self._on_mode_group_changed)
        mode_row.addWidget(self._btn_mode_chroma, 1)
        mode_row.addWidget(self._btn_mode_flood, 1)
        right_l.addLayout(mode_row)

        self._hint = QLabel(tr("image_import.hint_chroma_short"))
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #b0b0b0; font-size: 12px;")
        right_l.addWidget(self._hint)

        tol_form = QFormLayout()
        self._tol_slider = QSlider(Qt.Orientation.Horizontal)
        self._tol_slider.setRange(0, 120)
        self._tol_slider.setValue(24)
        self._tol_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._tol_slider.setTickInterval(20)
        self._tol_val = QLabel("24")
        self._tol_val.setMinimumWidth(28)
        self._tol_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tol_wrap = QWidget()
        tol_h = QHBoxLayout(tol_wrap)
        tol_h.setContentsMargins(0, 0, 0, 0)
        tol_h.addWidget(self._tol_slider, 1)
        tol_h.addWidget(self._tol_val, 0)
        tol_form.addRow(tr("image_import.tolerance"), tol_wrap)
        self._tol_slider.valueChanged.connect(self._on_tol_slider_changed)
        right_l.addLayout(tol_form)

        edge_form = QFormLayout()
        self._edge_soft_slider = QSlider(Qt.Orientation.Horizontal)
        self._edge_soft_slider.setRange(-8, 8)
        self._edge_soft_slider.setValue(0)
        self._edge_soft_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._edge_soft_slider.setTickInterval(4)
        self._edge_soft_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._edge_soft_slider.setToolTip(tr("image_import.edge_soften_tip"))
        self._edge_soft_val = QLabel("0")
        self._edge_soft_val.setMinimumWidth(30)
        self._edge_soft_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        edge_wrap = QWidget()
        edge_h = QHBoxLayout(edge_wrap)
        edge_h.setContentsMargins(0, 0, 0, 0)
        edge_h.addWidget(self._edge_soft_slider, 1)
        edge_h.addWidget(self._edge_soft_val, 0)
        edge_form.addRow(tr("image_import.edge_soften"), edge_wrap)
        self._edge_soft_slider.valueChanged.connect(self._on_edge_soft_slider_changed)
        right_l.addLayout(edge_form)

        fe_form = QFormLayout()
        self._feather_slider = QSlider(Qt.Orientation.Horizontal)
        self._feather_slider.setRange(0, 48)
        self._feather_slider.setValue(6)
        self._feather_val = QLabel("6")
        self._feather_val.setMinimumWidth(28)
        self._feather_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fe_wrap = QWidget()
        fe_h = QHBoxLayout(fe_wrap)
        fe_h.setContentsMargins(0, 0, 0, 0)
        fe_h.addWidget(self._feather_slider, 1)
        fe_h.addWidget(self._feather_val, 0)
        fe_form.addRow(tr("image_import.feather"), fe_wrap)
        self._feather_slider.valueChanged.connect(self._on_feather_slider_changed)
        self._feather_row = QWidget()
        self._feather_row.setLayout(fe_form)
        right_l.addWidget(self._feather_row)

        self._swatch_caption = QLabel(tr("image_import.colors_remove"))
        self._swatch_caption.setWordWrap(True)
        self._swatch_caption.setStyleSheet("color: #aaa; font-size: 11px;")
        right_l.addWidget(self._swatch_caption)
        self._swatch_scroll = QScrollArea()
        self._swatch_scroll.setWidgetResizable(True)
        self._swatch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._swatch_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._swatch_scroll.setMaximumHeight(56)
        sw_inner = QWidget()
        self._swatch_layout = QHBoxLayout(sw_inner)
        self._swatch_layout.setContentsMargins(2, 2, 2, 2)
        self._swatch_layout.setSpacing(6)
        self._swatch_scroll.setWidget(sw_inner)
        right_l.addWidget(self._swatch_scroll)

        row = QHBoxLayout()
        self._btn_clear_colors = QPushButton(tr("image_import.clear_colors"))
        self._btn_clear_colors.clicked.connect(self._clear_colors)
        row.addWidget(self._btn_clear_colors)
        self._btn_clear_flood = QPushButton(tr("image_import.clear_flood"))
        self._btn_clear_flood.clicked.connect(self._clear_flood)
        row.addWidget(self._btn_clear_flood)
        self._btn_reset = QPushButton(tr("image_import.reset"))
        self._btn_reset.clicked.connect(self._reset_all)
        row.addWidget(self._btn_reset)
        row.addStretch()
        right_l.addLayout(row)

        self._color_info = QLabel("—")
        self._color_info.setStyleSheet("font-family: monospace;")
        right_l.addWidget(self._color_info)
        right_l.addStretch(1)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([760, 400])
        root.addWidget(split, 1)

        buttons = QDialogButtonBox()
        self._btn_skip = QPushButton(tr("image_import.skip"))
        buttons.addButton(self._btn_skip, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._on_ok_clicked)
        buttons.rejected.connect(self.reject)
        self._btn_skip.clicked.connect(self._accept_skip)
        root.addWidget(buttons)

        self._rebuild_swatches()
        self._sync_mode_tool_visibility()

    def _on_tol_slider_changed(self, v: int) -> None:
        self._tol_val.setText(str(int(v)))
        self._schedule_preview_refresh()

    def _on_feather_slider_changed(self, v: int) -> None:
        self._feather_val.setText(str(int(v)))
        self._schedule_preview_refresh()

    def _on_edge_soft_slider_changed(self, v: int) -> None:
        self._edge_soft_val.setText(str(int(v)))
        self._schedule_preview_refresh()

    def _tolerance_value(self) -> int:
        return int(self._tol_slider.value())

    def _feather_value(self) -> int:
        return int(self._feather_slider.value())

    def _edge_soften_value(self) -> int:
        return int(self._edge_soft_slider.value())

    def _active_mode(self) -> str:
        return "flood" if self._btn_mode_flood.isChecked() else "chroma"

    def _on_mode_group_changed(self, _id: int) -> None:
        if not self._ready:
            return
        if self._active_mode() == "flood":
            self._hint.setText(tr("image_import.hint_flood_short"))
        else:
            self._hint.setText(tr("image_import.hint_chroma_short"))
        self._sync_mode_tool_visibility()
        self._do_refresh_preview()

    def _sync_mode_tool_visibility(self) -> None:
        chroma = self._active_mode() == "chroma"
        self._swatch_caption.setVisible(chroma)
        self._swatch_scroll.setVisible(chroma)
        self._btn_clear_colors.setVisible(chroma)
        self._feather_row.setVisible(chroma)
        self._btn_clear_flood.setVisible(not chroma)

    def _rebuild_swatches(self) -> None:
        if self._swatch_layout is None:
            return
        while self._swatch_layout.count():
            item = self._swatch_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not self._refs:
            lab = QLabel(tr("image_import.no_colors_yet"))
            lab.setStyleSheet("color: #777; font-size: 11px;")
            self._swatch_layout.addWidget(lab)
            self._swatch_layout.addStretch(1)
        else:
            for i, (r, g, b) in enumerate(self._refs):
                btn = QPushButton()
                btn.setFixedSize(36, 36)
                btn.setToolTip(tr("image_import.remove_color_tip"))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: rgb({r},{g},{b}); border: 2px solid #666; border-radius: 6px; }}"
                    f"QPushButton:hover {{ border: 2px solid #ccc; }}"
                )
                btn.clicked.connect(partial(self._remove_color_at, i))
                self._swatch_layout.addWidget(btn)
        self._swatch_layout.addStretch(1)

    def _remove_color_at(self, index: int) -> None:
        if not self._ready:
            return
        if 0 <= index < len(self._refs):
            del self._refs[index]
            self._rebuild_swatches()
            self._do_refresh_preview()

    def _schedule_preview_refresh(self) -> None:
        if not self._ready or self._preview_timer is None:
            return
        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)

    def _on_ok_clicked(self) -> None:
        if not self._ready or self._flood_mask is None:
            return
        if not self._refs and not np.any(self._flood_mask):
            self._result_path = self._source_path
            super().accept()
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._result_path = self._export_full_png()
        except Exception as e:
            QMessageBox.critical(self, tr("msg.error"), str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        super().accept()

    def _clear_colors(self) -> None:
        if not self._ready:
            return
        self._refs.clear()
        self._rebuild_swatches()
        self._do_refresh_preview()

    def _clear_flood(self) -> None:
        if not self._ready or self._flood_mask is None:
            return
        self._flood_mask.fill(False)
        self._do_refresh_preview()

    def _reset_all(self) -> None:
        if not self._ready or self._flood_mask is None:
            return
        self._refs.clear()
        self._flood_mask.fill(False)
        self._tol_slider.blockSignals(True)
        self._feather_slider.blockSignals(True)
        self._edge_soft_slider.blockSignals(True)
        self._tol_slider.setValue(24)
        self._feather_slider.setValue(6)
        self._edge_soft_slider.setValue(0)
        self._tol_val.setText("24")
        self._feather_val.setText("6")
        self._edge_soft_val.setText("0")
        self._tol_slider.blockSignals(False)
        self._feather_slider.blockSignals(False)
        self._edge_soft_slider.blockSignals(False)
        self._rebuild_swatches()
        self._do_refresh_preview()

    def _compose_rgba(self) -> np.ndarray:
        if self._rgb is None or self._flood_mask is None:
            raise RuntimeError("compose before init")
        a = _chroma_alpha_channel(self._rgb, self._refs, self._tolerance_value(), self._feather_value())
        a = a.copy()
        a[self._flood_mask] = 0
        a = _refine_alpha_edges(a, self._edge_soften_value())
        return np.dstack([self._rgb, a])

    def _do_refresh_preview(self) -> None:
        if not self._ready or self._view is None or self._rgb is None or self._flood_mask is None:
            return
        comp = self._compose_rgba()
        qimg = _rgba_np_to_qimage(comp)
        self._view.set_pixmap(QPixmap.fromImage(qimg))

    def on_canvas_click(self, x: int, y: int) -> None:
        if not self._ready or self._base is None or self._rgb is None or self._flood_mask is None:
            return
        r, g, b, _a = (int(v) for v in self._base[y, x])
        self._color_info.setText(tr("image_import.picked_rgb", r=r, g=g, b=b))
        mode = self._active_mode()
        if mode == "chroma":
            self._refs.append((r, g, b))
            self._rebuild_swatches()
            self._do_refresh_preview()
        else:
            mask, truncated = _flood_mask_at(self._rgb, x, y, self._tolerance_value())
            self._flood_mask |= mask
            self._do_refresh_preview()
            if truncated:
                QMessageBox.warning(self, tr("msg.warning"), tr("image_import.flood_truncated"))

    def _accept_skip(self) -> None:
        self._skip_edit = True
        super().accept()

    def _export_full_png(self) -> str:
        reader = QImageReader(self._source_path)
        reader.setAutoTransform(True)
        full = reader.read()
        if full.isNull():
            full = QImage(self._source_path)
        if full.isNull():
            raise OSError("full image read failed")
        full = full.convertToFormat(QImage.Format.Format_RGBA8888)
        w0, h0 = full.width(), full.height()
        if w0 * h0 > _MAX_EXPORT_PIXELS:
            lim_mpx = max(1, _MAX_EXPORT_PIXELS // 1_000_000)
            raise OSError(
                tr("image_import.export_size_limit", w=w0, h=h0, lim=lim_mpx)
            )
        try:
            full_np = _qimage_to_rgba_np(full)
            rgb = full_np[:, :, :3]
            a = _chroma_alpha_channel(rgb, self._refs, self._tolerance_value(), self._feather_value())
            mask_full = _upsample_mask_nearest(self._flood_mask, self._h0, self._w0)
            a = a.copy()
            a[mask_full] = 0
            a = _refine_alpha_edges(a, self._edge_soften_value())
            full_np[:, :, 3] = a
            out_img = _rgba_np_to_qimage(full_np)
        except MemoryError as e:
            raise OSError(tr("err.image_memory", detail=str(e))) from e
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="aviz_import_")
        os.close(fd)
        if not out_img.save(tmp, "PNG"):
            raise OSError("save png failed")
        return tmp

    def get_output_path(self) -> str:
        if self._skip_edit:
            return self._source_path
        return self._result_path or self._source_path


def run_image_import_edit_dialog(source_path: str, parent: Optional[QWidget] = None) -> Optional[str]:
    """
    Показать диалог обработки импорта.
    Возвращает путь к файлу для импорта, либо None при отмене пользователем.
    При сбое диалога (инициализация/exec) возвращается исходный путь — импорт без правок.
    """
    try:
        dlg = ImageImportEditDialog(source_path, parent)
    except Exception as e:
        logger.warning("image import dialog init failed: %s", e, exc_info=True)
        return source_path
    try:
        code = dlg.exec()
    except Exception as e:
        logger.error("image import dialog exec failed: %s", e, exc_info=True)
        return source_path
    if code != QDialog.DialogCode.Accepted:
        return None
    return dlg.get_output_path()
