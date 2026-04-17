"""
Элемент текста с анимациями
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from typing import Dict, Any
import numpy as np

from app.anim_clock import animation_time
from .base_element import BaseVisualizationElement
from PyQt6.QtWidgets import QGraphicsItem


class TextElement(BaseVisualizationElement):
    """Элемент текста с анимациями"""
    
    def __init__(self, x: float = 0, y: float = 0, width: float = 200, height: float = 50,
                 text: str | None = None):
        from app.i18n import tr

        super().__init__(x, y, width, height)
        self.text = text if text is not None else tr("props.text.default_body")
        self.font = QFont("Arial", 24)
        self.color = QColor(255, 255, 255)
        self.animation_type = "pulse"  # pulse, wave, bounce, glow
        self.base_font_size = 24
        # В редакторе анимации не “играют” постоянно — только как превью в UI.
        self._ui_anim_preview = False

    def set_ui_anim_preview(self, enabled: bool) -> None:
        self._ui_anim_preview = bool(enabled)
        try:
            self.update()
        except Exception:
            pass
    
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base_amp = self.get_amplitude_for_frequencies() if self.frequency_ranges else 0.0
        # Превью в комбобоксе: можно показать реакцию на сигнал даже без частот.
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
        
        offset_y = 0.0
        pulse_scale = 1.0
        text_color = self.color
        
        if self.animation_type == "pulse":
            if allow_anim:
                pulse_scale = 1.0 + amplitude * 0.35
        elif self.animation_type == "wave":
            if allow_anim:
                offset_y = float(np.sin(animation_time() * 2 + amplitude * 10) * amplitude * 20)
        elif self.animation_type == "bounce":
            if allow_anim:
                offset_y = float(-abs(np.sin(animation_time() * 3)) * amplitude * 30)
        elif self.animation_type == "glow":
            if allow_anim:
                glow_intensity = int(amplitude * 255)
                text_color = QColor(
                    min(255, self.color.red() + glow_intensity),
                    min(255, self.color.green() + glow_intensity),
                    min(255, self.color.blue() + glow_intensity),
                )
        
        font = QFont(self.font)
        font.setPointSizeF(self.base_font_size)
        painter.setFont(font)
        painter.setPen(QPen(text_color))
        
        rect = QRectF(0, 0, self.width, self.height)

        if self.animation_type == "pulse" and pulse_scale != 1.0:
            painter.save()
            try:
                painter.translate(self.width / 2, self.height / 2)
                painter.scale(pulse_scale, pulse_scale)
                painter.translate(-self.width / 2, -self.height / 2)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
            finally:
                painter.restore()
        elif offset_y != 0:
            painter.save()
            try:
                painter.translate(0, offset_y)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
            finally:
                painter.restore()
        else:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
        
        # Отрисовка handles
        if self.isSelected():
            self.paint_selection_handles(painter)
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["text"] = self.text
        data["font_size"] = self.base_font_size
        data["color"] = [self.color.red(), self.color.green(), self.color.blue()]
        data["animation_type"] = self.animation_type
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TextElement':
        element = cls(
            data["x"],
            data["y"],
            data["width"],
            data["height"],
            data.get("text"),
        )
        element.load_visualization_state(data)
        element.base_font_size = data.get("font_size", 24)
        element.font.setPointSize(element.base_font_size)
        if "color" in data:
            element.color = QColor(*data["color"])
        element.animation_type = data.get("animation_type", "pulse")
        return element
