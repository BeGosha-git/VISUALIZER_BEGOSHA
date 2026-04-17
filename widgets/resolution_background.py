"""
Элемент фона разрешения экрана
"""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor
from PyQt6.QtWidgets import QGraphicsItem


class ResolutionBackground(QGraphicsItem):
    """Чёрный прямоугольник, обозначающий разрешение экрана"""
    
    def __init__(self, width: float = 1920, height: float = 1080, x: float = 0, y: float = 0):
        super().__init__()
        self.setPos(x, y)
        self.width = width
        self.height = height
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, False)
        self.setZValue(-1000)  # Всегда на заднем плане
    
    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.width, self.height)
    
    def paint(self, painter: QPainter, option, widget=None):
        # Чёрный фон
        painter.setBrush(QBrush(QColor(0, 0, 0)))
        painter.setPen(QPen(QColor(50, 50, 50), 2))
        painter.drawRect(0, 0, self.width, self.height)
        
        # Белая рамка для видимости
        painter.setPen(QPen(QColor(100, 100, 100), 1, Qt.PenStyle.DashLine))
        painter.drawRect(0, 0, self.width, self.height)
        
        # Текст с разрешением
        painter.setPen(QPen(QColor(150, 150, 150)))
        font = painter.font()
        font.setPointSize(12)
        painter.setFont(font)
        text = f"{int(self.width)}×{int(self.height)}"
        painter.drawText(10, 25, text)
    
    def set_size(self, width: float, height: float):
        """Установить размер"""
        self.width = width
        self.height = height
        self.update()
