"""
Видео на холсте: кадры через QVideoSink; в просмотре — скорость от амплитуды.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from PyQt6.QtCore import QRectF, Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
import logging

from .base_element import BaseVisualizationElement

logger = logging.getLogger(__name__)


class VideoElement(BaseVisualizationElement):
    """Видеофайл в прямоугольнике элемента; воспроизведение с изменением скорости по звуку."""

    def __init__(self, x: float = 0, y: float = 0, width: float = 320, height: float = 180, video_path: str = ""):
        super().__init__(x, y, width, height)
        self.video_path = str(video_path or "")
        self.playback_rate_base: float = 1.0
        self.playback_rate_audio_gain: float = 0.85
        self._player: Optional[QMediaPlayer] = None
        self._audio_out: Optional[QAudioOutput] = None
        self._sink: Optional[QVideoSink] = None
        self._last_frame: Optional[QImage] = None
        self._last_frame_wall: float = 0.0
        self._frame_interval: float = 1.0 / 30.0

    def _on_video_frame(self, frame) -> None:
        now = time.monotonic()
        if now - self._last_frame_wall < self._frame_interval:
            return
        self._last_frame_wall = now
        if frame is None or not frame.isValid():
            return
        try:
            img = frame.toImage()
        except Exception:
            return
        if img.isNull():
            return
        self._last_frame = img
        try:
            self.update()
        except Exception:
            pass

    def _ensure_media(self, parent_obj) -> None:
        if self._player is not None:
            return
        self._player = QMediaPlayer(parent_obj)
        self._audio_out = QAudioOutput()
        self._player.setAudioOutput(self._audio_out)
        try:
            self._audio_out.setMuted(True)
        except Exception:
            pass
        self._sink = QVideoSink()
        self._sink.videoFrameChanged.connect(self._on_video_frame)
        self._player.setVideoOutput(self._sink)
        try:
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
        except Exception:
            pass

    def open_video(self, path: str, parent_obj) -> None:
        self.detach_media()
        self.video_path = path
        if not path or not os.path.isfile(path):
            self._last_frame = None
            self.update()
            return
        self._ensure_media(parent_obj)
        assert self._player is not None
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self._player.play()

    def apply_playback_rate_from_audio(self, band_amp: float) -> None:
        if self._player is None:
            return
        g = max(0.0, float(self.playback_rate_audio_gain))
        r = float(self.playback_rate_base) + float(band_amp) * g * 2.25
        r = max(0.15, min(4.0, r))
        try:
            self._player.setPlaybackRate(r)
        except Exception:
            pass

    def detach_media(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
            try:
                self._player.setSource(QUrl())
            except Exception:
                pass
            try:
                self._player.deleteLater()
            except Exception:
                pass
        self._player = None
        if self._sink is not None:
            try:
                self._sink.deleteLater()
            except Exception:
                pass
        self._sink = None
        if self._audio_out is not None:
            try:
                self._audio_out.deleteLater()
            except Exception:
                pass
        self._audio_out = None
        self._last_frame = None

    def paint(self, painter: QPainter, option, widget=None) -> None:
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            rect = QRectF(0, 0, self.width, self.height)
            if self._last_frame is None or self._last_frame.isNull():
                painter.setPen(QPen(QColor(180, 180, 200), 2, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(QColor(28, 28, 32, 220)))
                painter.drawRect(rect)
                painter.setPen(QPen(QColor(220, 220, 240)))
                from app.i18n import tr

                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr("canvas.video"))
            else:
                painter.drawImage(rect, self._last_frame)
            if self.isSelected():
                self.paint_selection_handles(painter)
        except Exception as e:
            logger.error("VideoElement.paint: %s", e, exc_info=True)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["video_path"] = self.video_path
        d["playback_rate_base"] = float(self.playback_rate_base)
        d["playback_rate_audio_gain"] = float(self.playback_rate_audio_gain)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoElement":
        el = cls(
            float(data.get("x", 0)),
            float(data.get("y", 0)),
            float(data.get("width", 320)),
            float(data.get("height", 180)),
            str(data.get("video_path", "") or ""),
        )
        el.load_visualization_state(data)
        try:
            el.playback_rate_base = float(data.get("playback_rate_base", 1.0))
        except (TypeError, ValueError):
            el.playback_rate_base = 1.0
        try:
            el.playback_rate_audio_gain = float(data.get("playback_rate_audio_gain", 0.85))
        except (TypeError, ValueError):
            el.playback_rate_audio_gain = 0.85
        return el
