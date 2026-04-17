"""
Привязка к краям и центрам объектов на сцене (мягкий порог, Alt отключает).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsScene

# В координатах сцены: достаточно для «магнита», но легко сдвинуть дальше (порог не жёсткий).
SNAP_THRESHOLD_SCENE = 14.0


def collect_snap_lines(
    scene: QGraphicsScene, ignore: Optional[QGraphicsItem]
) -> Tuple[List[float], List[float]]:
    xs: List[float] = []
    ys: List[float] = []
    for it in scene.items():
        if it is ignore:
            continue
        if not it.isVisible():
            continue
        br = it.sceneBoundingRect()
        if br.width() <= 0 and br.height() <= 0:
            continue
        xs.extend([br.left(), br.right(), br.center().x()])
        ys.extend([br.top(), br.bottom(), br.center().y()])
    return xs, ys


def _snap_scalar_1d(
    val: float,
    size: float,
    lines: List[float],
    threshold: float,
) -> float:
    """Подгонка левого края val при размере size по вертикальным/горизонтальным линиям."""
    if size <= 0:
        return val
    L = val
    R = val + size
    C = val + size / 2
    best = val
    best_d = threshold + 1.0

    for line in lines:
        for edge, ev in (("L", L), ("R", R), ("C", C)):
            d = abs(ev - line)
            if d > threshold or d >= best_d:
                continue
            best_d = d
            if edge == "L":
                best = line
            elif edge == "R":
                best = line - size
            else:
                best = line - size / 2
    return best


def snap_position_top_left(
    pos: QPointF,
    width: float,
    height: float,
    lines_x: List[float],
    lines_y: List[float],
    threshold: float = SNAP_THRESHOLD_SCENE,
) -> QPointF:
    w = max(1.0, width)
    h = max(1.0, height)
    nx = _snap_scalar_1d(pos.x(), w, lines_x, threshold)
    ny = _snap_scalar_1d(pos.y(), h, lines_y, threshold)
    return QPointF(nx, ny)


def snap_resize_rect(
    handle: str,
    x: float,
    y: float,
    w: float,
    h: float,
    lines_x: List[float],
    lines_y: List[float],
    min_size: float = 20.0,
    threshold: float = SNAP_THRESHOLD_SCENE,
) -> Tuple[float, float, float, float]:
    """Подгонка размера/позиции по краям при перетаскивании маркера."""
    L, R, Tp, B = x, x + w, y, y + h
    nw, nh = w, h

    def snap_edge(coord: float, lines: List[float]) -> Optional[float]:
        best: float | None = None
        best_d = threshold + 1.0
        for line in lines:
            d = abs(coord - line)
            if d <= threshold and d < best_d:
                best_d = d
                best = line
        return best

    if "right" in handle:
        s = snap_edge(R, lines_x)
        if s is not None:
            nw = max(min_size, s - L)
    if "left" in handle:
        s = snap_edge(L, lines_x)
        if s is not None:
            new_l = s
            new_r = L + nw
            nw = max(min_size, new_r - new_l)
            x = new_l
    if "bottom" in handle:
        s = snap_edge(B, lines_y)
        if s is not None:
            nh = max(min_size, s - Tp)
    if "top" in handle:
        s = snap_edge(Tp, lines_y)
        if s is not None:
            new_t = s
            new_b = Tp + nh
            nh = max(min_size, new_b - new_t)
            y = new_t

    return x, y, nw, nh
