"""
Главное окно приложения.
"""
from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Без верхнего предела окно может занимать весь экран / произвольный размер.
QT_NO_MAX = 16777215

from config.app_settings import settings
from elements import BaseVisualizationElement
from modes.creation_mode import CreationMode
from modes.playback_mode import PlaybackMode
from ui.settings_dialog import SettingsDialog
from ui.guided_tour import GuidedTourOverlay
from ui.hotkeys_dialog import HotkeysDialog
from ui.user_guide_dialog import UserGuideDialog
from widgets import CustomTitleBar


class MainWindow(QMainWindow):
    """Главное окно приложения"""
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        
        # Адаптивный старт: не делаем окно больше доступной области экрана.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            avail_w = geo.width()
            avail_h = geo.height()
            self.setMinimumSize(min(900, avail_w), min(600, avail_h))
            self.setMaximumSize(QT_NO_MAX, QT_NO_MAX)
            self.resize(min(1400, avail_w), min(900, avail_h))
        else:
            self.setMinimumSize(900, 600)
            self.setMaximumSize(QT_NO_MAX, QT_NO_MAX)
            self.resize(1400, 900)
        self.is_fullscreen = False
        self.setup_ui()
        self.setup_shortcuts()
        settings.restore_window_geometry(self)
        try:
            self.title_bar.refresh_window_buttons()
        except Exception:
            pass
    
    def setup_ui(self):
        # Кастомный заголовок
        self.title_bar = CustomTitleBar(self)
        
        # Центральный виджет
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.title_bar)
        
        # Переключение режимов через QStackedWidget (isolation между сценами).
        self.stack = QStackedWidget()
        self.creation_mode = CreationMode(self)
        self.stack.addWidget(self.creation_mode)
        central_layout.addWidget(self.stack, 1)
        
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)
        
        # Тёмная тема: общий фон окна (QSS темы — resources/styles_*.qss)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0a0a0a;
            }
        """)

        self.title_bar.settings_btn.clicked.connect(self._open_settings)
        self.title_bar.about_btn.clicked.connect(self._show_about)
    
    def setup_shortcuts(self):
        """Настройка горячих клавиш"""
        fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        esc_shortcut.activated.connect(self._escape_fullscreen_if_active)
        help_shortcut = QShortcut(QKeySequence("F1"), self)
        help_shortcut.activated.connect(self._show_about)

        ctx = Qt.ShortcutContext.ApplicationShortcut
        self._shortcut_editor_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._shortcut_editor_undo.setContext(ctx)
        self._shortcut_editor_undo.activated.connect(self._shortcut_creation_undo)
        self._shortcut_editor_redo_std = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._shortcut_editor_redo_std.setContext(ctx)
        self._shortcut_editor_redo_std.activated.connect(self._shortcut_creation_redo)
        self._shortcut_editor_redo_y = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._shortcut_editor_redo_y.setContext(ctx)
        self._shortcut_editor_redo_y.activated.connect(self._shortcut_creation_redo)
        self._shortcut_editor_delete = QShortcut(QKeySequence.StandardKey.Delete, self)
        self._shortcut_editor_delete.setContext(ctx)
        self._shortcut_editor_delete.activated.connect(self._shortcut_creation_delete)

        self._shortcut_editor_save = QShortcut(QKeySequence.StandardKey.Save, self)
        self._shortcut_editor_save.setContext(ctx)
        self._shortcut_editor_save.activated.connect(self._shortcut_creation_save)
        self._shortcut_editor_save_as = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self._shortcut_editor_save_as.setContext(ctx)
        self._shortcut_editor_save_as.activated.connect(self._shortcut_creation_save_as)
        self._shortcut_editor_open = QShortcut(QKeySequence.StandardKey.Open, self)
        self._shortcut_editor_open.setContext(ctx)
        self._shortcut_editor_open.activated.connect(self._shortcut_creation_open)
        self._shortcut_editor_select_all = QShortcut(QKeySequence.StandardKey.SelectAll, self)
        self._shortcut_editor_select_all.setContext(ctx)
        self._shortcut_editor_select_all.activated.connect(self._shortcut_creation_select_all)
        self._shortcut_editor_copy = QShortcut(QKeySequence.StandardKey.Copy, self)
        self._shortcut_editor_copy.setContext(ctx)
        self._shortcut_editor_copy.activated.connect(self._shortcut_creation_copy)
        self._shortcut_editor_paste = QShortcut(QKeySequence.StandardKey.Paste, self)
        self._shortcut_editor_paste.setContext(ctx)
        self._shortcut_editor_paste.activated.connect(self._shortcut_creation_paste)
        self._shortcut_editor_duplicate = QShortcut(QKeySequence("Ctrl+D"), self)
        self._shortcut_editor_duplicate.setContext(ctx)
        self._shortcut_editor_duplicate.activated.connect(self._shortcut_creation_duplicate)
        self._shortcut_editor_fit_selection = QShortcut(QKeySequence("Ctrl+E"), self)
        self._shortcut_editor_fit_selection.setContext(ctx)
        self._shortcut_editor_fit_selection.activated.connect(self._shortcut_creation_fit_selection)
        self._shortcut_editor_reset_zoom = QShortcut(QKeySequence("Ctrl+0"), self)
        self._shortcut_editor_reset_zoom.setContext(ctx)
        self._shortcut_editor_reset_zoom.activated.connect(self._shortcut_creation_reset_zoom)
        self._shortcut_editor_layer_up = QShortcut(QKeySequence("PgUp"), self)
        self._shortcut_editor_layer_up.setContext(ctx)
        self._shortcut_editor_layer_up.activated.connect(lambda: self._shortcut_creation_layer(+1))
        self._shortcut_editor_layer_down = QShortcut(QKeySequence("PgDown"), self)
        self._shortcut_editor_layer_down.setContext(ctx)
        self._shortcut_editor_layer_down.activated.connect(lambda: self._shortcut_creation_layer(-1))
        self._shortcut_editor_hotkeys = QShortcut(QKeySequence(Qt.Key.Key_F3), self)
        self._shortcut_editor_hotkeys.setContext(ctx)
        self._shortcut_editor_hotkeys.activated.connect(self._shortcut_creation_hotkeys)

    def _creation_shortcuts_text_focus(self) -> bool:
        w = QApplication.focusWidget()
        if w is None:
            return False
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return True
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            return True
        if isinstance(w, QComboBox) and w.isEditable():
            return True
        return False

    def _shortcut_creation_undo(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_undo()

    def _shortcut_creation_redo(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_redo()

    def _shortcut_creation_delete(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_delete_selected()

    def _shortcut_creation_save(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.save_project_smart()

    def _shortcut_creation_save_as(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.save_project_as_dialog()

    def _shortcut_creation_open(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.load_project()

    def _shortcut_creation_select_all(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_select_all()

    def _shortcut_creation_copy(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_copy_selected()

    def _shortcut_creation_paste(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_paste_from_clipboard()

    def _shortcut_creation_duplicate(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_duplicate_all_selected()

    def _shortcut_creation_fit_selection(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_fit_view_to_selection()

    def _shortcut_creation_reset_zoom(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_reset_canvas_zoom()

    def _shortcut_creation_layer(self, delta: int) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        self.creation_mode.editor_layer_selected(delta)

    def _shortcut_creation_hotkeys(self) -> None:
        if self.stack.currentWidget() is not self.creation_mode:
            return
        if self._creation_shortcuts_text_focus():
            return
        HotkeysDialog(self).exec()

    def _escape_fullscreen_if_active(self) -> None:
        if self.is_fullscreen:
            self.toggle_fullscreen()

    def _set_viz_only_chrome_hidden(self, hide: bool) -> None:
        """Скрыть рамки интерфейса: заголовок и боковые панели / панель просмотра."""
        try:
            self.title_bar.setVisible(not hide)
        except Exception:
            pass
        w = self.stack.currentWidget()
        if w is not None and hasattr(w, "set_viz_fullscreen_chrome_visible"):
            try:
                w.set_viz_fullscreen_chrome_visible(not hide)
            except Exception:
                pass
        try:
            self.title_bar.refresh_window_buttons()
        except Exception:
            pass

    def toggle_fullscreen(self):
        """F11: полный экран без рамок — только область визуализации."""
        if self.is_fullscreen:
            self._set_viz_only_chrome_hidden(False)
            self.showNormal()
            self.is_fullscreen = False
            self.setMaximumSize(QT_NO_MAX, QT_NO_MAX)
        else:
            self.setMaximumSize(QT_NO_MAX, QT_NO_MAX)
            self.showFullScreen()
            self.is_fullscreen = True
            self._set_viz_only_chrome_hidden(True)
            try:
                if hasattr(self, "creation_mode") and self.creation_mode:
                    QTimer.singleShot(0, self.creation_mode._do_fit_canvas)
                    QTimer.singleShot(200, self.creation_mode._do_fit_canvas)
                if hasattr(self, "playback_mode") and self.playback_mode:
                    QTimer.singleShot(0, self.playback_mode._fit_playback_viz_to_view)
                    QTimer.singleShot(200, self.playback_mode._fit_playback_viz_to_view)
            except Exception:
                pass

        # После выхода из fullscreen подгоняем canvas под размер.
        if not self.is_fullscreen and hasattr(self, "creation_mode") and self.creation_mode:
            try:
                self.creation_mode._do_fit_canvas()
            except Exception:
                pass

        # Если пользователь в Playback — обновляем/поддерживаем захват без “лишних” рестартов.
        if hasattr(self, "playback_mode") and self.playback_mode:
            try:
                self.playback_mode.handle_fullscreen_toggle()
            except Exception:
                pass

    def toggle_maximize(self) -> None:
        """Развернуть/восстановить окно (не fullscreen)."""
        # Если сейчас fullscreen — сначала выходим, иначе состояние может “прыгать”.
        if self.is_fullscreen:
            try:
                self.toggle_fullscreen()
            except Exception:
                pass
        try:
            if self.isMaximized():
                self.showNormal()
            else:
                self.setMaximumSize(QT_NO_MAX, QT_NO_MAX)
                self.showMaximized()
        finally:
            try:
                self.title_bar.refresh_window_buttons()
            except Exception:
                pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.is_fullscreen:
            try:
                if hasattr(self, "creation_mode") and self.creation_mode:
                    QTimer.singleShot(0, self.creation_mode._do_fit_canvas)
                if hasattr(self, "playback_mode") and self.playback_mode:
                    QTimer.singleShot(0, self.playback_mode._fit_playback_viz_to_view)
            except Exception:
                pass

    def changeEvent(self, event):
        super().changeEvent(event)
        # Обновляем подсказку кнопки □ при развороте/восстановлении.
        try:
            if event.type() == event.Type.WindowStateChange:
                self.title_bar.refresh_window_buttons()
        except Exception:
            pass

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                from PyQt6.QtWidgets import QApplication

                from app.theme_qss import apply_application_theme, refresh_widgets_using_theme_variant

                apply_application_theme(QApplication.instance())
                refresh_widgets_using_theme_variant()
            except Exception:
                pass
            try:
                if hasattr(self, "creation_mode") and self.creation_mode:
                    self.creation_mode.apply_visual_settings_from_config()
            except Exception:
                pass

    def _show_about(self) -> None:
        # Интерактивный гайд поверх окна (стрелки/подсветки).
        try:
            if not hasattr(self, "_tour") or self._tour is None:
                host = self.centralWidget()
                if host is None:
                    host = self
                self._tour = GuidedTourOverlay(host, self)
            self._tour.start()
            return
        except Exception:
            pass
        # Fallback: если overlay не завёлся — показываем текстовую справку.
        UserGuideDialog(self).exec()

    def closeEvent(self, event):
        """Гарантированная остановка audio-worker при закрытии приложения."""
        try:
            settings.save_window_geometry(self)
        except Exception:
            pass
        try:
            if hasattr(self, "playback_mode") and self.playback_mode:
                self.playback_mode.cleanup()
        except Exception:
            pass
        super().closeEvent(event)
    
    def switch_to_playback_mode(
        self,
        elements: List[BaseVisualizationElement],
        project_json_path: str | None = None,
    ):
        """Переключение в режим проигрывания"""
        if hasattr(self, "playback_mode") and self.playback_mode:
            try:
                self.playback_mode.cleanup()
            except Exception:
                pass
            self.stack.removeWidget(self.playback_mode)
            self.playback_mode.deleteLater()
            self.playback_mode = None

        self.playback_mode = PlaybackMode(
            self,
            elements,
            project_json_path,
            resolution_width=self.creation_mode.resolution_width,
            resolution_height=self.creation_mode.resolution_height,
        )
        self.stack.addWidget(self.playback_mode)
        self.stack.setCurrentWidget(self.playback_mode)
        if self.is_fullscreen:
            self._set_viz_only_chrome_hidden(True)
    
    def switch_to_creation_mode(self):
        """Переключение в режим создания"""
        if hasattr(self, "playback_mode") and self.playback_mode:
            try:
                self.playback_mode.cleanup()
            except Exception:
                pass
            self.stack.removeWidget(self.playback_mode)
            self.playback_mode.deleteLater()
            self.playback_mode = None

        if hasattr(self, "creation_mode") and self.creation_mode:
            self.stack.setCurrentWidget(self.creation_mode)
            if self.is_fullscreen:
                self._set_viz_only_chrome_hidden(True)
            try:
                self.creation_mode.setFocus()
            except Exception:
                pass
