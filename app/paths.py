"""Общие пути для файловых диалогов (редактор, стартовый режим, сборка)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional


def documents_directory() -> str:
    """Каталог «Документы» пользователя или домашняя папка."""
    try:
        from PyQt6.QtCore import QStandardPaths

        d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if d:
            return d
    except Exception:
        pass
    return str(Path.home())


def qfile_dialog_options_stable() -> Any:
    """Опции QFileDialog для всех вызовов: на Windows — не-нативный диалог (иначе IFileDialog часто не показывается из вложенных виджетов)."""
    from PyQt6.QtWidgets import QFileDialog

    opts = QFileDialog.Option(0)
    if sys.platform == "win32":
        opts |= QFileDialog.Option.DontUseNativeDialog
    return opts


def qfile_dialog_parent_for_modal(widget: Optional[Any]) -> Optional[Any]:
    """Родитель модального диалога файлов: на Windows — None (как для стабильного IMG), иначе — топ-окно."""
    if widget is None:
        return None
    if sys.platform == "win32":
        return None
    try:
        w = widget.window()
        return w if w is not None else widget
    except Exception:
        return widget
