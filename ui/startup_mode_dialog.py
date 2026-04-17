"""
Стартовый выбор режима: две квадратные кнопки с ч/б иконками и крестик в углу.
Перетаскивание окна — за верхнюю «рамку» (полоска над кнопками).
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.theme_qss import theme_corner_radius_css
from config.app_settings import settings


def _mode_icon(kind: str) -> QIcon:
    """Простые монохромные иконки (без внешних ресурсов)."""
    s = 56
    pm = QPixmap(s, s)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(245, 245, 245))
    pen.setWidth(3)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "editor":
        p.drawRect(12, 12, 32, 34)
        p.drawLine(16, 40, 44, 18)
    else:
        tri = QPolygonF(
            [
                QPointF(14, 10),
                QPointF(14, 46),
                QPointF(48, 28),
            ]
        )
        p.drawPolygon(tri)
    p.end()
    return QIcon(pm)


class _FrameDragStrip(QWidget):
    """Зона «рамки» для перетаскивания безрамочного диалога."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__()
        self._d = dialog
        self._anchor: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._anchor = event.globalPosition().toPoint() - self._d.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._d.move(event.globalPosition().toPoint() - self._anchor)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._anchor = None
        super().mouseReleaseEvent(event)


class StartupModeDialog(QDialog):
    """Минимальное окно: полоска-рамка для перетаскивания, ✕, две квадратные кнопки."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(tr("startup.title"))
        self.setModal(True)
        self._mode: str = "editor"
        self._build_ui()

    def selected_mode(self) -> str:
        return self._mode

    def _build_ui(self) -> None:
        self.setMinimumSize(420, 220)
        self.resize(520, 240)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        panel = QWidget()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 10, 12, 12)
        pl.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        drag_strip = _FrameDragStrip(self)
        drag_strip.setObjectName("dragStrip")
        drag_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        drag_strip.setMinimumHeight(28)
        drag_strip.setCursor(Qt.CursorShape.SizeAllCursor)
        top.addWidget(drag_strip, 1)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(36, 32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        top.addWidget(close_btn, 0)
        pl.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addStretch(1)

        side = 148
        editor_btn = QToolButton()
        editor_btn.setObjectName("modeBtn")
        editor_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        editor_btn.setIcon(_mode_icon("editor"))
        editor_btn.setIconSize(QSize(56, 56))
        editor_btn.setText(tr("startup.editor"))
        editor_btn.setFixedSize(side, side)
        editor_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        editor_btn.clicked.connect(self._pick_editor)

        play_btn = QToolButton()
        play_btn.setObjectName("modeBtn")
        play_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        play_btn.setIcon(_mode_icon("playback"))
        play_btn.setIconSize(QSize(56, 56))
        play_btn.setText(tr("startup.playback"))
        play_btn.setFixedSize(side, side)
        play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        play_btn.clicked.connect(self._pick_playback)

        row.addWidget(editor_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        row.addWidget(play_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        row.addStretch(1)
        pl.addLayout(row)

        root.addWidget(panel)

        self.apply_theme_style()

    def apply_theme_style(self) -> None:
        br = theme_corner_radius_css()
        if settings.ui_theme() == "glass":
            self.setStyleSheet(
                f"""
                QWidget#panel {{
                    background-color: #0a0a0a;
                    border: 1px solid rgba(255, 255, 255, 0.35);
                    border-radius: {br};
                }}
                QWidget#dragStrip {{
                    background-color: transparent;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.35);
                }}
                QPushButton#closeBtn {{
                    background-color: rgba(255, 255, 255, 0.16);
                    border: 2px solid rgba(255, 255, 255, 0.9);
                    border-radius: {br};
                    color: #ffffff;
                    font-size: 14px;
                    padding: 0px;
                }}
                QPushButton#closeBtn:hover {{
                    background-color: rgba(255, 255, 255, 0.22);
                }}
                QPushButton#closeBtn:pressed {{
                    background-color: rgba(255, 255, 255, 0.10);
                }}
                QToolButton#modeBtn {{
                    background-color: rgba(255, 255, 255, 0.16);
                    border: 2px solid rgba(255, 255, 255, 0.9);
                    border-radius: {br};
                    color: #f5f5f5;
                    font-size: 15px;
                    font-weight: 800;
                    padding: 8px 6px 10px 6px;
                }}
                QToolButton#modeBtn:hover {{
                    background-color: rgba(255, 255, 255, 0.22);
                }}
                QToolButton#modeBtn:pressed {{
                    background-color: rgba(255, 255, 255, 0.10);
                }}
                """
            )
        else:
            self.setStyleSheet(
                f"""
                QWidget#panel {{
                    background-color: #0a0a0a;
                    border: 1px solid #2a3038;
                    border-radius: {br};
                }}
                QWidget#dragStrip {{
                    background-color: transparent;
                    border-bottom: 1px solid #2a3038;
                }}
                QPushButton#closeBtn {{
                    background-color: #1c1f26;
                    border: 1px solid #3a4558;
                    border-radius: {br};
                    color: #c8c8c8;
                    font-size: 14px;
                    padding: 0px;
                }}
                QPushButton#closeBtn:hover {{
                    background-color: #242830;
                    border: 1px solid #4a5a70;
                }}
                QPushButton#closeBtn:pressed {{
                    background-color: #14161c;
                    border: 1px solid #353d4c;
                }}
                QToolButton#modeBtn {{
                    background-color: #1c1f26;
                    border: 1px solid #3a4558;
                    border-radius: {br};
                    color: #c8c8c8;
                    font-size: 15px;
                    font-weight: 800;
                    padding: 8px 6px 10px 6px;
                }}
                QToolButton#modeBtn:hover {{
                    background-color: #242830;
                    border: 1px solid #4a5a70;
                }}
                QToolButton#modeBtn:pressed {{
                    background-color: #14161c;
                    border: 1px solid #353d4c;
                }}
                """
            )

    def _pick_editor(self) -> None:
        self._mode = "editor"
        self.accept()

    def _pick_playback(self) -> None:
        self._mode = "playback"
        self.accept()
