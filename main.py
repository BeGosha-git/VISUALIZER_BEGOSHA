"""
Главный файл приложения для аудиовизуализации
"""
import logging
import os
import sys
from pathlib import Path

import PyQt6

from PyQt6.QtCore import QLibraryInfo, QTranslator, Qt, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog

from app.i18n import tr
from app.paths import (
    documents_directory,
    qfile_dialog_options_stable,
    qfile_dialog_parent_for_modal,
)
from app.theme_qss import apply_application_theme
from config.app_settings import settings
from ui.main_window import MainWindow
from ui.startup_mode_dialog import StartupModeDialog
from ui.toast import show_toast


def _configure_logging() -> None:
    """При запуске из консоли (stdout — TTY) уровень INFO заметно грузит UI из‑за синхронизации вывода."""
    if os.environ.get("AUDIOVIZ_DEBUG", "").strip():
        level = logging.DEBUG
    else:
        try:
            tty = bool(sys.stdout and sys.stdout.isatty())
        except Exception:
            tty = False
        level = logging.WARNING if tty else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _qt_translation_directories() -> list:
    """Пути к каталогам с qtbase_*.qm (разработка, PyInstaller, системный Qt)."""
    dirs: list = []
    try:
        p = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if p:
            dirs.append(p)
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(str(Path(meipass) / "PyQt6" / "Qt6" / "translations"))
    dirs.append(str(Path(PyQt6.__file__).resolve().parent / "Qt6" / "translations"))
    return dirs


def _install_qt_translator(app: QApplication) -> None:
    """Русские подписи у стандартных кнопок диалогов Qt (Открыть, Отмена и т.д.)."""
    if settings.language() != "ru":
        return
    for dirname in _qt_translation_directories():
        if not dirname:
            continue
        dpath = Path(dirname)
        if not dpath.is_dir():
            continue
        loaded = False
        for base in ("qtbase_ru", "qt_ru"):
            trans = QTranslator(app)
            if trans.load(base, str(dpath)):
                app.installTranslator(trans)
                loaded = True
        if loaded:
            return


def main():
    _configure_logging()

    # Тихо подавляем часть системного шума Qt на Windows (ставим до QApplication, иначе часть строк уходит в консоль раньше обработчика).
    _prev_qt_msg_handler = []

    def _qt_message_handler(mode, context, message):
        try:
            text = str(message)
            if "QPainter::end: Painter ended with" in text:
                return
            if "OleInitialize() failed" in text or "OleInitialize" in text:
                return
            if "SetProcessDpiAwarenessContext" in text:
                return
            if "Qt's default DPI awareness" in text:
                return
        except Exception:
            pass
        prev = _prev_qt_msg_handler[0] if _prev_qt_msg_handler else None
        if prev is not None:
            try:
                prev(mode, context, message)
            except Exception:
                pass

    try:
        _prev_qt_msg_handler.append(qInstallMessageHandler(_qt_message_handler))
    except Exception:
        _prev_qt_msg_handler.append(None)

    app_attr = Qt.ApplicationAttribute
    if hasattr(app_attr, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(app_attr.AA_EnableHighDpiScaling, True)
    if hasattr(app_attr, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(app_attr.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(tr("app.title"))
    _install_qt_translator(app)

    app.setStyle("Fusion")
    apply_application_theme(app)

    picker = StartupModeDialog()
    if picker.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)
    start_mode = picker.selected_mode()

    window = MainWindow()

    if start_mode == "playback":
        try:
            window.raise_()
            window.activateWindow()
        except Exception:
            pass
        path, _ = QFileDialog.getOpenFileName(
            qfile_dialog_parent_for_modal(window),
            tr("dialog.open_project"),
            documents_directory(),
            tr("dialog.filter.json"),
            "",
            qfile_dialog_options_stable(),
        )
        if not path:
            show_toast(window, tr("startup.playback_no_file"), "info", 4000)
        elif window.creation_mode.load_project_from_path(path, show_success_dialog=False):
            if window.creation_mode.elements:
                window.switch_to_playback_mode(
                    window.creation_mode.elements,
                    window.creation_mode._project_json_path,
                )
            else:
                show_toast(window, tr("startup.playback_empty"), "warn", 4500)

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
