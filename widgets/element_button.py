"""
Кнопка элемента для матрицы
"""
from PyQt6.QtCore import Qt, QMimeData, QPoint
from PyQt6.QtGui import QPainter, QColor, QFont, QDrag, QPixmap
from PyQt6.QtWidgets import QPushButton, QApplication

from app.theme_qss import theme_corner_radius_css
from config.app_settings import settings


class ElementButton(QPushButton):
    """Кнопка элемента с иконкой для drag & drop"""

    def __init__(
        self,
        name: str,
        icon_text: str,
        element_type: str,
        parent=None,
        cell_side: int | None = None,
    ):
        super().__init__(parent)
        self.element_type = element_type
        self.icon_text = icon_text
        self.name = name
        side = 72 if cell_side is None else int(cell_side)
        side = max(48, min(92, side))
        self.setFixedSize(side, side)
        self.setText(f"{icon_text}\n{name}")
        self._font_pt = 10 if side < 68 else 11
        self.refresh_theme_style()

    def refresh_theme_style(self) -> None:
        fs = self._font_pt
        r = theme_corner_radius_css()
        if settings.ui_theme() == "glass":
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: rgba(255, 255, 255, 0.16);
                    border: 2px solid rgba(255, 255, 255, 0.9);
                    border-radius: {r};
                    color: #e8e8e8;
                    font-size: {fs}px;
                    text-align: center;
                    padding: 2px 2px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.22);
                    border: 2px solid rgba(255, 255, 255, 0.95);
                    color: #f5f5f5;
                }}
                QPushButton:pressed {{
                    background-color: rgba(255, 255, 255, 0.10);
                }}
            """
            )
        else:
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: #1c1f26;
                    border: 1px solid #3a4558;
                    border-radius: {r};
                    color: #c8c8c8;
                    font-size: {fs}px;
                    text-align: center;
                    padding: 2px 2px;
                }}
                QPushButton:hover {{
                    background-color: #242830;
                    border: 1px solid #4a5a70;
                    color: #d8d8d8;
                }}
                QPushButton:pressed {{
                    background-color: #14161c;
                    border: 1px solid #353d4c;
                }}
            """
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return

        if (
            event.position().toPoint() - self.drag_start_position
        ).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(self.element_type)
        drag.setMimeData(mime_data)

        # Создаём простую иконку для перетаскивания
        pixmap = QPixmap(60, 60)
        pixmap.fill(QColor(30, 30, 30))
        painter = QPainter(pixmap)
        painter.setPen(QColor(150, 150, 150))
        font = QFont()
        font.setPointSize(20)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, self.icon_text)
        painter.end()

        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(30, 30))
        drag.exec(Qt.DropAction.CopyAction)
