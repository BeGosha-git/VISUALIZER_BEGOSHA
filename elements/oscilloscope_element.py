"""
Элемент осцилографа (волна без сглаживания)
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
import logging

from .wave_element import WaveElement, _catmull_path

logger = logging.getLogger(__name__)


class OscilloscopeElement(WaveElement):
    """Элемент осцилографа (волна без сглаживания)"""

    def __init__(self, x: float = 0, y: float = 0, width: float = 400, height: float = 200):
        super().__init__(x, y, width, height)
        self.smoothing_passes = 0
        self.color = QColor(0, 255, 100)
        self._osc_hist: Deque[Tuple[float, np.ndarray]] = deque(maxlen=96)

    def update_audio_data(self, audio_data: np.ndarray, fft_data: np.ndarray, frequencies: np.ndarray) -> None:
        super().update_audio_data(audio_data, fft_data, frequencies)
        ad = np.asarray(self.audio_data, dtype=float).reshape(-1)
        if ad.size:
            step = max(1, ad.size // 160)
            slim = ad[::step].astype(np.float32, copy=True)
            self._osc_hist.append((time.monotonic(), slim))

    def paint(self, painter: QPainter, option, widget=None):
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Placeholder если нет данных
            if len(self.audio_data) == 0:
                rect = QRectF(0, 0, self.width, self.height)

                # Рамка
                painter.setPen(QPen(QColor(200, 200, 200), 3, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(QColor(40, 40, 40, 150)))
                painter.drawRect(rect)

                # Текст
                painter.setPen(QPen(QColor(220, 220, 220)))
                font = painter.font()
                font.setPointSize(14)
                font.setBold(True)
                painter.setFont(font)
                from app.i18n import tr

                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("canvas.osc"))

                # Handles
                if self.isSelected():
                    self.paint_selection_handles(painter)
                return

            amplitude_factor = self.get_amplitude_for_frequencies()
            gain = float(amplitude_factor) * 0.42

            decay_ms = float(getattr(self, "visual_decay_ms", 0.0) or 0.0)
            now = time.monotonic()
            window_s = (decay_ms / 1000.0) if decay_ms >= 100.0 else 0.0
            painter.setPen(QPen(self.color, self.line_width))

            def _points_from_slim(slim: np.ndarray) -> List[QPointF]:
                n = int(slim.size)
                if n <= 0:
                    return []
                pts: List[QPointF] = []
                num_points = min(n, int(self.width))
                step = max(1, n // max(1, num_points))
                for i in range(num_points):
                    idx = i * step
                    if idx >= n:
                        break
                    x = (i / max(1, num_points - 1)) * self.width if num_points > 1 else 0.0
                    v = float(slim[idx])
                    y = self.height / 2 - (v * self.height / 2 * gain)
                    y = max(1.0, min(float(self.height) - 1.0, y))
                    pts.append(QPointF(x, y))
                return pts

            if window_s > 0.0 and self._osc_hist:
                hist_list = list(self._osc_hist)
                # Последний снимок — тем же буфером рисуем ярко ниже, без двойной линии.
                trail_src = hist_list[:-1] if len(hist_list) > 1 else []
                for t_mono, slim in trail_src:
                    age = now - t_mono
                    if age > window_s * 1.05:
                        continue
                    # старые — слабее
                    u = 1.0 - min(1.0, age / window_s)
                    a = int(35 + 220 * (u * u))
                    c = QColor(self.color)
                    c.setAlpha(max(0, min(255, a)))
                    painter.setPen(QPen(c, max(0.5, self.line_width * (0.35 + 0.65 * u))))
                    pts = _points_from_slim(slim)
                    if len(pts) > 1:
                        form = max(0, min(8, int(getattr(self, "display_form", 0))))
                        passes = max(0, min(5, int(getattr(self, "smoothing_passes", 0))))
                        if passes > 0 and len(pts) > 3:
                            for _ in range(passes):
                                if len(pts) < 3:
                                    break
                                pts = self._smooth_points(pts)
                        if form <= 4:
                            painter.drawPolyline(QPolygonF(pts))
                        else:
                            painter.drawPath(_catmull_path(pts))
                painter.setPen(QPen(self.color, self.line_width))

            ad = np.asarray(self.audio_data, dtype=float).reshape(-1)
            num_points = min(len(ad), int(self.width))
            step = max(1, len(ad) // max(1, num_points))
            points: List[QPointF] = []
            for i in range(num_points):
                idx = i * step
                if idx < len(ad):
                    x = (i / max(1, num_points - 1)) * self.width if num_points > 1 else 0.0
                    v = float(ad[idx])
                    y = self.height / 2 - (v * self.height / 2 * gain)
                    y = max(1.0, min(float(self.height) - 1.0, y))
                    points.append(QPointF(x, y))

            if len(points) > 1:
                passes = max(0, min(5, int(getattr(self, "smoothing_passes", 0))))
                pts = points
                if passes > 0:
                    for _ in range(passes):
                        if len(pts) < 3:
                            break
                        pts = self._smooth_points(pts)
                form = max(0, min(8, int(getattr(self, "display_form", 0))))
                if form <= 4:
                    painter.drawPolyline(QPolygonF(pts))
                else:
                    painter.drawPath(_catmull_path(pts))

            # Отрисовка handles при выделении
            if self.isSelected():
                self.paint_selection_handles(painter)
        except Exception as e:
            logger.error(f"Error in OscilloscopeElement.paint: {e}", exc_info=True)
            return

    def to_dict(self) -> Dict[str, Any]:
        return super().to_dict()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OscilloscopeElement":
        element = cls(data["x"], data["y"], data["width"], data["height"])
        element.load_visualization_state(data)
        if "color" in data:
            element.color = QColor(*data["color"])
        element.line_width = data.get("line_width", 3.0)
        element.smoothing_passes = max(0, min(5, int(data.get("smoothing_passes", 0))))
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
        try:
            element.spectrum_step_gap = max(0.0, min(0.95, float(data.get("spectrum_step_gap", 0.0))))
        except (TypeError, ValueError):
            element.spectrum_step_gap = 0.0
        return element
