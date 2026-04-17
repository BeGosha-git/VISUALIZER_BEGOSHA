"""
Режим проигрывания визуализации.
"""
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.project_assets import resolve_image_path_for_load
from ui.toast import show_toast
from audio_capture import AudioCapture
from config.app_settings import settings as app_settings
from elements import (
    BaseVisualizationElement,
    GroupContainerElement,
    ImageElement,
    LineElement,
    OscilloscopeElement,
    TextElement,
    TrackNameElement,
    WaveElement,
)

logger = logging.getLogger(__name__)


def _console_audio_debug(msg: str) -> None:
    if app_settings.audio_debug_console():
        logger.debug("%s", msg)


class PlaybackMode(QWidget):
    """Режим проигрывания визуализации"""
    
    # Совпадает с `ResolutionBackground(..., x, y)` в CreationMode.setup_ui — иначе F11 даёт другое растяжение.
    _DESIGN_CANVAS_X = 100.0
    _DESIGN_CANVAS_Y = 100.0

    def __init__(
        self,
        parent,
        elements: List[BaseVisualizationElement],
        project_json_path: Optional[str] = None,
        *,
        resolution_width: int = 1920,
        resolution_height: int = 1080,
    ):
        super().__init__(parent)
        self.parent_window = parent
        self.elements = elements
        self._resolution_width = max(1, int(resolution_width))
        self._resolution_height = max(1, int(resolution_height))
        self._design_fit_rect = QRectF(
            self._DESIGN_CANVAS_X,
            self._DESIGN_CANVAS_Y,
            float(self._resolution_width),
            float(self._resolution_height),
        )
        self._project_root: Optional[Path] = (
            Path(project_json_path).resolve().parent if project_json_path else None
        )
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(0, 0, 0))
        self.playback_elements: List[BaseVisualizationElement] = []

        from modes.creation_mode import _element_from_project_item

        root = self._project_root if self._project_root is not None else Path.cwd()
        for elem in self.elements:
            if not isinstance(elem, BaseVisualizationElement):
                continue
            elem_dict = elem.to_dict()
            try:
                new_elem = _element_from_project_item(elem_dict, root)
                if new_elem is None:
                    continue
                if (
                    isinstance(new_elem, ImageElement)
                    and self._project_root is not None
                ):
                    stored = str(elem_dict.get("image_path", "") or "").strip()
                    if stored:
                        abs_p = resolve_image_path_for_load(self._project_root, stored)
                        if abs_p and os.path.isfile(abs_p):
                            new_elem.load_image(abs_p)
                            if not Path(stored).is_absolute():
                                new_elem.image_path = stored.replace("\\", "/")
                new_elem.setZValue(elem.zValue())
                new_elem.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                new_elem.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                self.scene.addItem(new_elem)
                self.playback_elements.append(new_elem)
                if isinstance(new_elem, GroupContainerElement):
                    new_elem._design_pos = QPointF(float(new_elem.x()), float(new_elem.y()))
                    for ch in new_elem.members():
                        ch.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                        ch.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            except Exception:
                continue

        self.audio_capture = AudioCapture(self)
        self.audio_capture.audio_data_ready.connect(self.on_audio_update)
        self.audio_capture.devices_ready.connect(self._on_devices_ready)
        self.audio_capture.devices_error.connect(self._on_devices_error)
        self.audio_capture.capturing_state_changed.connect(self._on_capturing_state_changed)
        self.audio_capture.capture_error.connect(self._on_capture_error)
        
        # Буфер: храним последний аудио-чанк, а визуализацию рисуем по таймеру.
        # Это резко снижает нагрузку на UI и защищает диалоги от зависаний.
        self._latest_audio_data = None
        self._latest_fft_data = None
        self._latest_frequencies = None
        self._has_latest_audio = False

        # Обновление имени трека по таймеру (а не в каждом кадре).
        # Чтобы первое обновление названия трека не триггерилось сразу после старта,
        # а только через интервал (избегаем рывков/зависаний из-за I/O).
        self._last_trackname_update_ts = time.monotonic()
        # Чтение Tracklist.txt может блокировать UI на медленных/синхронизируемых дисках (OneDrive).
        # Увеличиваем интервал и не форсим чтение из GUI-потока.
        self._trackname_update_interval_sec = app_settings.track_name_refresh_sec()
        
        # Текстовый лог текущего аудио (если визуализация не успевает/не работает).
        self._last_audio_debug_ts = 0.0
        self._audio_debug_interval_sec = 1.0
        self._audio_last_received_ts = 0.0
        self._audio_stagnant_reported = False
        self._viz_fullscreen_fill = False
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_visualization)
        self._devices_loaded = False
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Панель управления
        control_panel = QWidget()
        control_panel.setMinimumHeight(56)
        control_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        control_panel.setStyleSheet("")
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(10, 10, 10, 10)
        
        # Выбор устройства
        device_label = QLabel(tr("play.device"))
        device_label.setStyleSheet("")
        control_layout.addWidget(device_label)
        
        self.device_combo = QComboBox()
        self.device_combo.setStyleSheet("")
        self.device_combo.addItem(tr("play.search_devices"), "")
        self.device_combo.setEnabled(False)
        self.device_combo.setMinimumWidth(120)
        self.device_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.device_combo.setToolTip(tr("play.device_tip"))
        control_layout.addWidget(self.device_combo)

        self.capture_status_label = QLabel(tr("play.capture.wait"))
        self.capture_status_label.setStyleSheet("")
        control_layout.addWidget(self.capture_status_label)

        self.audio_debug_label = QLabel(
            tr("play.audio.label") + " " + tr("play.audio.empty")
        )
        self.audio_debug_label.setStyleSheet("")
        control_layout.addWidget(self.audio_debug_label)
        
        # Кнопка старт/стоп
        self.play_btn = QPushButton(tr("play.btn.start"))
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setEnabled(False)
        control_layout.addWidget(self.play_btn)
        
        # Кнопка возврата
        back_btn = QPushButton(tr("play.back"))
        back_btn.clicked.connect(self.back_to_creation)
        control_layout.addWidget(back_btn)
        
        control_layout.addStretch()
        control_panel.setLayout(control_layout)
        self.control_panel = control_panel

        # Сцена визуализации
        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet("background-color: #000000; border: none;")
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        layout.addWidget(control_panel)
        layout.addWidget(self.view)
        
        self.setLayout(layout)

        # Асинхронно загружаем устройства вывода.
        if hasattr(self, "capture_status_label") and self.capture_status_label:
            self.capture_status_label.setText(tr("play.capture.search"))
        self.audio_capture.request_devices()
    
    def toggle_playback(self):
        if self.audio_capture.is_capturing:
            self.stop_playback()
        else:
            self.start_playback()
    
    def start_playback(self):
        if not self._devices_loaded:
            show_toast(self, tr("play.msg.loading"), "warn", 3500)
            return

        device_id = self.device_combo.currentData()
        device_id_or_name = str(device_id) if device_id is not None else ""
        try:
            if self.audio_capture.start_capture(device_id_or_name):
                self._audio_last_received_ts = time.monotonic()
                self._audio_stagnant_reported = False
                # Меньше FPS = меньше перерисовок сцены = меньше нагрузки/подвисаний.
                self.update_timer.start(app_settings.playback_refresh_ms())
                self.play_btn.setText(tr("play.btn.stop"))
                # Сразу даём сигнал, что playback запущен.
                self.audio_debug_label.setText(
                    tr("play.audio.label")
                    + " "
                    + tr("play.audio.started", name=device_id_or_name)
                )
                # Force immediate debug tick.
                self._last_audio_debug_ts = time.monotonic() - self._audio_debug_interval_sec
                app_settings.set_last_audio_device_id(device_id_or_name)
                _console_audio_debug(f"AudioCapture: started device='{device_id_or_name}'")
                # Чтобы не было I/O на старте (особенно update_track_name из файла),
                # гарантированно откладываем первое обновление трека минимум на интервал.
                self._last_trackname_update_ts = time.monotonic() + self._trackname_update_interval_sec
                # Гарантируем, что первый "Audio: --" появится сразу в консоли,
                # даже если первый аудио-чанк ещё не успел прийти.
                # (не вызываем мгновенный scene.update() чтобы не провоцировать ранний paint)
            else:
                show_toast(self, tr("play.err.start_capture"), "err", 5500)
        except Exception as e:
            show_toast(self, tr("play.err.run", e=e), "err", 6000)

    def _on_devices_ready(self, devices: List[Dict[str, Any]]):
        # Устройства могут не подгрузиться из-за отсутствия прав/драйверов.
        self.device_combo.clear()
        if not devices:
            self.device_combo.addItem(tr("play.no_devices"), "")
            self.device_combo.setEnabled(False)
            self.play_btn.setEnabled(False)
            self._devices_loaded = False
            return

        for device in devices:
            self.device_combo.addItem(device["name"], device.get("id", ""))

        last_id = app_settings.last_audio_device_id()
        if last_id:
            for i in range(self.device_combo.count()):
                if str(self.device_combo.itemData(i) or "") == last_id:
                    self.device_combo.setCurrentIndex(i)
                    break

        self.device_combo.setEnabled(True)
        self._devices_loaded = True
        self.play_btn.setEnabled(True)
        if hasattr(self, "capture_status_label") and self.capture_status_label:
            self.capture_status_label.setText(tr("play.capture.stopped"))

    def _on_devices_error(self, err: str):
        self.device_combo.clear()
        self.device_combo.addItem(tr("play.device_error"), "")
        self.device_combo.setEnabled(False)
        self.play_btn.setEnabled(False)
        self._devices_loaded = False
        if hasattr(self, "capture_status_label") and self.capture_status_label:
            self.capture_status_label.setText(tr("play.capture.error"))
        show_toast(self, tr("play.err.devices_list", err=err), "err", 6500)

    def _on_capturing_state_changed(self, capturing: bool):
        """Обновляет UI при включении/остановке захвата аудио."""
        if not hasattr(self, "capture_status_label") or self.capture_status_label is None:
            return

        if capturing:
            self.capture_status_label.setText(tr("play.capture.active"))
            self.device_combo.setEnabled(False)
            self.play_btn.setText(tr("play.btn.stop"))
        else:
            self.capture_status_label.setText(tr("play.capture.stopped"))
            self.device_combo.setEnabled(self._devices_loaded)
            self.play_btn.setText(tr("play.btn.start"))
            # play_btn будет включён, когда устройства найдены
            self.play_btn.setEnabled(self._devices_loaded)

    def _on_capture_error(self, err: str):
        """Ошибка захвата аудио."""
        self.update_timer.stop()
        if hasattr(self, "capture_status_label") and self.capture_status_label:
            self.capture_status_label.setText(tr("play.capture.error"))
        self.play_btn.setText(tr("play.btn.start"))
        self.play_btn.setEnabled(self._devices_loaded)
        self.device_combo.setEnabled(self._devices_loaded)
        self.audio_debug_label.setText(
            tr("play.audio.label") + " " + tr("play.audio.capture_err")
        )
        logger.warning("Ошибка захвата аудио: %s", err)
        show_toast(self, f"{tr('play.err.capture_title')}: {err}", "err", 7000)
    
    def stop_playback(self):
        # Останавливаем таймеры ДО stop_capture, чтобы не обновлять scene в момент остановки.
        _console_audio_debug("PlaybackMode: stop_playback()")
        self.update_timer.stop()
        for e in getattr(self, "playback_elements", []) or []:
            if isinstance(e, GroupContainerElement):
                try:
                    e.reset_playback_motion()
                except Exception:
                    pass
        self.play_btn.setText(tr("play.btn.start"))
        self.audio_capture.stop_capture()
        self.play_btn.setEnabled(self._devices_loaded)

    def handle_fullscreen_toggle(self):
        """Безопасная реакция на F11: если захват активен — перезапускаем его.

        Это предотвращает редкие проблемы с драйверами/рендером при смене режима отображения.
        """
        # Для “готового продукта” F11 не должен ломать захват. В большинстве случаев
        # достаточно продолжать рендерить по таймеру.
        if not self.audio_capture.is_capturing:
            return

        if not self.update_timer.isActive():
            self.update_timer.start(app_settings.playback_refresh_ms())
    
    def on_audio_update(self, audio_data, fft_data, frequencies):
        """Получаем буфер, рисуем по `QTimer`."""
        self._audio_last_received_ts = time.monotonic()
        self._latest_audio_data = audio_data
        self._latest_fft_data = fft_data
        self._latest_frequencies = frequencies
        self._has_latest_audio = True

        # Обновляем текстовую информацию сразу (но не слишком часто).
        # Так ты точно увидишь, что аудио реально приходит.
        now = self._audio_last_received_ts
        if now - self._last_audio_debug_ts >= 0.3:
            try:
                rms = float(np.sqrt(np.mean(np.square(audio_data))))
                peak_idx = int(np.argmax(fft_data)) if hasattr(fft_data, "__len__") else 0
                peak_val = float(fft_data[peak_idx]) if hasattr(fft_data, "__len__") else 0.0
                peak_freq = float(frequencies[peak_idx]) if frequencies is not None and hasattr(frequencies, "__len__") and len(frequencies) > peak_idx else -1.0
                txt = tr("play.audio.label") + " " + tr(
                    "play.audio.rms", rms=rms, peak=peak_val, freq=peak_freq
                )
            except Exception:
                txt = tr("play.audio.label") + " " + tr("play.audio.err_calc")
            self.audio_debug_label.setText(txt)
            _console_audio_debug(txt)
            self._last_audio_debug_ts = now
    
    def update_visualization(self):
        """Обновление визуализации"""
        # Защита от редких вызовов до инициализации аудио-плейбака.
        if not hasattr(self, "audio_debug_label"):
            return
        updated = False
        if self._has_latest_audio and self._latest_audio_data is not None:

            def _iter_audio_targets(
                items: List[BaseVisualizationElement],
            ) -> List[BaseVisualizationElement]:
                out: List[BaseVisualizationElement] = []
                for e in items:
                    out.append(e)
                    if isinstance(e, GroupContainerElement):
                        out.extend(e.members())
                return out

            for elem in _iter_audio_targets(self.playback_elements):
                try:
                    elem.update_audio_data(
                        self._latest_audio_data,
                        self._latest_fft_data,
                        self._latest_frequencies,
                    )
                except Exception:
                    logger.debug("update_audio_data failed for %s", type(elem).__name__, exc_info=True)
            self._has_latest_audio = False
            updated = True

        if self.audio_capture.is_capturing:
            for elem in self.playback_elements:
                if isinstance(elem, GroupContainerElement):
                    amps: List[float] = []
                    for c in elem.members():
                        try:
                            amps.append(float(c.get_amplitude_for_frequencies()))
                        except Exception:
                            amps.append(0.0)
                    raw = max(amps) if amps else 0.0
                    elem.apply_playback_motion(raw * float(elem.group_amplitude))
            updated = True
        
        now = time.monotonic()

        # Если аудио не приходит какое-то время — сообщаем об этом.
        if not self._audio_stagnant_reported and now - self._audio_last_received_ts >= 2.0:
            self._audio_stagnant_reported = True
            msg = tr("play.audio.label") + " " + tr("play.audio.stagnant")
            self.audio_debug_label.setText(msg)
            _console_audio_debug(msg)

        # Логируем параметры текущего аудио раз в N секунд.
        if now - self._last_audio_debug_ts >= self._audio_debug_interval_sec:
            try:
                if self._latest_audio_data is not None and self._latest_fft_data is not None:
                    audio = self._latest_audio_data
                    fft = self._latest_fft_data
                    freqs = self._latest_frequencies
                    rms = float(np.sqrt(np.mean(np.square(audio)))) if hasattr(audio, "__len__") and len(audio) else 0.0
                    fft_mean = float(np.mean(fft)) if hasattr(fft, "__len__") and len(fft) else 0.0
                    peak_idx = int(np.argmax(fft)) if hasattr(fft, "__len__") and len(fft) else 0
                    peak_val = float(fft[peak_idx]) if hasattr(fft, "__len__") and len(fft) else 0.0
                    peak_freq = float(freqs[peak_idx]) if freqs is not None and len(freqs) > peak_idx else -1.0

                    txt = tr("play.audio.label") + " " + tr(
                        "play.audio.fft_detail",
                        rms=rms,
                        fft_mean=fft_mean,
                        peak=peak_val,
                        freq=peak_freq,
                    )
                else:
                    txt = tr("play.audio.label") + " " + tr("play.audio.empty")
                self.audio_debug_label.setText(txt)
                _console_audio_debug(txt)
            except Exception:
                pass
            self._last_audio_debug_ts = now

        if now - self._last_trackname_update_ts >= self._trackname_update_interval_sec:
            for elem in self.playback_elements:
                if isinstance(elem, TrackNameElement):
                    # Не force=True: TrackNameElement сам кэширует и возвращается раньше.
                    elem.update_track_name(force=False)
            self._last_trackname_update_ts = now
            updated = True

        # Перерисовка сцены с частотой таймера при захвате; данные FFT обновляются по сигналу.
        if updated or self.audio_capture.is_capturing:
            self.scene.update()
    
    def _fit_playback_viz_to_view(self) -> None:
        """Подогнать область разрешения под viewport — как в редакторе по ResolutionBackground, не по itemsBoundingRect."""
        try:
            if self._design_fit_rect.width() < 4.0 or self._design_fit_rect.height() < 4.0:
                return
            mode = (
                Qt.AspectRatioMode.IgnoreAspectRatio
                if getattr(self, "_viz_fullscreen_fill", False)
                else Qt.AspectRatioMode.KeepAspectRatio
            )
            self.view.fitInView(self._design_fit_rect, mode)
        except Exception:
            pass

    def set_viz_fullscreen_chrome_visible(self, visible: bool) -> None:
        """Скрыть верхнюю панель устройств/кнопок в режиме «только визуализация»."""
        self._viz_fullscreen_fill = not visible
        try:
            self.control_panel.setVisible(visible)
        except Exception:
            pass
        try:
            if visible:
                self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            else:
                self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        except Exception:
            pass
        if not visible:
            QTimer.singleShot(0, self._fit_playback_viz_to_view)
            QTimer.singleShot(150, self._fit_playback_viz_to_view)
        else:
            QTimer.singleShot(150, self._fit_playback_viz_to_view)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_viz_fullscreen_fill", False):
            QTimer.singleShot(0, self._fit_playback_viz_to_view)

    def back_to_creation(self):
        self.stop_playback()
        self.parent_window.switch_to_creation_mode()
    
    def cleanup(self):
        """Очистка ресурсов"""
        self.stop_playback()
        self.scene.clearSelection()


