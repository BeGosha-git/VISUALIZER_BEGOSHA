"""Время для фазовых анимаций с учётом сдвига из настроек."""
from __future__ import annotations

import time


def animation_time() -> float:
    try:
        from config.app_settings import settings

        return time.time() + settings.animation_delay_sec()
    except Exception:
        return time.time()
