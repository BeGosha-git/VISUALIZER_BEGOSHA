"""
Элемент красивой волны
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
import logging

from .base_element import BaseVisualizationElement

logger = logging.getLogger(__name__)


def _catmull_path(points: List[QPointF]) -> QPainterPath:
    """Открытая кривая через точки (Catmull-Rom → кубические Безье)."""
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    if n == 1:
        path.moveTo(points[0])
        return path
    path.moveTo(points[0])
    if n == 2:
        path.lineTo(points[1])
        return path
    for i in range(0, n - 1):
        p0 = points[max(0, i - 1)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(n - 1, i + 2)]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0, p1.y() + (p2.y() - p0.y()) / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0, p2.y() - (p3.y() - p1.y()) / 6.0)
        path.cubicTo(c1, c2, p2)
    return path


class WaveElement(BaseVisualizationElement):
    """Элемент красивой волны"""

    def __init__(self, x: float = 0, y: float = 0, width: float = 400, height: float = 200):
        super().__init__(x, y, width, height)
        self.color = QColor(100, 150, 255)
        self.line_width = 3.0
        # smoothing_passes — в базовом классе: временная амплитуда + проходы Чайкина (см. paint).
        self.wave_points: List[QPointF] = []
        # 0 — острая ломаная … 8 — плавная «окружность» (кривая Безье).
        self.display_form: int = 0
        # Сколько столбцов/точек по ширине (объединение соседних частотных бинов): 1…256.
        self.spectrum_bar_count: int = 128
        # 0 — без следа; иначе время затухания «фосфора» в мс (100…2000).
        self.visual_decay_ms: float = 0.0
        self._spectrum_hold: np.ndarray | None = None
        self._last_audio_mono: float = 0.0
        self._form_dt: float = 0.02

    def update_audio_data(self, audio_data: np.ndarray, fft_data: np.ndarray, frequencies: np.ndarray) -> None:
        now = time.monotonic()
        if self._last_audio_mono > 0.0:
            self._form_dt = max(1.0 / 500.0, min(0.25, now - self._last_audio_mono))
        self._last_audio_mono = now
        super().update_audio_data(audio_data, fft_data, frequencies)

    def paint(self, painter: QPainter, option, widget=None):
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Placeholder если нет данных
            if len(self.fft_data) == 0:
                # Убеждаемся что размеры больше 0
                w = max(100.0, self.width)
                h = max(50.0, self.height)
                rect = QRectF(0, 0, w, h)

                # Рамка
                painter.setPen(QPen(QColor(200, 200, 200), 3, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(QColor(40, 40, 40, 200)))  # Более непрозрачный для видимости
                painter.drawRect(rect)

                # Текст
                painter.setPen(QPen(QColor(255, 255, 255)))  # Белый текст для лучшей видимости
                font = painter.font()
                font.setPointSize(16)
                font.setBold(True)
                painter.setFont(font)
                from app.i18n import tr

                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("canvas.wave"))

                # Handles
                if self.isSelected():
                    self.paint_selection_handles(painter)
                return

            painter.setPen(QPen(self.color, self.line_width))

            # Без выбранных диапазонов частот не «оживляем» волну от общего FFT —
            # иначе демо/фоновый сигнал даёт ложное движение при настройке.
            amplitude_factor = self.get_amplitude_for_frequencies()

            fd = np.asarray(self.fft_data, dtype=float).reshape(-1)
            m = int(fd.size)
            if m <= 0:
                return

            n_bars = max(1, min(256, int(getattr(self, "spectrum_bar_count", 128) or 128)))
            vals = np.zeros(n_bars, dtype=float)
            for i in range(n_bars):
                a = int(i * m / n_bars)
                b = int((i + 1) * m / n_bars)
                b = max(b, a + 1)
                vals[i] = float(np.mean(fd[a:b]))

            decay_ms = float(getattr(self, "visual_decay_ms", 0.0) or 0.0)
            if decay_ms >= 100.0:
                dt = float(getattr(self, "_form_dt", 0.02))
                dec = math.exp(-dt / (decay_ms / 1000.0))
                if self._spectrum_hold is None or int(self._spectrum_hold.size) != n_bars:
                    self._spectrum_hold = vals.copy()
                else:
                    self._spectrum_hold = np.maximum(vals, self._spectrum_hold * dec)
                plot_vals = self._spectrum_hold
            else:
                self._spectrum_hold = None
                plot_vals = vals

            form = max(0, min(8, int(getattr(self, "display_form", 0))))
            if form > 0:
                k = 1 + 2 * min(8, form)
                wv = np.hanning(k)
                wv = wv / float(np.sum(wv))
                plot_vals = np.convolve(plot_vals, wv, mode="same")

            num_points = int(plot_vals.size)
            points: List[QPointF] = []
            for i in range(num_points):
                if num_points > 1:
                    x = (i / (num_points - 1)) * self.width
                else:
                    x = self.width * 0.5
                v = float(plot_vals[i])
                y = self.height / 2 - (v * self.height / 2 * amplitude_factor)
                y = max(1.0, min(float(self.height) - 1.0, y))
                points.append(QPointF(x, y))

            if len(points) > 1:
                passes = max(0, min(5, int(getattr(self, "smoothing_passes", 0))))
                if passes > 0 and len(points) > 3:
                    for _ in range(passes):
                        if len(points) < 3:
                            break
                        points = self._smooth_points(points)

                if form <= 4:
                    painter.drawPolyline(QPolygonF(points))
                else:
                    painter.drawPath(_catmull_path(points))

            # Отрисовка handles при выделении
            if self.isSelected():
                self.paint_selection_handles(painter)
        except Exception as e:
            logger.error(f"Error in WaveElement.paint: {e}", exc_info=True)
            return

    def _smooth_points(self, points: List[QPointF]) -> List[QPointF]:
        """Сглаживание алгоритмом Чайкина — без scipy, быстро и стабильно."""
        if len(points) < 3:
            return points
        new_pts: List[QPointF] = [points[0]]
        for i in range(len(points) - 1):
            p0 = points[i]
            p1 = points[i + 1]
            new_pts.append(QPointF(0.75 * p0.x() + 0.25 * p1.x(), 0.75 * p0.y() + 0.25 * p1.y()))
            new_pts.append(QPointF(0.25 * p0.x() + 0.75 * p1.x(), 0.25 * p0.y() + 0.75 * p1.y()))
        new_pts.append(points[-1])
        return new_pts

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["color"] = [self.color.red(), self.color.green(), self.color.blue()]
        data["line_width"] = self.line_width
        data["display_form"] = int(getattr(self, "display_form", 0))
        data["spectrum_bar_count"] = int(getattr(self, "spectrum_bar_count", 128))
        data["visual_decay_ms"] = float(getattr(self, "visual_decay_ms", 0.0))
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WaveElement":
        element = cls(data["x"], data["y"], data["width"], data["height"])
        element.load_visualization_state(data)
        if "color" in data:
            element.color = QColor(*data["color"])
        element.line_width = data.get("line_width", 3.0)
        if "smoothing_passes" in data:
            element.smoothing_passes = max(0, min(5, int(data.get("smoothing_passes", 0))))
        else:
            element.smoothing_passes = 1 if bool(data.get("smoothing", True)) else 0
        try:
            element.display_form = max(0, min(8, int(data.get("display_form", 0))))
        except (TypeError, ValueError):
            element.display_form = 0
        try:
            element.spectrum_bar_count = max(1, min(256, int(data.get("spectrum_bar_count", 128))))
        except (TypeError, ValueError):
            element.spectrum_bar_count = 128
        try:
            element.visual_decay_ms = max(0.0, min(5000.0, float(data.get("visual_decay_ms", 0.0))))
        except (TypeError, ValueError):
            element.visual_decay_ms = 0.0
        return element
