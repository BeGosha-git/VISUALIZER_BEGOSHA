"""
Элемент картинки с анимацией по частотам
"""
from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QImageReader, QPainter, QPen, QBrush, QColor, QPixmap
from PyQt6.QtWidgets import QGraphicsItem
from typing import Optional, Dict, Any
import os
import logging

from .base_element import BaseVisualizationElement

logger = logging.getLogger(__name__)

# Ограничение длинной стороны текстуры: полный декод 20–40 Мп в QPixmap блокирует UI.
_MAX_PIXMAP_EDGE = 4096


class ImageElement(BaseVisualizationElement):
    """Элемент картинки с анимацией по частотам"""
    
    def __init__(self, x: float = 0, y: float = 0, width: float = 100, height: float = 100, 
                 image_path: str = ""):
        super().__init__(x, y, width, height)
        self.image_path = image_path
        self.pixmap: Optional[QPixmap] = None
        self.movement_type = "vertical"  # vertical, horizontal, scale, rotate
        self.base_x = x
        self.base_y = y
        self.base_width = width
        self.base_height = height
        self.rotation = 0.0
        
        if image_path and os.path.exists(image_path):
            self.load_image(image_path)
    
    def load_image(self, path: str):
        """Загрузить изображение.

        Полный декод гигантского файла в `QPixmap(path)` блокирует UI; читаем через
        QImageReader с уменьшением по длинной стороне до `_MAX_PIXMAP_EDGE`, затем
        масштаб до рамки элемента по-прежнему в paint() через drawPixmap.
        """
        self.image_path = path
        pm: Optional[QPixmap] = None
        try:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            if reader.canRead():
                sz = reader.size()
                if sz.isValid() and sz.width() > 0 and sz.height() > 0:
                    w0, h0 = sz.width(), sz.height()
                    m = max(w0, h0)
                    if m > _MAX_PIXMAP_EDGE:
                        scale = _MAX_PIXMAP_EDGE / float(m)
                        nw = max(1, int(round(w0 * scale)))
                        nh = max(1, int(round(h0 * scale)))
                        reader.setScaledSize(QSize(nw, nh))
                img = reader.read()
                if not img.isNull():
                    pm = QPixmap.fromImage(img)
        except MemoryError:
            logger.warning("ImageElement: not enough memory for scaled read: %s", path)
            pm = None
        except Exception:
            logger.debug("ImageElement scaled read failed, fallback to QPixmap", exc_info=True)
        if pm is None or pm.isNull():
            try:
                pm = QPixmap(path)
            except MemoryError:
                logger.warning("ImageElement: not enough memory for QPixmap fallback: %s", path)
                pm = None
        self.pixmap = None if (pm is None or pm.isNull()) else pm
    
    def paint(self, painter: QPainter, option, widget=None):
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            
            if not self.pixmap or self.pixmap.isNull():
                # Убеждаемся что размеры больше 0
                w = max(100.0, self.width)
                h = max(100.0, self.height)
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

                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("canvas.image"))
                
                # Handles
                if self.isSelected():
                    self.paint_selection_handles(painter)
                return
            
            # Получаем амплитуду
            amplitude = self.get_amplitude_for_frequencies()
            
            # Вычисляем трансформации без изменения painter
            offset_x = 0
            offset_y = 0
            scale_x = 1.0
            scale_y = 1.0
            rotation = 0
            
            if self.movement_type == "vertical":
                offset_y = amplitude * 50
            elif self.movement_type == "horizontal":
                offset_x = amplitude * 50
            elif self.movement_type == "scale":
                scale_x = scale_y = 1.0 + amplitude * 0.5
            elif self.movement_type == "rotate":
                rotation = amplitude * 360
            
            # Целевой прямоугольник для масштабирования (Qt рендерит через GPU)
            target_rect = QRectF(0, 0, self.width, self.height)
            src_rect = QRectF(self.pixmap.rect())

            if rotation != 0 or scale_x != 1.0 or scale_y != 1.0 or offset_x != 0 or offset_y != 0:
                painter.save()
                try:
                    if self.movement_type == "scale":
                        # Масштаб относительно центра рамки элемента
                        painter.translate(self.width / 2, self.height / 2)
                        painter.scale(scale_x, scale_y)
                        painter.translate(-self.width / 2, -self.height / 2)
                    elif self.movement_type == "rotate":
                        painter.translate(self.width / 2, self.height / 2)
                        painter.rotate(rotation)
                        painter.translate(-self.width / 2, -self.height / 2)
                    else:
                        painter.translate(offset_x, offset_y)
                    painter.drawPixmap(target_rect, self.pixmap, src_rect)
                finally:
                    painter.restore()
            else:
                painter.drawPixmap(target_rect, self.pixmap, src_rect)
            
            # Отрисовка handles
            if self.isSelected():
                self.paint_selection_handles(painter)
        except Exception as e:
            logger.error(f"Error in ImageElement.paint: {e}", exc_info=True)
            return
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["image_path"] = self.image_path
        data["movement_type"] = self.movement_type
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImageElement':
        element = cls(data["x"], data["y"], data["width"], data["height"], 
                     data.get("image_path", ""))
        element.load_visualization_state(data)
        element.movement_type = data.get("movement_type", "vertical")
        return element
