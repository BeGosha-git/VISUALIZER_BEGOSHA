"""Неблокирующие «тост»-уведомления вместо модальных окон для операций с файлами."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, Qt, QTimer
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

from app.theme_qss import theme_corner_radius_css
from config.app_settings import settings

_active_toast: Optional["Toast"] = None


class Toast(QWidget):
    """Короткое сообщение у нижнего края главного окна; исчезает по таймеру."""

    def __init__(
        self,
        host: QWidget,
        text: str,
        kind: str = "info",
        duration_ms: int = 3800,
    ) -> None:
        super().__init__(host)
        self._host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        br = theme_corner_radius_css()
        if settings.ui_theme() == "glass":
            bg = "rgba(18, 18, 18, 0.94)"
            border = "2px solid rgba(255, 255, 255, 0.55)"
            accent = "#e8e8e8"
        else:
            bg = "rgba(22, 24, 28, 0.96)"
            border = "1px solid #3a4558"
            accent = "#c8c8c8"
        if kind == "err":
            accent = "#ff8a8a"
        elif kind == "warn":
            accent = "#e8c86a"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(420)
        lbl.setStyleSheet(f"color: {accent}; font-size: 13px; background: transparent;")
        lay.addWidget(lbl)

        self.setObjectName("toastRoot")
        self.setStyleSheet(
            f"""
            QWidget#toastRoot {{
                background-color: {bg};
                border: {border};
                border-radius: {br};
            }}
            """
        )
        self.adjustSize()

        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(0.0)
        self.setGraphicsEffect(eff)
        self._fade_in = QPropertyAnimation(eff, b"opacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(eff, b"opacity", self)
        self._fade_out.setDuration(220)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self._finish_close)
        self._fade_scheduled = False

        QTimer.singleShot(40, self._fade_in.start)
        QTimer.singleShot(max(800, duration_ms), self._start_fade_out)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._reposition()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reposition()

    def _reposition(self) -> None:
        try:
            hg = self._host.rect()
            x = (hg.width() - self.width()) // 2
            y = hg.height() - self.height() - 28
            self.move(max(0, x), max(0, y))
        except Exception:
            pass

    def _start_fade_out(self) -> None:
        if self._fade_scheduled:
            return
        self._fade_scheduled = True
        try:
            self._fade_out.start()
        except Exception:
            self._finish_close()

    def _finish_close(self) -> None:
        global _active_toast
        if _active_toast is self:
            _active_toast = None
        try:
            self.deleteLater()
        except Exception:
            pass


def show_toast(parent: QWidget | None, text: str, kind: str = "info", duration_ms: int = 3800) -> None:
    """Показать тост относительно окна `parent` (или его `window()`)."""
    global _active_toast
    if not text.strip():
        return
    host = parent.window() if parent is not None else None
    if host is None:
        return
    if _active_toast is not None:
        try:
            _active_toast.hide()
            _active_toast.deleteLater()
        except Exception:
            pass
        _active_toast = None
    t = Toast(host, text, kind=kind, duration_ms=duration_ms)
    _active_toast = t
    t.raise_()
    t.show()
