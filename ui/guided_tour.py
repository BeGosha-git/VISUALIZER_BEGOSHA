"""
Гайд по интерфейсу: затемнение + нижняя панель с текстом и кнопками (без тяжёлой отрисовки и кликов по маске).
"""
from __future__ import annotations

from typing import List

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.theme_qss import theme_corner_radius_css


class GuidedTourOverlay(QWidget):
    """Оверлей: полупрозрачный фон и панель с шагами; навигация только кнопками."""

    def __init__(self, host: QWidget, main_window: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._mw = main_window  # оставлен для совместимости вызова
        self._index = 0
        self._steps: List[str] = [
            "tour.step.workflow",
            "tour.step.titlebar",
            "tour.step.settings",
            "tour.step.help",
            "tour.step.left",
            "tour.step.canvas",
            "tour.step.right",
            "tour.step.project",
        ]

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._panel = QWidget(self)
        self._panel.setObjectName("tourPanel")
        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(10)

        self._title = QLabel(tr("tour.title"))
        self._title.setObjectName("tourTitle")
        self._title.setWordWrap(True)

        self._body = QLabel()
        self._body.setObjectName("tourBody")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setOpenExternalLinks(False)

        self._prog = QLabel()
        self._prog.setObjectName("tourProg")

        hint = QLabel(tr("tour.hint"))
        hint.setObjectName("tourHint")
        hint.setWordWrap(True)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._btn_back = QPushButton(tr("tour.btn.back"))
        self._btn_next = QPushButton(tr("tour.btn.next"))
        self._btn_close = QPushButton(tr("tour.btn.close"))
        self._btn_back.clicked.connect(self._prev)
        self._btn_next.clicked.connect(self._next)
        self._btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_back)
        btn_row.addWidget(self._btn_next, 1)
        btn_row.addWidget(self._btn_close)

        pl.addWidget(self._title)
        pl.addWidget(self._body)
        pl.addWidget(self._prog)
        pl.addWidget(hint)
        pl.addLayout(btn_row)

        self._apply_panel_qss()

    def _apply_panel_qss(self) -> None:
        br = theme_corner_radius_css()
        self._panel.setStyleSheet(
            f"""
            QWidget#tourPanel {{
                background-color: rgba(14, 14, 14, 0.96);
                border: 2px solid rgba(255, 255, 255, 0.85);
                border-radius: {br};
            }}
            QLabel#tourTitle {{
                color: #f0f0f0;
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#tourBody {{
                color: #e0e0e0;
                font-size: 11px;
            }}
            QLabel#tourProg {{
                color: #a8a8a8;
                font-size: 10px;
            }}
            QLabel#tourHint {{
                color: #909090;
                font-size: 10px;
            }}
            """
        )

    def refresh_panel_theme_style(self) -> None:
        self._apply_panel_qss()

    def _detach_host_filter(self) -> None:
        try:
            self._host.removeEventFilter(self)
        except Exception:
            pass

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self._fill_geometry()
            return False
        return False

    def _fill_geometry(self) -> None:
        try:
            self.setGeometry(0, 0, max(1, self._host.width()), max(1, self._host.height()))
        except Exception:
            pass
        self._layout_panel()
        self.update()

    def _layout_panel(self) -> None:
        margin = 12
        pw = max(200, int(self.width()))
        ph = max(160, int(self.height()))
        w = min(560, pw - margin * 2)
        self._panel.setFixedWidth(w)
        hint_h = self._panel.sizeHint().height()
        h = max(220, min(int(ph * 0.55), hint_h + 24))
        x = max(margin, (pw - w) // 2)
        y = max(margin, ph - margin - h)
        self._panel.setGeometry(x, y, w, h)

    def _sync_buttons(self) -> None:
        n = len(self._steps)
        self._btn_back.setEnabled(self._index > 0)
        if self._index >= n - 1:
            self._btn_next.setText(tr("tour.btn.done"))
        else:
            self._btn_next.setText(tr("tour.btn.next"))

    def _apply_step(self) -> None:
        if not self._steps or self._index < 0 or self._index >= len(self._steps):
            self.close()
            return
        self._title.setText(tr("tour.title"))
        self._body.setText(tr(self._steps[self._index]))
        self._prog.setText(tr("tour.progress", i=self._index + 1, n=len(self._steps)))
        self._sync_buttons()
        self._layout_panel()

    def start(self) -> None:
        self._detach_host_filter()
        self._host.installEventFilter(self)
        self._index = 0
        self._fill_geometry()
        self._apply_step()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_panel()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fill_geometry()

    def keyPressEvent(self, event) -> None:
        if isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Right):
                self._next()
                return
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Backspace):
                self._prev()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Клики по затемнению не листают шаги — только кнопки (нет зависаний/гонок с UI под оверлеем).
        event.accept()

    def paintEvent(self, _event) -> None:
        try:
            p = QPainter(self)
            if not p.isActive():
                return
            p.fillRect(self.rect(), QColor(0, 0, 0, 140))
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self._detach_host_filter()
        super().closeEvent(event)

    def _next(self) -> None:
        try:
            if self._index >= len(self._steps) - 1:
                self.close()
                return
            self._index += 1
            self._apply_step()
            self.update()
        except Exception:
            self.close()

    def _prev(self) -> None:
        try:
            self._index = max(0, self._index - 1)
            self._apply_step()
            self.update()
        except Exception:
            self.close()
