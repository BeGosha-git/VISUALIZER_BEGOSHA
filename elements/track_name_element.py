"""
Элемент названия трека из VirtualDJ
"""
from __future__ import annotations

import logging
import os
import time

from PyQt6.QtGui import QPainter

from .text_element import TextElement

logger = logging.getLogger(__name__)


class TrackNameElement(TextElement):
    """Элемент названия трека из VirtualDJ"""
    
    def __init__(self, x: float = 0, y: float = 0, width: float = 400, height: float = 50):
        super().__init__(x, y, width, height, "")
        home = os.path.expanduser("~")
        self.tracklist_paths = [
            os.path.join(home, "Documents", "VirtualDJ", "History", "Tracklist.txt"),
            os.path.join(home, "OneDrive", "Documents", "VirtualDJ", "History", "Tracklist.txt"),
            os.path.join(home, "OneDrive", "Документы", "VirtualDJ", "History", "Tracklist.txt"),
        ]
        prof = os.environ.get("USERPROFILE")
        if prof:
            self.tracklist_paths.append(
                os.path.join(prof, "Documents", "VirtualDJ", "History", "Tracklist.txt")
            )
        self._refresh_interval_sec = 1.0
        # Не читаем файл в __init__, чтобы не подвешивать UI при создании элементов в playback.
        # Первый реальный апдейт будет выполнен периодическим вызовом update_track_name() в UI-потоке.
        self._last_refresh_ts = time.monotonic()
        from app.i18n import tr

        self.text = tr("track.placeholder")

    @staticmethod
    def _expand_path(p: str) -> str:
        p = (p or "").strip().strip('"')
        if not p:
            return ""
        try:
            return os.path.normpath(os.path.expandvars(os.path.expanduser(p)))
        except Exception:
            return p

    @staticmethod
    def _decode_tail(data: bytes) -> str:
        """VirtualDJ может писать UTF-8 или UTF-16 — пробуем типовые кодировки."""
        for enc in ("utf-8-sig", "utf-8", "utf-16-le", "utf-16-be", "utf-16", "cp1251", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def _paths_to_try(self):
        extra: list[str] = []
        try:
            from config.app_settings import settings

            extra = settings.extra_tracklist_paths_list()
        except Exception:
            pass
        seen = set()
        out = []
        for p in extra + self.tracklist_paths:
            p = self._expand_path(p)
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def update_track_name(self, force: bool = False) -> None:
        """Обновить название трека из файла.

        Важно: это вызывается не из `paint()`, чтобы не читать файл на каждом кадре.
        """
        now = time.monotonic()
        if not force and (now - self._last_refresh_ts) < self._refresh_interval_sec:
            return

        self._last_refresh_ts = now

        for path in self._paths_to_try():
            if os.path.exists(path):
                try:
                    # Важно: не читаем весь файл (readlines может быть дорогим на OneDrive).
                    # Читаем только конец файла и извлекаем последнюю строку.
                    with open(path, "rb") as f:
                        f.seek(0, os.SEEK_END)
                        end = f.tell()
                        if end <= 0:
                            continue

                        # Берем несколько последних байт; если строка длиннее, может отрезаться,
                        # но обычно трек-лист содержит короткие строки.
                        max_bytes = 65536  # 64 KB
                        start = max(0, end - max_bytes)
                        # UTF-16: не режем посередине суррогатной пары (чётный offset безопаснее).
                        if start > 0 and start % 2 == 1:
                            start += 1
                        f.seek(start)
                        data = f.read(end - start)

                    # Отрезаем возможный «обрубок» первой строки после seek.
                    if start > 0:
                        nl = data.find(b"\n")
                        if nl != -1:
                            data = data[nl + 1 :]

                    text = self._decode_tail(data)
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    for line in reversed(lines):
                        if line:
                            self.text = line
                            return
                except Exception as e:
                    logger.warning("Ошибка чтения файла трека %s: %s", path, e)

        from app.i18n import tr

        self.text = tr("track.not_found")
    
    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
