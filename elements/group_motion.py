"""Общая аудио-анимация сдвига/масштаба/поворота для группы (как у ImageElement)."""
from __future__ import annotations

from typing import Tuple


def motion_deltas(
    movement_type: str, amplitude: float, width: float, height: float
) -> Tuple[float, float, float, float]:
    """Возвращает (offset_x, offset_y, scale_uniform, rotation_deg) для опоры в центре рамки."""
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    ox = 0.0
    oy = 0.0
    sc = 1.0
    rot = 0.0
    mt = (movement_type or "vertical").strip()
    if mt == "vertical":
        oy = float(amplitude) * 50.0
    elif mt == "horizontal":
        ox = float(amplitude) * 50.0
    elif mt == "scale":
        sc = 1.0 + float(amplitude) * 0.5
    elif mt == "rotate":
        rot = float(amplitude) * 360.0
    return ox, oy, sc, rot
