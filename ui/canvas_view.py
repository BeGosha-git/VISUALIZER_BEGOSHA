"""
Интерактивный вид холста.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene

if TYPE_CHECKING:
    from modes.creation_mode import CreationMode


class InteractiveCanvasView(QGraphicsView):
    """Canvas view without monkey-patching event handlers.

    Delegates mouse/wheel events to `CreationMode` methods.
    """

    def __init__(self, scene: QGraphicsScene, creation_mode: CreationMode):
        super().__init__(scene)
        self._creation_mode = creation_mode

    def graphics_view_mouse_press(self, event) -> None:
        """Стандартная обработка QGraphicsView после логики CreationMode (без рекурсии в свой же mousePressEvent)."""
        super().mousePressEvent(event)

    def graphics_view_mouse_move(self, event) -> None:
        super().mouseMoveEvent(event)

    def graphics_view_mouse_release(self, event) -> None:
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        return self._creation_mode.view_mouse_press(event)

    def mouseMoveEvent(self, event):
        return self._creation_mode.view_mouse_move(event)

    def mouseReleaseEvent(self, event):
        return self._creation_mode.view_mouse_release(event)

    def wheelEvent(self, event):
        return self._creation_mode.view_wheel_event(event)

    def keyPressEvent(self, event):
        return self._creation_mode.view_key_press(event)


