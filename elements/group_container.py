"""
Группа элементов: общее перемещение на холсте и общая аудио-анимация в просмотре.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsItem

from .base_element import BaseVisualizationElement
from .group_motion import motion_deltas

logger = logging.getLogger(__name__)


class GroupContainerElement(BaseVisualizationElement):
    """Контейнер: дети рисуются внутри группы; в просмотре — сдвиг/масштаб/поворот от звука."""

    def __init__(self, x: float = 0, y: float = 0, width: float = 100, height: float = 100):
        super().__init__(x, y, width, height)
        self.group_movement_type: str = "vertical"
        self.group_amplitude: float = 1.0
        self._pivot_local_x: float = width / 2.0
        self._pivot_local_y: float = height / 2.0
        self._design_pos = QPointF(float(x), float(y))
        self._members: List[BaseVisualizationElement] = []

    def _sync_rect_from_children(self) -> None:
        br = self.childrenBoundingRect()
        if br.isEmpty():
            return
        try:
            self.prepareGeometryChange()
        except Exception:
            pass
        self.width = max(1.0, float(br.width()))
        self.height = max(1.0, float(br.height()))
        self._pivot_local_x = self.width / 2.0
        self._pivot_local_y = self.height / 2.0

    def add_member(self, child: BaseVisualizationElement) -> None:
        child.setParentItem(self)
        child.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        child.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        if child not in self._members:
            self._members.append(child)
        self._sync_rect_from_children()

    def members(self) -> List[BaseVisualizationElement]:
        return [c for c in self._members if c.parentItem() is self]

    def boundingRect(self) -> QRectF:
        br = self.childrenBoundingRect()
        if br.isEmpty():
            return QRectF(0.0, 0.0, max(1.0, float(self.width)), max(1.0, float(self.height)))
        return br.adjusted(-4.0, -4.0, 4.0, 4.0)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.isSelected():
            try:
                br = self.childrenBoundingRect()
                if not br.isEmpty():
                    painter.setPen(QPen(QColor(120, 170, 255), 2, Qt.PenStyle.DashLine))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(br)
            except Exception:
                logger.debug("group paint selection", exc_info=True)

    def get_resize_handle_at(self, scene_pos: QPointF) -> Optional[str]:
        return None

    def get_rotate_handle_at(self, scene_pos: QPointF) -> bool:
        return False

    def _apply_transform(self) -> None:
        """Группа не использует flip/rotation_deg базы — только движение просмотра через setRotation/setScale."""
        from PyQt6.QtGui import QTransform

        self.setTransformOriginPoint(self._pivot_local_x, self._pivot_local_y)
        self.setTransform(QTransform())

    def load_visualization_state(self, data: Dict[str, Any]) -> None:
        super().load_visualization_state(data)
        try:
            self.group_movement_type = str(data.get("group_movement_type", "vertical") or "vertical")
        except Exception:
            self.group_movement_type = "vertical"
        try:
            self.group_amplitude = float(data.get("group_amplitude", 1.0))
        except (TypeError, ValueError):
            self.group_amplitude = 1.0
        try:
            self._pivot_local_x = float(data.get("pivot_local_x", self.width / 2.0))
            self._pivot_local_y = float(data.get("pivot_local_y", self.height / 2.0))
        except (TypeError, ValueError):
            self._pivot_local_x = self.width / 2.0
            self._pivot_local_y = self.height / 2.0

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["group_movement_type"] = self.group_movement_type
        data["group_amplitude"] = float(self.group_amplitude)
        data["pivot_local_x"] = float(self._pivot_local_x)
        data["pivot_local_y"] = float(self._pivot_local_y)
        data["children"] = [c.to_dict() for c in self.members()]
        return data

    @classmethod
    def from_dict_with_resolver(
        cls,
        data: Dict[str, Any],
        resolve_child: Callable[[Dict[str, Any]], Optional[BaseVisualizationElement]],
    ) -> Optional["GroupContainerElement"]:
        try:
            x = float(data.get("x", 0))
            y = float(data.get("y", 0))
            w = float(data.get("width", 100))
            h = float(data.get("height", 100))
        except (TypeError, ValueError):
            return None
        g = cls(x, y, w, h)
        g.load_visualization_state(data)
        g._design_pos = QPointF(float(g.x()), float(g.y()))
        raw_children = data.get("children")
        if not isinstance(raw_children, list):
            return g
        for cd in raw_children:
            if not isinstance(cd, dict):
                continue
            ch = resolve_child(cd)
            if ch is None:
                continue
            g.add_member(ch)
        g._sync_rect_from_children()
        return g

    def itemChange(self, change, value):
        out = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._design_pos = QPointF(float(self.x()), float(self.y()))
        return out

    def apply_playback_motion(self, amplitude: float) -> None:
        """Вызывается из PlaybackMode: amplitude уже с учётом group_amplitude."""
        amp = float(amplitude)
        ox, oy, sc, rot = motion_deltas(
            self.group_movement_type, amp, float(self.width), float(self.height)
        )
        self.setTransformOriginPoint(self._pivot_local_x, self._pivot_local_y)
        self.setPos(self._design_pos.x() + ox, self._design_pos.y() + oy)
        if self.group_movement_type == "scale":
            self.setScale(float(sc))
            self.setRotation(0.0)
        elif self.group_movement_type == "rotate":
            self.setScale(1.0)
            self.setRotation(float(rot))
        else:
            self.setScale(1.0)
            self.setRotation(0.0)

    def reset_playback_motion(self) -> None:
        self.setPos(self._design_pos)
        self.setScale(1.0)
        self.setRotation(0.0)
