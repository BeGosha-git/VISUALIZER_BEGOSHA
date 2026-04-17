"""
Элемент линии, нарисованной пользователем
"""
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QPolygonF
from typing import List, Dict, Any
import numpy as np

from .base_element import BaseVisualizationElement
from PyQt6.QtWidgets import QGraphicsItem


class LineElement(BaseVisualizationElement):
    """Элемент линии, нарисованной пользователем"""
    
    def __init__(self, x: float = 0, y: float = 0):
        super().__init__(x, y, 0, 0)
        self.points: List[QPointF] = []
        self.smoothed_points: List[QPointF] = []
        self.color = QColor(200, 200, 200)  # Светлее для видимости на чёрном
        self.line_width = 5.0  # Увеличено по умолчанию
        self.animation_type = "wave"  # wave, pulse, glow
        # smoothing_passes — в базовом классе (время + Чайкин для линии).
        # В редакторе анимации не “играют” постоянно — только как превью в UI.
        self._ui_anim_preview = False

    def set_ui_anim_preview(self, enabled: bool) -> None:
        self._ui_anim_preview = bool(enabled)
        try:
            self.update()
        except Exception:
            pass
    
    def _bbox_union_points(self) -> List[QPointF]:
        """Объединение сырых и сглаженных точек — Chaikin может чуть выступать за исходный bbox."""
        out: List[QPointF] = list(self.points)
        if len(self.smoothed_points) >= 2:
            out.extend(self.smoothed_points)
        return out

    def _normalize_origin_to_min_corner(self) -> None:
        """Минимум bbox в (0,0): рамка выделения и width/height совпадают с линией (в т.ч. влево/вверх от старта)."""
        for _ in range(5):
            pts = self._bbox_union_points()
            if not pts:
                return
            min_x = min(p.x() for p in pts)
            min_y = min(p.y() for p in pts)
            if min_x >= -1e-6 and min_y >= -1e-6:
                break
            dx, dy = min_x, min_y
            try:
                self.prepareGeometryChange()
            except Exception:
                pass
            self.points = [QPointF(p.x() - dx, p.y() - dy) for p in self.points]
            if self.smoothed_points:
                self.smoothed_points = [QPointF(p.x() - dx, p.y() - dy) for p in self.smoothed_points]
            try:
                pos = self.pos()
                self.setPos(pos.x() + dx, pos.y() + dy)
            except Exception:
                pass

    def _sync_size_from_points(self) -> None:
        """Размеры и нормализация локальных координат под рамку (0,0)–(w,h)."""
        if not self.points:
            self.width = 0.0
            self.height = 0.0
            return
        self._normalize_origin_to_min_corner()
        src = self.smoothed_points if len(self.smoothed_points) >= 2 else self.points
        if not src:
            self.width = 0.0
            self.height = 0.0
            return
        xs = [p.x() for p in src]
        ys = [p.y() for p in src]
        self.width = float(max(xs) - min(xs)) if xs else 0.0
        self.height = float(max(ys) - min(ys)) if ys else 0.0

    def add_point(self, point: QPointF):
        """Добавить точку к линии (в локальных координатах)"""
        self.points.append(point)
        # Пересчёт не на каждую точку — иначе при длинном штрихе UI подвисает.
        if len(self.points) % 6 == 0 or len(self.points) < 4:
            self._rebuild_smoothed()

        self._sync_size_from_points()

    @staticmethod
    def _chaikin_one_pass(pts: List[QPointF]) -> List[QPointF]:
        """Один проход Чайкина (как в WaveElement._smooth_points)."""
        if len(pts) < 2:
            return pts.copy()
        new_pts: List[QPointF] = [pts[0]]
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            new_pts.append(
                QPointF(0.75 * p0.x() + 0.25 * p1.x(), 0.75 * p0.y() + 0.25 * p1.y())
            )
            new_pts.append(
                QPointF(0.25 * p0.x() + 0.75 * p1.x(), 0.25 * p0.y() + 0.75 * p1.y())
            )
        new_pts.append(pts[-1])
        return new_pts

    def _rebuild_smoothed(self) -> None:
        """Пересобрать smoothed_points из points по smoothing_passes."""
        pts = list(self.points)
        passes = max(0, min(5, int(getattr(self, "smoothing_passes", 0))))
        if passes == 0 or len(pts) < 3:
            self.smoothed_points = pts.copy()
            return
        cur = pts
        max_pts = 2000
        for _ in range(passes):
            if len(cur) < 3:
                break
            nxt = self._chaikin_one_pass(cur)
            if len(nxt) > max_pts:
                break
            cur = nxt
        self.smoothed_points = cur

    def finish_drawing(self):
        """Завершить рисование и применить сглаживание"""
        self._rebuild_smoothed()
        self._sync_size_from_points()
    
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base_amp = self.get_amplitude_for_frequencies() if self.frequency_ranges else 0.0
        amplitude = (
            base_amp
            if self.frequency_ranges
            else (self.get_overall_amplitude() if self._ui_anim_preview else 0.0)
        )

        # В Playback элементы не movable/selectable; там анимацию играем всегда.
        # В редакторе — только когда пользователь “превьюит” в комбобоксе.
        try:
            in_editor = bool(self.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        except Exception:
            in_editor = True
        allow_anim = (not in_editor) or self._ui_anim_preview
        
        points_to_draw = self.smoothed_points if self.smoothed_points else self.points
        if len(points_to_draw) < 2:
            if self.isSelected():
                self.paint_selection_handles(painter)
            return
        
        # Вычисляем параметры без изменения painter
        line_color = self.color
        line_width = self.line_width
        
        if self.animation_type == "wave":
            if allow_anim:
                # Волнообразное движение линии
                animated_points = []
                for point in points_to_draw:
                    offset = np.sin(point.x() * 0.1 + amplitude * 10) * amplitude * 20
                    animated_points.append(QPointF(point.x(), point.y() + offset))
                points_to_draw = animated_points
        elif self.animation_type == "pulse":
            if allow_anim:
                line_width = self.line_width * (1.0 + amplitude * 0.5)
        elif self.animation_type == "glow":
            if allow_anim:
                glow_intensity = int(amplitude * 100)
                line_color = QColor(
                    min(255, self.color.red() + glow_intensity),
                    min(255, self.color.green() + glow_intensity),
                    min(255, self.color.blue() + glow_intensity),
                )
        
        # Применяем настройки
        painter.setPen(QPen(line_color, line_width))
        
        # Рисуем линию (список QPointF → QPolygonF; splat в drawPolyline даёт неопределённое поведение)
        painter.drawPolyline(QPolygonF(points_to_draw))
        
        # Отрисовка handles
        if self.isSelected():
            self.paint_selection_handles(painter)
    
    def boundingRect(self) -> QRectF:
        src = self.smoothed_points if len(self.smoothed_points) >= 2 else self.points
        if not src:
            return QRectF(0, 0, 0, 0)
        xs = [p.x() for p in src]
        ys = [p.y() for p in src]
        r = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        m = max(2.0, float(self.line_width) * 0.5 + 2.0)
        return r.adjusted(-m, -m, m, m)
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["points"] = [[p.x(), p.y()] for p in self.points]
        data["color"] = [self.color.red(), self.color.green(), self.color.blue()]
        data["line_width"] = self.line_width
        data["animation_type"] = self.animation_type
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LineElement':
        element = cls(data["x"], data["y"])
        if "points" in data:
            element.points = [QPointF(p[0], p[1]) for p in data["points"]]
        element.load_visualization_state(data)
        if "color" in data:
            element.color = QColor(*data["color"])
        element.line_width = data.get("line_width", 3.0)
        element.animation_type = data.get("animation_type", "wave")
        element.smoothing_passes = max(0, min(5, int(data.get("smoothing_passes", 1))))
        if element.points:
            element._rebuild_smoothed()
            element._sync_size_from_points()
        return element
