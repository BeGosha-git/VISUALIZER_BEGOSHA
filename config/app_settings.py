"""
Персистентные настройки (QSettings).
"""
from __future__ import annotations

from typing import List

from PyQt6.QtCore import QSettings

ORG_NAME = "AudioVizStudio"
APP_NAME = "AudioVisualization"


class AppSettings:
    """Обёртка над QSettings с ключами приложения."""

    def __init__(self) -> None:
        self._s = QSettings(ORG_NAME, APP_NAME)

    # --- Аудио ---
    def silence_rms(self) -> float:
        v = self._s.value("audio/silence_rms", 0.0012)
        try:
            return max(1e-6, float(v))
        except (TypeError, ValueError):
            return 0.0012

    def set_silence_rms(self, value: float) -> None:
        self._s.setValue("audio/silence_rms", float(max(1e-6, value)))

    def audio_debug_console(self) -> bool:
        return bool(self._s.value("audio/debug_console", False))

    def set_audio_debug_console(self, enabled: bool) -> None:
        self._s.setValue("audio/debug_console", bool(enabled))

    def last_audio_device_id(self) -> str:
        return str(self._s.value("audio/last_device_id", "") or "")

    def set_last_audio_device_id(self, device_id: str) -> None:
        self._s.setValue("audio/last_device_id", str(device_id or ""))

    # --- VirtualDJ / трек ---
    def tracklist_extra_paths(self) -> str:
        """Дополнительные пути к Tracklist.txt (по одному на строку)."""
        return str(self._s.value("track/extra_paths", "") or "")

    def set_tracklist_extra_paths(self, text: str) -> None:
        self._s.setValue("track/extra_paths", text)

    def extra_tracklist_paths_list(self) -> List[str]:
        raw = self.tracklist_extra_paths()
        return [line.strip() for line in raw.splitlines() if line.strip()]

    # --- Окно ---
    def save_window_geometry(self, widget) -> None:
        self._s.setValue("ui/window_geometry", widget.saveGeometry())

    def restore_window_geometry(self, widget) -> None:
        geo = self._s.value("ui/window_geometry")
        if geo is not None:
            widget.restoreGeometry(geo)

    # --- Язык интерфейса: "ru" | "en" ---
    def language(self) -> str:
        v = str(self._s.value("ui/language", "ru") or "ru").lower()
        return "en" if v.startswith("en") else "ru"

    def set_language(self, code: str) -> None:
        c = (code or "ru").lower()
        self._s.setValue("ui/language", "en" if c.startswith("en") else "ru")

    # --- Тема интерфейса: "classic" (по умолчанию) | "glass" ---
    def ui_theme(self) -> str:
        v = str(self._s.value("ui/theme", "classic") or "classic").lower().strip()
        return v if v in ("classic", "glass") else "classic"

    def set_ui_theme(self, mode: str) -> None:
        m = str(mode or "classic").lower().strip()
        self._s.setValue("ui/theme", "glass" if m == "glass" else "classic")

    # --- Визуализация ---
    def animation_delay_ms(self) -> float:
        v = self._s.value("ui/animation_delay_ms", 0)
        try:
            return max(-5000.0, min(5000.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    def set_animation_delay_ms(self, value: float) -> None:
        v = float(max(-5000.0, min(5000.0, value)))
        self._s.setValue("ui/animation_delay_ms", v)

    def animation_delay_sec(self) -> float:
        return self.animation_delay_ms() / 1000.0

    def playback_refresh_ms(self) -> int:
        v = self._s.value("ui/playback_refresh_ms", 100)
        try:
            # 11 мс ≈ 91 Гц; 500 мс = 2 Гц. Раньше нижняя граница 33 мс (~30 Гц).
            return max(11, min(500, int(round(float(v)))))
        except (TypeError, ValueError):
            return 100

    def set_playback_refresh_ms(self, value: int) -> None:
        self._s.setValue("ui/playback_refresh_ms", int(max(11, min(500, int(value)))))

    def track_name_refresh_sec(self) -> float:
        v = self._s.value("ui/track_name_refresh_sec", 2.0)
        try:
            return max(0.5, min(60.0, float(v)))
        except (TypeError, ValueError):
            return 2.0

    def set_track_name_refresh_sec(self, value: float) -> None:
        self._s.setValue("ui/track_name_refresh_sec", float(max(0.5, min(60.0, value))))

    # --- Недавние проекты (JSON) ---
    def recent_projects(self) -> List[str]:
        raw = self._s.value("ui/recent_projects")
        if raw is None:
            return []
        if isinstance(raw, str):
            lines = [x.strip() for x in raw.split("\n") if x.strip()]
        else:
            try:
                lines = [str(x).strip() for x in raw if str(x).strip()]  # type: ignore[arg-type]
            except TypeError:
                lines = []
        out: List[str] = []
        seen = set()
        for p in lines:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out[:12]

    def add_recent_project(self, path: str) -> None:
        p = (path or "").strip()
        if not p:
            return
        cur = [x for x in self.recent_projects() if x != p]
        cur.insert(0, p)
        cur = cur[:12]
        self._s.setValue("ui/recent_projects", "\n".join(cur))

    def clear_recent_projects(self) -> None:
        self._s.remove("ui/recent_projects")

# Единый экземпляр на процесс (достаточно для десктоп-приложения).
settings = AppSettings()
