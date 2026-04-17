"""Диалог настроек приложения."""
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.theme_qss import theme_corner_radius_css
from config.app_settings import settings


class _DialogTitleBar(QWidget):
    """Небольшая шапка для безрамочных диалогов (перетаскивание + закрыть)."""

    def __init__(self, dialog: QDialog, title: str) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._drag_pos = None
        self.setFixedHeight(44)
        self.setStyleSheet(
            """
            QWidget {
                background-color: #141414;
                border-bottom: 1px solid #2a2a2a;
            }
        """
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #d0d0d0; font-size: 14px; font-weight: bold;")
        lay.addWidget(lbl)
        lay.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(42, 34)
        close_btn.setToolTip(tr("titlebar.tooltip.close"))
        close_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                color: #b0b0b0;
                font-size: 20px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: #2a2a2a;
                color: #ffffff;
            }
        """
        )
        close_btn.clicked.connect(dialog.reject)
        lay.addWidget(close_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._dialog.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self._dialog.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lang_before = settings.language()
        self.setWindowTitle(tr("settings.title"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(540, 420)

        tabs = QTabWidget()

        # --- Звук ---
        audio_tab = QWidget()
        audio_layout = QVBoxLayout(audio_tab)
        g_audio = QGroupBox(tr("settings.audio.capture"))
        form_a = QFormLayout()
        self._silence = QDoubleSpinBox()
        self._silence.setRange(0.000001, 0.1)
        self._silence.setDecimals(6)
        self._silence.setSingleStep(0.0001)
        self._silence.setValue(settings.silence_rms())
        self._silence.setToolTip(tr("settings.audio.silence_tip"))
        form_a.addRow(tr("settings.audio.silence"), self._silence)
        self._audio_debug = QCheckBox(tr("settings.audio.debug"))
        self._audio_debug.setChecked(settings.audio_debug_console())
        form_a.addRow(self._audio_debug)
        g_audio.setLayout(form_a)
        audio_layout.addWidget(g_audio)
        hint = QLabel(tr("settings.audio.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #909090;")
        audio_layout.addWidget(hint)
        audio_layout.addStretch()
        tabs.addTab(audio_tab, tr("settings.tab.audio"))

        # --- Трек ---
        track_tab = QWidget()
        track_layout = QVBoxLayout(track_tab)
        g_track = QGroupBox(tr("settings.track.group"))
        tv = QVBoxLayout()
        tv.addWidget(QLabel(tr("settings.track.paths")))
        self._extra_paths = QPlainTextEdit()
        self._extra_paths.setPlainText(settings.tracklist_extra_paths())
        self._extra_paths.setPlaceholderText(tr("settings.track.placeholder"))
        tv.addWidget(self._extra_paths)
        g_track.setLayout(tv)
        track_layout.addWidget(g_track)
        track_layout.addStretch()
        tabs.addTab(track_tab, tr("settings.tab.track"))

        # --- Визуализация ---
        visual_tab = QWidget()
        visual_layout = QVBoxLayout(visual_tab)
        g_vis = QGroupBox(tr("settings.visual.group"))
        form_v = QFormLayout()
        self._anim_delay = QDoubleSpinBox()
        self._anim_delay.setRange(-5000, 5000)
        self._anim_delay.setDecimals(0)
        self._anim_delay.setSingleStep(50)
        self._anim_delay.setValue(settings.animation_delay_ms())
        self._anim_delay.setToolTip(tr("settings.visual.anim_delay_tip"))
        form_v.addRow(tr("settings.visual.anim_delay"), self._anim_delay)

        self._playback_fps = QSpinBox()
        self._playback_fps.setRange(2, 90)
        self._playback_fps.setSingleStep(1)
        ms = settings.playback_refresh_ms()
        fps_val = max(2, min(90, int(round(1000.0 / max(1, ms)))))
        self._playback_fps.setValue(fps_val)
        self._playback_fps.setSuffix(" " + tr("settings.visual.fps_suffix"))
        self._playback_fps.setToolTip(tr("settings.visual.refresh_tip"))
        form_v.addRow(tr("settings.visual.refresh"), self._playback_fps)

        self._track_sec = QDoubleSpinBox()
        self._track_sec.setRange(0.5, 60.0)
        self._track_sec.setDecimals(1)
        self._track_sec.setSingleStep(0.5)
        self._track_sec.setValue(settings.track_name_refresh_sec())
        self._track_sec.setToolTip(tr("settings.visual.track_tip"))
        form_v.addRow(tr("settings.visual.track"), self._track_sec)

        g_vis.setLayout(form_v)
        visual_layout.addWidget(g_vis)
        v_hint = QLabel(tr("settings.visual.apply_hint"))
        v_hint.setWordWrap(True)
        v_hint.setStyleSheet("color: #909090;")
        visual_layout.addWidget(v_hint)
        visual_layout.addStretch()
        tabs.addTab(visual_tab, tr("settings.tab.visual"))

        # --- Интерфейс ---
        ui_tab = QWidget()
        ui_layout = QVBoxLayout(ui_tab)
        g_ui = QGroupBox(tr("settings.tab.ui"))
        form_ui = QFormLayout()
        self._language = QComboBox()
        self._language.addItem(tr("settings.ui.language.ru"), "ru")
        self._language.addItem(tr("settings.ui.language.en"), "en")
        idx = self._language.findData(settings.language())
        self._language.setCurrentIndex(max(0, idx))
        form_ui.addRow(tr("settings.ui.language"), self._language)

        self._ui_theme = QComboBox()
        self._ui_theme.addItem(tr("settings.ui.theme.classic"), "classic")
        self._ui_theme.addItem(tr("settings.ui.theme.glass"), "glass")
        ti = self._ui_theme.findData(settings.ui_theme())
        self._ui_theme.setCurrentIndex(max(0, ti))
        form_ui.addRow(tr("settings.ui.theme"), self._ui_theme)

        g_ui.setLayout(form_ui)
        ui_layout.addWidget(g_ui)
        theme_hint = QLabel(tr("settings.ui.theme_hint"))
        theme_hint.setWordWrap(True)
        theme_hint.setStyleSheet("color: #909090;")
        ui_layout.addWidget(theme_hint)
        ui_hint = QLabel(tr("settings.ui.hint"))
        ui_hint.setWordWrap(True)
        ui_hint.setStyleSheet("color: #909090;")
        ui_layout.addWidget(ui_hint)
        ui_layout.addStretch()
        tabs.addTab(ui_tab, tr("settings.tab.ui"))

        row = QHBoxLayout()
        row.addStretch()
        ok_btn = QPushButton(tr("btn.ok"))
        cancel_btn = QPushButton(tr("btn.cancel"))
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(ok_btn)
        row.addWidget(cancel_btn)

        # Внешняя рамка и “панель” как у справки/главного окна
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)
        self.setStyleSheet("QDialog { background-color: #0a0a0a; }")

        panel = QWidget()
        panel.setObjectName("settingsPanel")
        _panel_br = theme_corner_radius_css()
        panel.setStyleSheet(
            f"""
            QWidget#settingsPanel {{
                background-color: #0a0a0a;
                border: 1px solid #2a2a2a;
                border-radius: {_panel_br};
            }}
        """
        )
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(_DialogTitleBar(self, tr("settings.title")))

        body = QVBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(10)
        body.addWidget(tabs, 1)
        body.addLayout(row)
        inner.addLayout(body, 1)
        root.addWidget(panel, 1)

    def _save(self) -> None:
        settings.set_silence_rms(self._silence.value())
        settings.set_audio_debug_console(self._audio_debug.isChecked())
        settings.set_tracklist_extra_paths(self._extra_paths.toPlainText())
        settings.set_animation_delay_ms(self._anim_delay.value())
        fps = int(self._playback_fps.value())
        refresh_ms = max(11, min(500, int(round(1000.0 / max(1, fps)))))
        settings.set_playback_refresh_ms(refresh_ms)
        settings.set_track_name_refresh_sec(self._track_sec.value())
        new_lang = self._language.currentData()
        settings.set_language(str(new_lang))
        td = self._ui_theme.currentData()
        settings.set_ui_theme(str(td) if td is not None else "classic")
        self.accept()
        if self._lang_before != settings.language():
            # Перезапуск для применения языка ко всем виджетам.
            try:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except OSError:
                pass
