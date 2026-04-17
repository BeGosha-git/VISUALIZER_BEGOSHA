"""
Модуль для захвата аудио вывода через soundcard.

Захват выполняется в отдельном потоке (подкласс QThread, цикл в run()).
Сигналы в UI идут через QueuedConnection. Остановка — только флагом из run(),
без вызова методов QObject захвата с чужого потока.
"""

from __future__ import annotations

import soundcard as sc
import numpy as np
import warnings

from typing import Optional, Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, Qt

# soundcard на некоторых драйверах при loopback может постоянно спамить
# warnings вида "data discontinuity in recording".
try:
    from soundcard.mediafoundation import SoundcardRuntimeWarning  # type: ignore

    warnings.filterwarnings("ignore", category=SoundcardRuntimeWarning)
except Exception:
    pass

# --- Compatibility fix for soundcard + NumPy >= 2.0 ---
_orig_np_fromstring = np.fromstring


def _patched_fromstring(a, dtype=float, count=-1, sep=""):
    try:
        return _orig_np_fromstring(a, dtype=dtype, count=count, sep=sep)
    except ValueError as e:
        if "binary mode of fromstring is removed" in str(e):
            return np.frombuffer(a, dtype=dtype, count=count if count != -1 else -1)
        raise


np.fromstring = _patched_fromstring


def _get_recorder_ctx(
    speaker: Any,
    requested: str,
    sample_rate: int,
    channels: int = 1,
) -> Any:
    """Контекстный менеджер recorder для loopback (speaker / WASAPI loopback)."""
    if hasattr(speaker, "recorder"):
        try:
            return speaker.recorder(samplerate=sample_rate, channels=channels)
        except Exception:
            pass

    try:
        all_mics = sc.all_microphones(include_loopback=True)

        for candidate in (
            requested,
            getattr(speaker, "id", "") or "",
            getattr(speaker, "name", "") or "",
        ):
            candidate = str(candidate).strip()
            if not candidate:
                continue
            try:
                mic = sc.get_microphone(id=candidate, include_loopback=True)
                return mic.recorder(samplerate=sample_rate, channels=channels)
            except Exception:
                continue

        speaker_name = (getattr(speaker, "name", "") or "").lower()
        requested_l = (requested or "").lower()

        def score(m) -> int:
            n = (getattr(m, "name", "") or "").lower()
            s = 0
            if speaker_name and speaker_name in n:
                s += 100
            if requested_l and requested_l in n:
                s += 60
            if "loopback" in n:
                s += 30
            if getattr(m, "_is_loopback", False):
                s += 20
            return s

        loopbacks = sorted(all_mics, key=score, reverse=True)
        best = loopbacks[0] if loopbacks else None
        if best is not None and score(best) > 0:
            return best.recorder(samplerate=sample_rate, channels=channels)
    except Exception:
        pass

    try:
        all_mics = sc.all_microphones(include_loopback=True)
        if all_mics:
            return all_mics[0].recorder(samplerate=sample_rate, channels=channels)
    except Exception:
        pass

    default_mic = sc.default_microphone()
    return default_mic.recorder(samplerate=sample_rate, channels=channels)


class _DevicesListerWorker(QObject):
    devices_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()

    @pyqtSlot()
    def run(self) -> None:
        try:
            speakers = sc.all_speakers()
            devices = [{"name": sp.name, "id": sp.id} for sp in speakers]
            self.devices_ready.emit(devices)
        except Exception as e:
            self.error.emit(str(e))


class AudioCaptureThread(QThread):
    """Поток захвата: один mic.record() на итерацию, emit прореживается по счётчику (без sleep/busy-loop)."""

    audio_data_ready = pyqtSignal(object, object, object)
    capture_failed = pyqtSignal(str)

    def __init__(
        self,
        sample_rate: int,
        chunk_size: int,
        device_id_or_name: str,
        target_emit_hz: float = 20.0,
        silence_rms: float = 0.0012,
    ) -> None:
        super().__init__()
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.device_id_or_name = device_id_or_name or ""
        self.target_emit_hz = max(1.0, float(target_emit_hz))
        self._silence_rms = max(1e-6, float(silence_rms))

        self._stop_requested = False

        # Сколько примерно кадров record в секунду: sr / chunk.
        frames_per_sec = self.sample_rate / max(1, self.chunk_size)
        # Например 44100/1024 ~ 43 кадра/с, при target 20 Hz -> emit каждые 2 кадра.
        self._emit_every_n = max(1, int(round(frames_per_sec / self.target_emit_hz)))

        # Совпадает с np.fft.rfft(..., n=chunk_size) и срезом [: chunk_size // 2].
        self.frequencies = np.fft.rfftfreq(chunk_size, 1 / sample_rate)[: chunk_size // 2]

    def request_stop(self) -> None:
        """Запрос остановки (безопасно вызывать с UI-потока: только выставляет флаг)."""
        self._stop_requested = True

    def run(self) -> None:
        try:
            from soundcard.mediafoundation import SoundcardRuntimeWarning  # type: ignore
        except Exception:
            SoundcardRuntimeWarning = Warning  # type: ignore

        try:
            speaker: Optional[sc.Speaker] = None
            req = self.device_id_or_name

            if req:
                speakers = sc.all_speakers()
                for sp in speakers:
                    if sp.id == req or sp.name == req:
                        speaker = sp
                        break
                    if req in sp.name:
                        speaker = sp
                        break

            speaker = speaker or sc.default_speaker()
            recorder_ctx = _get_recorder_ctx(speaker, req, self.sample_rate, channels=1)

            frame_idx = 0
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=SoundcardRuntimeWarning)
                with recorder_ctx as mic:
                    while not self._stop_requested:
                        try:
                            data = mic.record(numframes=self.chunk_size)
                        except Exception as e:
                            self.capture_failed.emit(f"Ошибка записи (mic.record): {e}")
                            return

                        audio_data = np.asarray(data, dtype=np.float32).reshape(-1)
                        if audio_data.size == 0:
                            continue

                        frame_idx += 1
                        if frame_idx % self._emit_every_n != 0:
                            continue

                        # RMS до FFT: при тишине/шуме драйвера нормализация max(fft)->1
                        # превращает случайный бин в peak=1.0 и визуализация «дёргается».
                        rms = float(np.sqrt(np.mean(np.square(audio_data, dtype=np.float64))))
                        if rms < self._silence_rms:
                            n_bins = self.chunk_size // 2
                            fft_data = np.zeros(n_bins, dtype=np.float32)
                            audio_out = np.zeros_like(audio_data)
                            self.audio_data_ready.emit(audio_out, fft_data, self.frequencies)
                            continue

                        try:
                            fft = np.fft.rfft(audio_data, n=self.chunk_size)
                            fft_data = np.abs(fft[: self.chunk_size // 2])
                        except Exception as e:
                            self.capture_failed.emit(f"Ошибка FFT: {e}")
                            return

                        max_val = float(np.max(fft_data)) if fft_data.size else 0.0
                        if max_val > 0:
                            fft_data = (fft_data / max_val).astype(np.float32, copy=False)
                        else:
                            fft_data = fft_data.astype(np.float32, copy=False)

                        self.audio_data_ready.emit(audio_data, fft_data, self.frequencies)

        except Exception as e:
            self.capture_failed.emit(str(e))


class AudioCapture(QObject):
    """Захват аудио вывода (soundcard + QThread)."""

    devices_ready = pyqtSignal(list)
    devices_error = pyqtSignal(str)

    audio_data_ready = pyqtSignal(object, object, object)
    capturing_state_changed = pyqtSignal(bool)
    capture_error = pyqtSignal(str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        sample_rate: int = 44100,
        chunk_size: int = 1024,
        emit_interval_sec: float = 0.05,
    ) -> None:
        super().__init__(parent)
        self.sample_rate = sample_rate
        self.chunk_size = max(64, int(chunk_size))
        self._emit_interval_sec = float(emit_interval_sec)
        self._target_emit_hz = max(1.0, 1.0 / self._emit_interval_sec)

        self.is_capturing = False

        self._devices_thread: Optional[QThread] = None
        self._devices_worker: Optional[_DevicesListerWorker] = None

        self._capture_thread: Optional[AudioCaptureThread] = None

    def request_devices(self) -> None:
        """Асинхронно получить список доступных устройств вывода."""
        if self._devices_thread and self._devices_thread.isRunning():
            return

        self._devices_thread = QThread()
        self._devices_worker = _DevicesListerWorker()
        self._devices_worker.moveToThread(self._devices_thread)

        self._devices_thread.started.connect(self._devices_worker.run)
        self._devices_worker.devices_ready.connect(self._on_devices_ready)
        self._devices_worker.error.connect(self._on_devices_error)

        self._devices_worker.devices_ready.connect(self._devices_thread.quit)
        self._devices_worker.devices_ready.connect(self._devices_worker.deleteLater)
        self._devices_worker.error.connect(self._devices_thread.quit)
        self._devices_worker.error.connect(self._devices_worker.deleteLater)

        self._devices_thread.finished.connect(self._devices_thread.deleteLater)

        self._devices_thread.start()

    @pyqtSlot(list)
    def _on_devices_ready(self, devices: list) -> None:
        self.devices_ready.emit(devices)

    @pyqtSlot(str)
    def _on_devices_error(self, err: str) -> None:
        self.devices_error.emit(err)

    def start_capture(self, device_id_or_name: Optional[str] = None) -> bool:
        """Запустить захват аудио."""
        if self.is_capturing:
            return False

        if self._capture_thread and self._capture_thread.isRunning():
            return False

        from config.app_settings import settings as app_settings

        ms = max(11, int(app_settings.playback_refresh_ms()))
        target_hz = max(1.0, min(90.0, 1000.0 / float(ms)))

        self._capture_thread = AudioCaptureThread(
            sample_rate=self.sample_rate,
            chunk_size=self.chunk_size,
            device_id_or_name=str(device_id_or_name or ""),
            target_emit_hz=target_hz,
            silence_rms=app_settings.silence_rms(),
        )

        self._capture_thread.audio_data_ready.connect(
            self.audio_data_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._capture_thread.capture_failed.connect(
            self.capture_error,
            Qt.ConnectionType.QueuedConnection,
        )
        self._capture_thread.finished.connect(self._on_capture_thread_finished)
        self._capture_thread.finished.connect(self._capture_thread.deleteLater)

        self.is_capturing = True
        self.capturing_state_changed.emit(True)

        self._capture_thread.start()
        return True

    @pyqtSlot()
    def _on_capture_thread_finished(self) -> None:
        self.is_capturing = False
        self.capturing_state_changed.emit(False)
        self._capture_thread = None

    def stop_capture(self) -> None:
        """Остановить захват (только request_stop на QThread — без вызова слотов worker с чужого потока)."""
        t = self._capture_thread
        if t is not None and t.isRunning():
            t.request_stop()

        self.is_capturing = False
