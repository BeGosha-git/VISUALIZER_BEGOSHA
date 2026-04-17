"""
Базовый класс для элементов визуализации
"""
import uuid

from PyQt6.QtCore import QPointF, QRectF, Qt, QVariant
from PyQt6.QtGui import QPainter, QPainterPath, QPen, QBrush, QColor, QTransform
from PyQt6.QtWidgets import QGraphicsItem
import numpy as np
from typing import List, Optional, Tuple, Dict, Any
import logging

# Настройка логирования
logger = logging.getLogger(__name__)


class BaseVisualizationElement(QGraphicsItem):
    """Базовый класс для элементов визуализации"""

    _geometry_commit_notifier = None
    _position_ui_notifier = None
    # True — не применять snap в ItemPositionChange (ввод координат в свойствах, скрипты).
    _suppress_position_snap: bool = False

    @classmethod
    def set_geometry_commit_notifier(cls, fn):
        """Вызывается после завершённого сдвига элемента (ItemPositionHasChanged), для undo/redo в редакторе."""
        cls._geometry_commit_notifier = fn

    @classmethod
    def set_position_ui_notifier(cls, fn):
        """После ItemPositionHasChanged — обновить поля позиции в UI (редактор)."""
        cls._position_ui_notifier = fn

    @classmethod
    def set_position_snap_suppressed(cls, suppressed: bool) -> None:
        cls._suppress_position_snap = bool(suppressed)

    def __init__(self, x: float = 0, y: float = 0, width: float = 100, height: float = 100):
        super().__init__()
        self.setPos(x, y)
        self.width = width
        self.height = height
        self.frequency_ranges: List[Tuple[float, float]] = []
        self.amplitude = 1.0
        self.audio_data = np.array([])
        self.fft_data = np.array([])
        self.frequencies = np.array([])
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        # Для resize handles (визуал и зона попадания чуть шире)
        self.resize_handle_size = 10
        self.resize_hit_margin = 4
        self.is_resizing = False
        self.resize_corner = None
        self.flip_h = False
        self.flip_v = False
        self.rotation_deg = 0.0
        self.rotate_handle_radius = 7.0
        self.rotate_handle_offset = 18.0
        # 0 — без временного сглаживания амплитуды; 1–5 — сильнее (картинка, текст, волна и т.д.).
        # Для волны/линии/осциллографа дополнительно: проходы Чайкина по ломаной (см. paint).
        self.smoothing_passes: int = 1
        self._smoothed_band_amp: float = 0.0
        self._smoothed_overall_amp: float = 0.0
        self.element_id: str = uuid.uuid4().hex

    def itemChange(self, change, value):
        """Обработка изменений элемента для обновления сцены"""
        # boundingRect() зависит от isSelected() (появляются handles/крутилка),
        # поэтому при изменении выделения обновляем геометрию в индексе сцены.
        if change in (
            QGraphicsItem.GraphicsItemChange.ItemSelectedChange,
            QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged,
        ):
            try:
                self.prepareGeometryChange()
            except Exception:
                pass
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Привязка к краям/центрам других объектов и рамки разрешения (Alt — без привязки).
            try:
                from PyQt6.QtGui import QGuiApplication

                from elements.snap_geometry import collect_snap_lines, snap_position_top_left

                if QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
                    return super().itemChange(change, value)
                if BaseVisualizationElement._suppress_position_snap:
                    return super().itemChange(change, value)
                if isinstance(value, QPointF) and self.scene():
                    lx, ly = collect_snap_lines(self.scene(), self)
                    snapped = snap_position_top_left(
                        value, float(self.width), float(self.height), lx, ly
                    )
                    return snapped
            except Exception:
                logger.debug("snap position skipped", exc_info=True)
            return super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Обновляем сцену при перемещении чтобы не было следов
            if self.scene():
                self.scene().update()
            fn = BaseVisualizationElement._geometry_commit_notifier
            if fn is not None:
                try:
                    fn(self)
                except Exception:
                    logger.debug("geometry commit notifier failed", exc_info=True)
            ui_fn = BaseVisualizationElement._position_ui_notifier
            if ui_fn is not None:
                try:
                    ui_fn(self)
                except Exception:
                    logger.debug("position ui notifier failed", exc_info=True)
        return super().itemChange(change, value)
        
    def boundingRect(self) -> QRectF:
        """Границы отрисовки/хиттеста.

        Важно: крутилка поворота и маркеры размера находятся *вне* (0..w, 0..h),
        поэтому при выделении расширяем прямоугольник и вверх, и по краям.
        Иначе `scene.itemAt()` не сможет найти элемент по клику на крутилку.
        """
        w = max(1.0, float(self.width))
        h = max(1.0, float(self.height))

        # Зону крутилки поворота включаем ВСЕГДА, иначе первый клик по ней не найдёт item (`scene.itemAt`).
        top_extra = float(self.rotate_handle_offset) + float(self.rotate_handle_radius) + 2.0

        if not self.isSelected():
            # Небольшой “козырёк” вверх для крутилки, остальное — только тело элемента.
            return QRectF(0.0, -top_extra, w, h + top_extra)

        pad = max(1.0, float(self.resize_handle_size) / 2.0)
        return QRectF(-pad, -pad - top_extra, w + pad * 2.0, h + pad * 2.0 + top_extra)

    def shape(self) -> QPainterPath:
        """Хиттест по расширенному boundingRect (крутилка вне тела элемента)."""
        p = QPainterPath()
        p.addRect(self.boundingRect())
        return p
    
    def paint_selection_handles(self, painter: QPainter):
        """Отрисовка handles для изменения размера"""
        try:
            if not self.isSelected():
                return
            
            rect = QRectF(0, 0, self.width, self.height)
            handle_size = self.resize_handle_size
            
            handles = [
                QRectF(rect.left() - handle_size/2, rect.top() - handle_size/2, handle_size, handle_size),  # Top-left
                QRectF(rect.right() - handle_size/2, rect.top() - handle_size/2, handle_size, handle_size),  # Top-right
                QRectF(rect.left() - handle_size/2, rect.bottom() - handle_size/2, handle_size, handle_size),  # Bottom-left
                QRectF(rect.right() - handle_size/2, rect.bottom() - handle_size/2, handle_size, handle_size),  # Bottom-right
                QRectF(rect.center().x() - handle_size/2, rect.top() - handle_size/2, handle_size, handle_size),  # Top
                QRectF(rect.center().x() - handle_size/2, rect.bottom() - handle_size/2, handle_size, handle_size),  # Bottom
                QRectF(rect.left() - handle_size/2, rect.center().y() - handle_size/2, handle_size, handle_size),  # Left
                QRectF(rect.right() - handle_size/2, rect.center().y() - handle_size/2, handle_size, handle_size),  # Right
            ]
            
            painter.setPen(QPen(QColor(100, 150, 255), 2))
            painter.setBrush(QBrush(QColor(100, 150, 255)))
            for i, handle in enumerate(handles):
                painter.drawRect(handle)

            # Handle поворота (крутилка) над верхней гранью по центру.
            cx = rect.center().x()
            cy = rect.top() - self.rotate_handle_offset
            painter.setPen(QPen(QColor(160, 200, 255), 2))
            painter.setBrush(QBrush(QColor(25, 25, 25)))
            painter.drawLine(QPointF(cx, rect.top()), QPointF(cx, cy))
            painter.setBrush(QBrush(QColor(160, 200, 255)))
            r = float(self.rotate_handle_radius)
            painter.drawEllipse(QPointF(cx, cy), r, r)
        except Exception as e:
            # Отрисовка не должна валить приложение.
            logger.error(f"Error in paint_selection_handles: {e}", exc_info=True)
            return
    
    def get_resize_handle_at(self, scene_pos: QPointF) -> Optional[str]:
        """Handle под курсором. Аргумент — координаты сцены (как от QGraphicsView)."""
        rect = QRectF(0, 0, self.width, self.height)
        handle_size = self.resize_handle_size
        m = self.resize_hit_margin
        local_pos = self.mapFromScene(scene_pos)

        handles = {
            "top-left": QRectF(rect.left() - handle_size / 2, rect.top() - handle_size / 2, handle_size, handle_size),
            "top-right": QRectF(rect.right() - handle_size / 2, rect.top() - handle_size / 2, handle_size, handle_size),
            "bottom-left": QRectF(rect.left() - handle_size / 2, rect.bottom() - handle_size / 2, handle_size, handle_size),
            "bottom-right": QRectF(rect.right() - handle_size / 2, rect.bottom() - handle_size / 2, handle_size, handle_size),
            "top": QRectF(rect.center().x() - handle_size / 2, rect.top() - handle_size / 2, handle_size, handle_size),
            "bottom": QRectF(rect.center().x() - handle_size / 2, rect.bottom() - handle_size / 2, handle_size, handle_size),
            "left": QRectF(rect.left() - handle_size / 2, rect.center().y() - handle_size / 2, handle_size, handle_size),
            "right": QRectF(rect.right() - handle_size / 2, rect.center().y() - handle_size / 2, handle_size, handle_size),
        }

        for name, handle_rect in handles.items():
            hit = handle_rect.adjusted(-m, -m, m, m)
            if hit.contains(local_pos):
                return name
        return None

    def get_rotate_handle_at(self, scene_pos: QPointF) -> bool:
        """Попадание в крутилку поворота (координаты сцены).

        Важно: не завязываемся на isSelected(), чтобы можно было “поймать” крутилку
        первым кликом (до того, как сцена применит выделение).
        """
        rect = QRectF(0, 0, self.width, self.height)
        cx = rect.center().x()
        cy = rect.top() - self.rotate_handle_offset
        local = self.mapFromScene(scene_pos)
        r = float(self.rotate_handle_radius) + float(self.resize_hit_margin)
        dx = float(local.x() - cx)
        dy = float(local.y() - cy)
        return (dx * dx + dy * dy) <= (r * r)

    def _apply_transform(self) -> None:
        """Отражение и поворот относительно центра прямоугольника элемента."""
        w = max(float(self.width), 1.0)
        h = max(float(self.height), 1.0)
        # Важно: transformOriginPoint влияет на setRotation()/setScale(), но НЕ на setTransform(QTransform).
        # Поэтому собираем матрицу вручную: перенос в центр → отражение → поворот → перенос обратно.
        cx = w / 2.0
        cy = h / 2.0
        self.setTransformOriginPoint(cx, cy)
        sx = -1.0 if self.flip_h else 1.0
        sy = -1.0 if self.flip_v else 1.0
        t = QTransform()
        t.translate(cx, cy)
        t.scale(sx, sy)
        try:
            t.rotate(float(self.rotation_deg))
        except Exception:
            t.rotate(0.0)
        t.translate(-cx, -cy)
        self.setTransform(t)

    # Backward-compat alias (старое имя использовалось по проекту)
    def _apply_flip_transform(self) -> None:
        self._apply_transform()

    def load_visualization_state(self, data: Dict[str, Any]) -> None:
        """Общие поля из JSON (частоты, амплитуда, отражение, слой). Вызывать из from_dict подклассов."""
        raw_eid = data.get("element_id")
        if isinstance(raw_eid, str) and len(raw_eid.strip()) >= 8:
            self.element_id = raw_eid.strip()
        else:
            self.element_id = uuid.uuid4().hex
        raw_fr = data.get("frequency_ranges", [])
        self.frequency_ranges = [
            (float(p[0]), float(p[1])) for p in raw_fr if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        # frequency_range_smoothing в старых проектах — игнорируем
        self.amplitude = data.get("amplitude", 1.0)
        if "smoothing_passes" in data:
            try:
                self.smoothing_passes = max(0, min(5, int(data.get("smoothing_passes", 1))))
            except (TypeError, ValueError):
                pass
        self.flip_h = data.get("flip_h", False)
        self.flip_v = data.get("flip_v", False)
        try:
            self.rotation_deg = float(data.get("rotation_deg", 0.0) or 0.0)
        except (TypeError, ValueError):
            self.rotation_deg = 0.0
        self.setZValue(float(data.get("z", 100.0)))
        self._apply_transform()

    @staticmethod
    def smoothing_passes_to_alpha(p: int) -> float:
        """Коэффициент EMA по уровню сглаживания 0…5 (как у глобального временного сглаживания)."""
        p = max(0, min(5, int(p)))
        return (1.0, 0.52, 0.38, 0.28, 0.20, 0.12)[p]

    def update_audio_data(self, audio_data: np.ndarray, fft_data: np.ndarray, frequencies: np.ndarray):
        """Обновить аудио данные для элемента.

        FFT приводим к устойчивому масштабу для отрисовки: DC/низ часто «рвут»
        шкалу и дают ложные «зашкаливающие» басы на волне/спектре.
        """
        ad = np.asarray(audio_data, dtype=float).reshape(-1)
        fd = np.asarray(fft_data, dtype=float).reshape(-1)
        fq = np.asarray(frequencies, dtype=float).reshape(-1)

        if fd.size:
            fd = np.abs(np.nan_to_num(fd, nan=0.0, posinf=0.0, neginf=0.0))
            # Убираем DC (и при желании самый низкий бин), чтобы не красить всё в «бас».
            fd[0] = 0.0
            if fd.size > 1:
                fd[1] = 0.0
            fd = np.log1p(fd)
            peak = float(np.max(fd))
            if peak > 1e-15:
                fd = fd / peak
            else:
                fd *= 0.0

        if ad.size:
            ad = np.nan_to_num(ad, nan=0.0, posinf=0.0, neginf=0.0)
            pk = float(np.max(np.abs(ad)))
            if pk > 1e-15:
                ad = ad / pk

        self.audio_data = ad
        self.fft_data = fd
        self.frequencies = fq
        # Не вызываем self.update() здесь: в Playback все элементы
        # обновляются пакетно, а перерисовку делаем один раз через scene.update().
        # Это сильно уменьшает нагрузку на UI-поток.
        rb = self._raw_amplitude_for_frequencies()
        ro = self._raw_overall_amplitude()
        a = self._temporal_smooth_alpha()
        self._smoothed_band_amp += a * (rb - self._smoothed_band_amp)
        self._smoothed_overall_amp += a * (ro - self._smoothed_overall_amp)

    def _temporal_smooth_alpha(self) -> float:
        """Глобальное сглаживание для get_overall_amplitude (и запасной режим)."""
        return BaseVisualizationElement.smoothing_passes_to_alpha(int(getattr(self, "smoothing_passes", 1)))

    def _raw_amplitude_for_frequencies(self) -> float:
        """Мгновенное значение по выбранным полосам (EMA применяется в update_audio_data)."""
        if len(self.frequency_ranges) == 0:
            return 0.0
        fft = np.asarray(self.fft_data, dtype=float).reshape(-1)
        freq_axis = np.asarray(self.frequencies, dtype=float).reshape(-1)
        n = min(fft.size, freq_axis.size)
        if n == 0:
            return 0.0
        fft = fft[:n]
        freq_axis = freq_axis[:n]

        total_amplitude = 0.0
        for freq_min, freq_max in self.frequency_ranges:
            try:
                lo = float(freq_min)
                hi = float(freq_max)
            except (TypeError, ValueError):
                continue
            if lo > hi:
                lo, hi = hi, lo
            mask = (freq_axis >= lo) & (freq_axis <= hi)
            if np.any(mask):
                chunk = np.nan_to_num(fft[mask], nan=0.0, posinf=0.0, neginf=0.0)
                total_amplitude += float(np.mean(chunk))

        raw = (total_amplitude / float(len(self.frequency_ranges))) * float(self.amplitude)
        return float(np.clip(raw, 0.0, 3.0))

    def _raw_overall_amplitude(self) -> float:
        if len(self.fft_data) == 0:
            return 0.0
        arr = np.nan_to_num(
            np.asarray(self.fft_data, dtype=float).reshape(-1),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        if arr.size == 0:
            return 0.0
        raw = float(np.mean(arr)) * float(self.amplitude)
        return float(np.clip(raw, 0.0, 3.0))

    def get_amplitude_for_frequencies(self) -> float:
        """Сглаженная амплитуда по выбранным частотам (обновляется в update_audio_data)."""
        if len(self.frequency_ranges) == 0:
            return 0.0
        return float(self._smoothed_band_amp)

    def get_overall_amplitude(self) -> float:
        """Сглаженная амплитуда по всему FFT (без частотных фильтров)."""
        return float(self._smoothed_overall_amp)
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            "type": self.__class__.__name__,
            "element_id": getattr(self, "element_id", "") or uuid.uuid4().hex,
            "x": self.x(),
            "y": self.y(),
            "width": self.width,
            "height": self.height,
            "z": self.zValue(),
            "frequency_ranges": self.frequency_ranges,
            "amplitude": self.amplitude,
            "smoothing_passes": max(0, min(5, int(getattr(self, "smoothing_passes", 1)))),
            "flip_h": self.flip_h,
            "flip_v": self.flip_v,
            "rotation_deg": self.rotation_deg,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseVisualizationElement':
        """Десериализация из словаря"""
        element = cls(data["x"], data["y"], data["width"], data["height"])
        element.load_visualization_state(data)
        return element
