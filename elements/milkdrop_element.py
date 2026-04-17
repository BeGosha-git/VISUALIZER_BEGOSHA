"""
Область под пресет Milkdrop (.milk): путь и папка текстур для будущего рендера / внешних тулов.
Сейчас — заметная рамка и подпись (встроенный движок projectM в приложение не входит).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen

from .base_element import BaseVisualizationElement


def default_projectm_preset_dir() -> str:
    p = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steamapps" / "common" / "projectM" / "presets"
    return str(p) if p.is_dir() else ""


def default_projectm_textures_dir() -> str:
    p = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam" / "steamapps" / "common" / "projectM" / "textures"
    return str(p) if p.is_dir() else ""


class MilkdropElement(BaseVisualizationElement):
    """Прямоугольник фона под .milk: хранит пути к пресету и текстурам (например Steam projectM)."""

    def __init__(self, x: float = 0, y: float = 0, width: float = 800, height: float = 450):
        super().__init__(x, y, width, height)
        self.preset_path: str = ""
        self.textures_dir: str = default_projectm_textures_dir()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        rect = QRectF(0, 0, self.width, self.height)
        painter.setPen(QPen(QColor(120, 200, 255), 2, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(QColor(15, 22, 38, 210)))
        painter.drawRect(rect)
        from app.i18n import tr

        painter.setPen(QPen(QColor(200, 220, 255)))
        f = painter.font()
        f.setPointSize(11)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(rect.adjusted(8, 8, -8, -28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, tr("canvas.milkdrop"))
        f.setPointSize(9)
        f.setBold(False)
        painter.setFont(f)
        base = Path(self.preset_path).name if self.preset_path else "—"
        painter.drawText(rect.adjusted(8, 36, -8, -8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, base)
        painter.setPen(QPen(QColor(140, 160, 190)))
        painter.drawText(
            rect.adjusted(8, -56, -8, -8),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            tr("canvas.milkdrop_hint"),
        )
        if self.isSelected():
            self.paint_selection_handles(painter)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["preset_path"] = self.preset_path
        d["textures_dir"] = self.textures_dir
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MilkdropElement":
        el = cls(
            float(data.get("x", 0)),
            float(data.get("y", 0)),
            float(data.get("width", 800)),
            float(data.get("height", 450)),
        )
        el.load_visualization_state(data)
        el.preset_path = str(data.get("preset_path", "") or "")
        el.textures_dir = str(data.get("textures_dir", "") or "") or default_projectm_textures_dir()
        return el
