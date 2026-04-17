"""Загрузка глобального QSS по ключу `settings.ui_theme()` (classic | glass)."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return Path(__file__).resolve().parent.parent


def theme_stylesheet_path() -> Path:
    from config.app_settings import settings

    name = "styles_glass.qss" if settings.ui_theme() == "glass" else "styles_classic.qss"
    return _project_root() / "resources" / name


def theme_corner_radius_css() -> str:
    """Единое скругление для обеих тем (как в Glass)."""
    return "8px"


def apply_application_theme(app: QApplication | None) -> None:
    """Полностью заменить application stylesheet выбранной темой."""
    if app is None:
        return
    path = theme_stylesheet_path()
    if not path.is_file():
        return
    try:
        app.setStyleSheet(path.read_text(encoding="utf-8"))
    except OSError:
        pass


def _repolish_all_widgets(app: QApplication) -> None:
    """Сброс кэша стиля: после смены application stylesheet часть виджетов иначе «залипает»."""
    try:
        for w in app.allWidgets():
            if w is None:
                continue
            try:
                st = w.style()
                st.unpolish(w)
                st.polish(w)
            except Exception:
                pass
    except Exception:
        pass


def refresh_widgets_using_theme_variant() -> None:
    """Перерисовать виджеты с кастомной отрисовкой и локальными QSS, зависящими от темы."""
    app = QApplication.instance()
    if app is None:
        return
    try:
        from widgets.element_button import ElementButton

        for w in app.allWidgets():
            if isinstance(w, ElementButton):
                try:
                    w.refresh_theme_style()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from ui.guided_tour import GuidedTourOverlay

        for w in app.allWidgets():
            if isinstance(w, GuidedTourOverlay):
                try:
                    w.refresh_panel_theme_style()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from widgets.custom_title_bar import CustomTitleBar

        for w in app.allWidgets():
            if isinstance(w, CustomTitleBar):
                try:
                    w.refresh_theme_style()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from widgets.properties_panel import PropertiesPanel

        for w in app.allWidgets():
            if isinstance(w, PropertiesPanel):
                try:
                    w.refresh_after_theme_change()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from widgets.properties_panel import DualLogFreqRangeSlider

        for w in app.allWidgets():
            if isinstance(w, DualLogFreqRangeSlider):
                try:
                    w.update()
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from ui.startup_mode_dialog import StartupModeDialog

        for w in app.allWidgets():
            if isinstance(w, StartupModeDialog):
                try:
                    w.apply_theme_style()
                except Exception:
                    pass
    except Exception:
        pass
    _repolish_all_widgets(app)
