"""
Панель свойств выбранного элемента
"""
from __future__ import annotations

import logging
import math
import weakref

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QColorDialog,
    QScrollArea,
    QSizePolicy,
    QGridLayout,
    QSlider,
)
from typing import Callable, List, Optional
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen

from app.i18n import animation_label, movement_label, tr
from app.paths import documents_directory, qfile_dialog_options_stable, qfile_dialog_parent_for_modal
from ui.toast import show_toast
from app.theme_qss import theme_corner_radius_css
from config.app_settings import settings as app_settings
from elements import (
    BaseVisualizationElement,
    GroupContainerElement,
    ImageElement,
    MilkdropElement,
    WaveElement,
    OscilloscopeElement,
    TextElement,
    TrackNameElement,
    LineElement,
    VideoElement,
)

logger = logging.getLogger(__name__)


def _freq_remove_btn_stylesheet() -> str:
    r = theme_corner_radius_css()
    if app_settings.ui_theme() == "glass":
        return f"""
            QPushButton#freqRemoveBtn {{
                background-color: rgba(12, 12, 12, 0.95);
                border: 2px solid rgba(255, 255, 255, 0.9);
                border-radius: {r};
                color: #ffffff;
                font-size: 18px;
                font-weight: 900;
                padding: 0px;
                margin: 0px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }}
            QPushButton#freqRemoveBtn:hover {{
                background-color: rgba(40, 40, 40, 0.95);
            }}
            QPushButton#freqRemoveBtn:pressed {{
                background-color: rgba(8, 8, 8, 0.95);
            }}
            """
    return f"""
            QPushButton#freqRemoveBtn {{
                background-color: #1c1f26;
                border: 1px solid #4a5a70;
                border-radius: {r};
                color: #c8c8c8;
                font-size: 18px;
                font-weight: 900;
                padding: 0px;
                margin: 0px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }}
            QPushButton#freqRemoveBtn:hover {{
                background-color: #242830;
                border: 1px solid #5a6a82;
            }}
            QPushButton#freqRemoveBtn:pressed {{
                background-color: #14161c;
                border: 1px solid #353d4c;
            }}
            """


def _animation_combo_stylesheet() -> str:
    r = theme_corner_radius_css()
    if app_settings.ui_theme() == "glass":
        return f"""
            QComboBox {{
                min-height: 34px;
                padding: 4px 10px;
                font-size: 11px;
                border-radius: {r};
            }}
            QComboBox QAbstractItemView {{
                outline: none;
                border: 1px solid rgba(255, 255, 255, 0.45);
                background-color: rgba(18, 18, 18, 0.98);
                border-radius: {r};
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 30px;
                padding: 4px 10px;
            }}
            """
    return f"""
            QComboBox {{
                min-height: 34px;
                padding: 4px 10px;
                font-size: 11px;
                border-radius: {r};
            }}
            QComboBox QAbstractItemView {{
                outline: none;
                border: 1px solid #333842;
                background-color: #141414;
                border-radius: {r};
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 30px;
                padding: 4px 10px;
            }}
            """


class DualLogFreqRangeSlider(QWidget):
    """Два маркера «от / до» на одной логарифмической шкале 20 Гц … 20 кГц."""

    valueChanged = pyqtSignal()

    FMIN = 20.0
    FMAX = 20000.0
    _LOG_LO = math.log10(FMIN)
    _LOG_HI = math.log10(FMAX)
    _LOG_SPAN = _LOG_HI - _LOG_LO
    # Диаметр 16px в теме «glass»; в «classic» — круглые маркеры как раньше (8px радиус)
    HANDLE_R = 8.0
    TRACK_H = 4.0
    TRACK_RX = 2.0
    MIN_T_GAP = 1.0 / 80.0

    def __init__(self, fa: float, fb: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag: Optional[str] = None
        self._t_lo = self._t_from_f(fa)
        self._t_hi = self._t_from_f(fb)
        self._normalize_order()
        self.setMinimumHeight(46)
        self.setMaximumHeight(54)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Без фокуса — иначе Fusion рисует синюю рамку выделения при Tab/клике.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _t_from_f(self, f: float) -> float:
        f = max(self.FMIN, min(self.FMAX, float(f)))
        return (math.log10(f) - self._LOG_LO) / self._LOG_SPAN

    def _f_from_t(self, t: float) -> float:
        t = max(0.0, min(1.0, float(t)))
        return 10.0 ** (self._LOG_LO + t * self._LOG_SPAN)

    def _normalize_order(self) -> None:
        if self._t_lo > self._t_hi:
            self._t_lo, self._t_hi = self._t_hi, self._t_lo
        self._t_lo = max(0.0, min(1.0, self._t_lo))
        self._t_hi = max(0.0, min(1.0, self._t_hi))
        if self._t_hi - self._t_lo < self.MIN_T_GAP:
            mid = (self._t_lo + self._t_hi) / 2.0
            mid = min(max(mid, self.MIN_T_GAP / 2), 1.0 - self.MIN_T_GAP / 2)
            self._t_lo = max(0.0, mid - self.MIN_T_GAP / 2)
            self._t_hi = min(1.0, self._t_lo + self.MIN_T_GAP)

    def range_hz(self) -> tuple[float, float]:
        self._normalize_order()
        a = self._f_from_t(self._t_lo)
        b = self._f_from_t(self._t_hi)
        if a > b:
            a, b = b, a
        return (a, b)

    def set_range_hz(self, fa: float, fb: float) -> None:
        self._t_lo = self._t_from_f(fa)
        self._t_hi = self._t_from_f(fb)
        self._normalize_order()
        self.update()

    def _track_metrics(self) -> tuple[float, float, float]:
        w = max(40, self.width())
        h = self.height()
        margin_x = 12.0
        track_y = float(h) - 16.0
        tw = float(w) - 2.0 * margin_x
        return margin_x, track_y, tw

    def _x_for_t(self, t: float, margin_x: float, tw: float) -> float:
        return margin_x + t * tw

    def _t_for_x(self, x: float, margin_x: float, tw: float) -> float:
        if tw <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - margin_x) / tw))

    def _handle_at(self, mx: float, my: float) -> Optional[str]:
        margin_x, track_y, tw = self._track_metrics()
        if tw <= 0:
            return None
        x_lo = self._x_for_t(self._t_lo, margin_x, tw)
        x_hi = self._x_for_t(self._t_hi, margin_x, tw)
        r = self.HANDLE_R + 4.0
        if (mx - x_lo) ** 2 + (my - track_y) ** 2 <= r * r:
            return "lo"
        if (mx - x_hi) ** 2 + (my - track_y) ** 2 <= r * r:
            return "hi"
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            hx = self._handle_at(float(e.position().x()), float(e.position().y()))
            if hx:
                self._drag = hx
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._drag:
            self._drag = None
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag:
            margin_x, _track_y, tw = self._track_metrics()
            nt = self._t_for_x(float(e.position().x()), margin_x, tw)
            if self._drag == "lo":
                self._t_lo = min(nt, self._t_hi - self.MIN_T_GAP)
            else:
                self._t_hi = max(nt, self._t_lo + self.MIN_T_GAP)
            self._normalize_order()
            self.update()
            self.valueChanged.emit()
            e.accept()
            return
        cur = self._handle_at(float(e.position().x()), float(e.position().y()))
        if cur:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(e)

    def _fmt_hz(self, f: float) -> str:
        if f >= 1000.0:
            return tr("freq.label_khz", v=f / 1000.0)
        return tr("freq.label_hz", v=f)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin_x, track_y, tw = self._track_metrics()
        h = self.height()

        a_hz, b_hz = self.range_hz()
        lbl = f"{self._fmt_hz(a_hz)}   …   {self._fmt_hz(b_hz)}"
        fnt = QFont(self.font())
        fnt.setPointSize(9)
        p.setFont(fnt)
        p.setPen(QColor(170, 170, 170))
        p.drawText(12, 16, lbl)

        x_lo = self._x_for_t(self._t_lo, margin_x, tw)
        x_hi = self._x_for_t(self._t_hi, margin_x, tw)

        if app_settings.ui_theme() == "glass":
            th = self.TRACK_H
            gy = float(track_y) - th / 2.0
            left = min(x_lo, x_hi)
            right = max(x_lo, x_hi)
            aw = max(1.0, right - left)
            groove = QRectF(margin_x, gy, tw, th)
            # Скругление дорожки как у QSlider в styles_glass.qss (4px), не как у тонкой линии classic.
            track_rx = 4.0
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.setBrush(QBrush(QColor(255, 255, 255, 31)))
            p.drawRoundedRect(groove, track_rx, track_rx)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 61)))
            p.drawRoundedRect(QRectF(left, gy, aw, th), track_rx, track_rx)
            hp = QPen(QColor(255, 255, 255, 230), 2)
            hb = QBrush(QColor(255, 255, 255, 46))
            for x in (x_lo, x_hi):
                p.setPen(hp)
                p.setBrush(hb)
                p.drawEllipse(QPointF(x, track_y), self.HANDLE_R, self.HANDLE_R)
        else:
            # Classic: тонкие линии + лёгкий сине-стальный акцент (согласовано со styles_classic.qss / QSlider)
            p.setPen(QPen(QColor(38, 42, 50), 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawLine(int(margin_x), int(track_y), int(margin_x + tw), int(track_y))
            p.setPen(QPen(QColor(72, 108, 158), 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawLine(int(x_lo), int(track_y), int(x_hi), int(track_y))
            for x in (x_lo, x_hi):
                p.setPen(QPen(QColor(120, 160, 220, 115), 1))
                p.setBrush(QBrush(QColor(30, 36, 48)))
                p.drawEllipse(QPointF(x, track_y), self.HANDLE_R, self.HANDLE_R)

        fmini = QFont(self.font())
        fmini.setPointSize(8)
        p.setFont(fmini)
        p.setPen(QColor(95, 95, 95))
        p.drawText(int(margin_x), int(h - 4), f"{int(self.FMIN)}")
        p.drawText(int(margin_x + tw - 36), int(h - 4), f"{int(self.FMAX // 1000)}k")


class PropertiesPanel(QWidget):
    """Панель свойств выбранного элемента"""
    
    def __init__(self):
        super().__init__()
        self.current_element: Optional[BaseVisualizationElement] = None
        self._current_elements: List[BaseVisualizationElement] = []
        self._common_pos_x_spin: Optional[QDoubleSpinBox] = None
        self._common_pos_y_spin: Optional[QDoubleSpinBox] = None
        # Увеличивается при очистке панели: отменяет отложенные обработчики UI частот
        # после deleteLater(), иначе возможен вылет по уже уничтоженным виджетам.
        self._props_ui_generation = 0
        self.setup_ui()
        # Глобальный QSS: resources/styles_classic.qss | styles_glass.qss
        self.setStyleSheet("")
    
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        
        self.info_label = QLabel(tr("props.select"))
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("")
        layout.addWidget(self.info_label)

        # Реально прокручиваемая область свойств.
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        # Горизонтальный скролл в панели свойств — это почти всегда признак «слишком широкого контента».
        # Лучше переносить/ужимать содержимое, чем заставлять пользователя скроллить вбок.
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout()
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(6)
        self.scroll_widget.setLayout(self.scroll_layout)
        self.scroll_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        
        self.scroll_area.setWidget(self.scroll_widget)
        layout.addWidget(self.scroll_area, 1)
        
        self.setLayout(layout)

    def refresh_position_fields_from_element(self, element: BaseVisualizationElement) -> None:
        """Синхронизировать поля X/Y с позицией элемента после перетаскивания на холсте."""
        if len(getattr(self, "_current_elements", [])) > 1:
            return
        if self.current_element is not element:
            return
        x_spin = self._common_pos_x_spin
        y_spin = self._common_pos_y_spin
        if x_spin is None or y_spin is None:
            return
        try:
            from PyQt6 import sip

            if sip.isdeleted(element) or sip.isdeleted(x_spin) or sip.isdeleted(y_spin):
                return
        except Exception:
            return
        try:
            with QSignalBlocker(x_spin), QSignalBlocker(y_spin):
                x_spin.setValue(float(element.x()))
                y_spin.setValue(float(element.y()))
        except RuntimeError:
            pass

    def refresh_after_theme_change(self) -> None:
        """Пересобрать локальные стили (крестики, комбо, высоты слайдеров) после смены темы."""
        el = self.current_element
        if el is None:
            return
        try:
            self.show_properties(el)
        except Exception:
            pass

    def _wrap_label(self, text: str) -> QLabel:
        """Подпись для QFormLayout, которая переносится и не раздувает ширину панели."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMinimumWidth(0)
        lbl.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        lbl.setStyleSheet("color: #808080;")
        return lbl

    def _prep_field(self, w: QWidget) -> QWidget:
        """Поле ввода/виджет, который можно ужимать по ширине."""
        try:
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        except Exception:
            pass
        return w

    def _hint_one_line(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setWordWrap(False)
        lb.setStyleSheet("color: #707070; font-size: 9px;")
        try:
            lb.setMaximumHeight(16)
        except Exception:
            pass
        return lb

    def _form_add_amplitude_slider(self, form: QFormLayout, initial: float, on_value: Callable[[int], None]) -> None:
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(0, 50)
        sl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sl.setMinimumHeight(28 if app_settings.ui_theme() == "glass" else 22)
        iv = int(round(max(0.0, min(50.0, float(initial)))))
        sl.setValue(iv)
        vlab = QLabel(str(iv))
        vlab.setMinimumWidth(28)
        vlab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def _chg(x: int) -> None:
            vx = max(0, min(50, int(x)))
            vlab.setText(str(vx))
            on_value(vx)

        sl.valueChanged.connect(_chg)
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(sl, 1)
        hl.addWidget(vlab, 0)
        form.addRow(self._wrap_label(tr("props.amplitude")), self._prep_field(row))

    def _form(self) -> QFormLayout:
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        # Ключевое: не даём колонке подписей раздувать форму.
        # Подписи должны занимать минимум, а поле — получать остаток ширины.
        try:
            form.setColumnStretch(0, 0)
            form.setColumnStretch(1, 1)
            form.setColumnMinimumWidth(0, 120)
        except Exception:
            pass
        return form

    def _prepare_animation_combo(self, combo: QComboBox) -> None:
        """Высокий комбобокс и выпадающий список без скролла (мало пунктов)."""
        combo.setMinimumHeight(34)
        combo.setMaxVisibleItems(max(12, combo.count()))
        combo.setStyleSheet(_animation_combo_stylesheet())
        try:
            view = combo.view()
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            n = int(combo.count())
            if n > 0:
                h = n * 32 + 10
                view.setMinimumHeight(h)
                view.setMaximumHeight(h)
        except Exception:
            pass

    def clear_properties(self):
        """Очистить панель свойств"""
        self._common_pos_x_spin = None
        self._common_pos_y_spin = None
        self._current_elements = []
        self._props_ui_generation += 1
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.current_element = None
        self.info_label.setText(tr("props.select"))
    
    def show_properties(self, element: BaseVisualizationElement):
        """Показать свойства элемента"""
        self.clear_properties()
        self.current_element = element
        self._current_elements = [element]

        if isinstance(element, GroupContainerElement):
            self._setup_group_container_properties(element)
            self._setup_common_properties(element)
            return
        if isinstance(element, MilkdropElement):
            self._setup_milkdrop_properties(element)
            self._setup_common_properties(element)
            return
        if isinstance(element, VideoElement):
            self._setup_video_properties(element)
        elif isinstance(element, ImageElement):
            self._setup_image_properties(element)
        elif isinstance(element, WaveElement) and not isinstance(element, OscilloscopeElement):
            self._setup_wave_properties(element)
        elif isinstance(element, OscilloscopeElement):
            self._setup_oscilloscope_properties(element)
        elif isinstance(element, TextElement) and not isinstance(element, TrackNameElement):
            self._setup_text_properties(element)
        elif isinstance(element, TrackNameElement):
            self._setup_trackname_properties(element)
        elif isinstance(element, LineElement):
            self._setup_line_properties(element)
        
        # Общие свойства
        self._setup_common_properties(element)
        
        # Частоты
        self._add_frequency_range_ui(element)

    def show_properties_multi(self, elements: List[BaseVisualizationElement]) -> None:
        """Несколько выделенных: общие поля; при одном типе — ещё блок типа."""
        self.clear_properties()
        if not elements:
            return
        self._current_elements = list(elements)
        self.current_element = elements[0]
        self.info_label.setText(tr("props.selected_n", n=len(elements)))
        self._setup_common_properties_multi(elements)
        t = type(elements[0])
        homo = all(type(e) is t for e in elements)
        if homo and t is ImageElement:
            self._setup_image_properties_multi(elements)
        elif homo and t is TextElement and all(not isinstance(e, TrackNameElement) for e in elements):
            self._setup_text_properties_multi(elements)

    def _setup_group_container_properties(self, g: GroupContainerElement) -> None:
        group = QGroupBox(tr("props.group"))
        form = self._form()
        movement_combo = QComboBox()
        for val in ("vertical", "horizontal", "scale", "rotate"):
            movement_combo.addItem(movement_label(val), val)
        mi = movement_combo.findData(g.group_movement_type)
        movement_combo.setCurrentIndex(max(0, mi))

        def _on_move(_idx: int) -> None:
            data = movement_combo.currentData()
            if data is not None:
                g.group_movement_type = str(data)
                g.update()

        movement_combo.currentIndexChanged.connect(_on_move)
        form.addRow(self._wrap_label(tr("props.image.movement")), self._prep_field(movement_combo))
        ga_sl = QSlider(Qt.Orientation.Horizontal)
        ga_sl.setRange(0, 100)
        ga_sl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ga_sl.setMinimumHeight(28 if app_settings.ui_theme() == "glass" else 22)
        ga_sl.setValue(int(round(min(100.0, max(0.0, float(g.group_amplitude) * 10.0)))))
        gav = QLabel(f"{float(g.group_amplitude):.1f}")
        gav.setMinimumWidth(36)
        gav.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def _on_ga(x: int) -> None:
            av = max(0, min(100, int(x))) / 10.0
            gav.setText(f"{av:.1f}")
            g.group_amplitude = av
            g.update()

        ga_sl.valueChanged.connect(_on_ga)
        ga_row = QWidget()
        ghl = QHBoxLayout(ga_row)
        ghl.setContentsMargins(0, 0, 0, 0)
        ghl.setSpacing(8)
        ghl.addWidget(ga_sl, 1)
        ghl.addWidget(gav, 0)
        form.addRow(self._wrap_label(tr("props.group_strength")), self._prep_field(ga_row))
        group.setLayout(form)
        self.scroll_layout.addWidget(group)

    def _setup_common_properties_multi(self, elements: List[BaseVisualizationElement]) -> None:
        group = QGroupBox(tr("props.common"))
        form = self._form()

        def _apply_all(fn) -> None:
            for e in elements:
                fn(e)
                try:
                    e.update()
                except Exception:
                    pass

        def _amp_multi(v: int) -> None:
            vf = float(max(0, min(50, v)))
            _apply_all(lambda e: setattr(e, "amplitude", vf))

        self._form_add_amplitude_slider(form, float(elements[0].amplitude), _amp_multi)

        smooth_slider = QSlider(Qt.Orientation.Horizontal)
        smooth_slider.setRange(0, 5)
        smooth_slider.setValue(max(0, min(5, int(getattr(elements[0], "smoothing_passes", 1)))))
        sv = QLabel(str(smooth_slider.value()))
        sv.setMinimumWidth(22)
        sv.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def _on_smooth(x: int) -> None:
            sv.setText(str(int(x)))
            for e in elements:
                e.smoothing_passes = int(x)
                if isinstance(e, LineElement):
                    try:
                        e._rebuild_smoothed()
                    except Exception:
                        pass
                e.update()

        smooth_slider.valueChanged.connect(_on_smooth)
        sw = QWidget()
        shl = QHBoxLayout(sw)
        shl.setContentsMargins(0, 0, 0, 0)
        shl.addWidget(smooth_slider, 1)
        shl.addWidget(sv, 0)
        form.addRow(self._wrap_label(tr("props.smooth")), sw)

        w_spin = QDoubleSpinBox()
        w_spin.setRange(1.0, 8000.0)
        w_spin.setDecimals(1)
        w_spin.setValue(float(elements[0].width))
        h_spin = QDoubleSpinBox()
        h_spin.setRange(1.0, 8000.0)
        h_spin.setDecimals(1)
        h_spin.setValue(float(elements[0].height))

        def _set_wh() -> None:
            for e in elements:
                try:
                    e.prepareGeometryChange()
                except Exception:
                    pass
                e.width = float(w_spin.value())
                e.height = float(h_spin.value())
                try:
                    e._apply_transform()
                except Exception:
                    pass
                e.update()

        w_spin.valueChanged.connect(lambda _v: _set_wh())
        h_spin.valueChanged.connect(lambda _v: _set_wh())
        sz_row = QWidget()
        sr = QHBoxLayout(sz_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(6)
        sr.addWidget(QLabel(tr("props.widget_w")), 0)
        sr.addWidget(self._prep_field(w_spin), 1)
        sr.addWidget(QLabel(tr("props.widget_h")), 0)
        sr.addWidget(self._prep_field(h_spin), 1)
        form.addRow(self._wrap_label(tr("props.size_wh")), sz_row)

        rot_spin = QDoubleSpinBox()
        rot_spin.setRange(-180.0, 180.0)
        rot_spin.setDecimals(1)
        rot_spin.setSingleStep(1.0)
        rot_spin.setValue(float(getattr(elements[0], "rotation_deg", 0.0) or 0.0))

        def _set_rot(v: float) -> None:
            for e in elements:
                e.rotation_deg = float(v)
                try:
                    e._apply_transform()
                except Exception:
                    pass
                e.update()

        rot_spin.valueChanged.connect(_set_rot)
        form.addRow(self._wrap_label(tr("props.rotation")), self._prep_field(rot_spin))

        group.setLayout(form)
        self.scroll_layout.addWidget(group)

    def _setup_image_properties_multi(self, elements: List[BaseVisualizationElement]) -> None:
        imgs = [e for e in elements if isinstance(e, ImageElement)]
        if not imgs:
            return
        group = QGroupBox(tr("props.image"))
        form = self._form()
        movement_combo = QComboBox()
        for val in ("vertical", "horizontal", "scale", "rotate"):
            movement_combo.addItem(movement_label(val), val)
        mi = movement_combo.findData(imgs[0].movement_type)
        movement_combo.setCurrentIndex(max(0, mi))

        def _on_move(_idx: int) -> None:
            data = movement_combo.currentData()
            if data is None:
                return
            mt = str(data)
            for e in imgs:
                e.movement_type = mt
                e.update()

        movement_combo.currentIndexChanged.connect(_on_move)
        form.addRow(self._wrap_label(tr("props.image.movement")), self._prep_field(movement_combo))
        group.setLayout(form)
        self.scroll_layout.addWidget(group)

    def _setup_text_properties_multi(self, elements: List[BaseVisualizationElement]) -> None:
        texts = [e for e in elements if isinstance(e, TextElement) and not isinstance(e, TrackNameElement)]
        if not texts:
            return
        group = QGroupBox(tr("props.text"))
        form = self._form()
        text_edit = QLineEdit(texts[0].text)

        def _on_text(v: str) -> None:
            for t in texts:
                t.text = v
                t.update()

        text_edit.textChanged.connect(_on_text)
        form.addRow(self._wrap_label(tr("props.text.content")), self._prep_field(text_edit))
        fs = QSpinBox()
        fs.setRange(8, 200)
        fs.setValue(int(texts[0].base_font_size))

        def _on_fs(v: int) -> None:
            iv = int(v)
            for t in texts:
                t.base_font_size = iv
                t.font.setPointSize(iv)
                t.update()

        fs.valueChanged.connect(_on_fs)
        form.addRow(self._wrap_label(tr("props.text.font_size")), self._prep_field(fs))
        group.setLayout(form)
        self.scroll_layout.addWidget(group)
    
    def _setup_common_properties(self, element: BaseVisualizationElement):
        """Настройка общих свойств"""
        group = QGroupBox(tr("props.common"))
        form = self._form()

        form.addRow(self._hint_one_line(tr("props.common_hint")))

        if float(element.amplitude) > 50.0:
            element.amplitude = 50.0
            element.update()

        def _amp_one(v: int) -> None:
            element.amplitude = float(max(0, min(50, v)))
            element.update()

        self._form_add_amplitude_slider(form, float(element.amplitude), _amp_one)

        # Координаты (позиция элемента: левый верхний угол)
        x_spin = QDoubleSpinBox()
        x_spin.setRange(-100000.0, 100000.0)
        x_spin.setDecimals(1)
        x_spin.setSingleStep(1.0)
        x_spin.setValue(float(element.x()))

        y_spin = QDoubleSpinBox()
        y_spin.setRange(-100000.0, 100000.0)
        y_spin.setDecimals(1)
        y_spin.setSingleStep(1.0)
        y_spin.setValue(float(element.y()))
        self._common_pos_x_spin = x_spin
        self._common_pos_y_spin = y_spin

        def _set_pos() -> None:
            try:
                BaseVisualizationElement.set_position_snap_suppressed(True)
                element.setPos(float(x_spin.value()), float(y_spin.value()))
                element.update()
            except Exception:
                pass
            finally:
                try:
                    BaseVisualizationElement.set_position_snap_suppressed(False)
                except Exception:
                    pass

        x_spin.valueChanged.connect(lambda _v: _set_pos())
        y_spin.valueChanged.connect(lambda _v: _set_pos())
        pos_row = QWidget()
        pr = QHBoxLayout(pos_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(6)
        pr.addWidget(QLabel(tr("props.pos_x")), 0)
        pr.addWidget(self._prep_field(x_spin), 1)
        pr.addWidget(QLabel(tr("props.pos_y")), 0)
        pr.addWidget(self._prep_field(y_spin), 1)
        form.addRow(self._wrap_label(tr("props.pos_xy")), pos_row)

        # Поворот
        rot_spin = QDoubleSpinBox()
        rot_spin.setRange(-180.0, 180.0)
        rot_spin.setDecimals(1)
        rot_spin.setSingleStep(1.0)
        rot_spin.setValue(float(getattr(element, "rotation_deg", 0.0) or 0.0))

        def _set_rot(v: float) -> None:
            try:
                element.rotation_deg = float(v)
                element._apply_transform()
                element.update()
            except Exception:
                pass

        rot_spin.valueChanged.connect(_set_rot)
        form.addRow(self._wrap_label(tr("props.rotation")), self._prep_field(rot_spin))

        if not isinstance(element, LineElement):
            wh_w = QDoubleSpinBox()
            wh_w.setRange(1.0, 8000.0)
            wh_w.setDecimals(1)
            wh_w.setValue(float(element.width))
            wh_h = QDoubleSpinBox()
            wh_h.setRange(1.0, 8000.0)
            wh_h.setDecimals(1)
            wh_h.setValue(float(element.height))

            def _set_wh_single() -> None:
                try:
                    element.prepareGeometryChange()
                except Exception:
                    pass
                element.width = float(wh_w.value())
                element.height = float(wh_h.value())
                try:
                    element._apply_transform()
                except Exception:
                    pass
                element.update()

            wh_w.valueChanged.connect(lambda _v: _set_wh_single())
            wh_h.valueChanged.connect(lambda _v: _set_wh_single())
            sz_row = QWidget()
            sr = QHBoxLayout(sz_row)
            sr.setContentsMargins(0, 0, 0, 0)
            sr.setSpacing(6)
            sr.addWidget(QLabel(tr("props.widget_w")), 0)
            sr.addWidget(self._prep_field(wh_w), 1)
            sr.addWidget(QLabel(tr("props.widget_h")), 0)
            sr.addWidget(self._prep_field(wh_h), 1)
            form.addRow(self._wrap_label(tr("props.size_wh")), sz_row)

        group.setLayout(form)
        self.scroll_layout.addWidget(group)
    
    def _setup_image_properties(self, element: ImageElement):
        group = QGroupBox(tr("props.image"))
        form = self._form()
        
        # Путь к изображению
        path_edit = QLineEdit(element.image_path)
        path_edit.setMinimumWidth(0)
        path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        path_btn = QPushButton(tr("btn.choose_file"))
        path_btn.clicked.connect(lambda: self._select_image(element, path_edit))
        form.addRow(self._wrap_label(tr("props.image.path")), self._prep_field(path_edit))
        form.addRow("", path_btn)
        
        movement_combo = QComboBox()
        for val in ("vertical", "horizontal", "scale", "rotate"):
            movement_combo.addItem(movement_label(val), val)
        mi = movement_combo.findData(element.movement_type)
        movement_combo.setCurrentIndex(max(0, mi))

        def _on_move(_idx: int) -> None:
            data = movement_combo.currentData()
            if data is not None:
                element.movement_type = str(data)
                element.update()

        movement_combo.currentIndexChanged.connect(_on_move)
        form.addRow(self._wrap_label(tr("props.image.movement")), self._prep_field(movement_combo))

        group.setLayout(form)
        self.scroll_layout.addWidget(group)
    
    def _select_image(self, element: ImageElement, path_edit: QLineEdit):
        """Выбор файла без QThread: загрузка через ImageElement.load_image в UI-потоке со следующего тика.

        Отдельный поток с QImage/QPixmap давал зависания/краши при гонках с закрытием панели и Qt.
        """
        dlg_parent = self.window() or self
        try:
            dlg_parent.raise_()
            dlg_parent.activateWindow()
        except Exception:
            pass
        path, _ = QFileDialog.getOpenFileName(
            qfile_dialog_parent_for_modal(dlg_parent),
            tr("dialog.pick_image"),
            documents_directory(),
            tr("dialog.filter.images"),
            "",
            qfile_dialog_options_stable(),
        )
        if not path:
            return
        from ui.image_import_edit_dialog import run_image_import_edit_dialog

        edited = run_image_import_edit_dialog(path, dlg_parent)
        if edited is None:
            return
        path = edited
        element.image_path = path
        path_edit.setText(path)

        def _apply_image_deferred() -> None:
            try:
                from PyQt6 import sip

                if sip.isdeleted(self) or sip.isdeleted(path_edit) or sip.isdeleted(element):
                    return
            except Exception:
                return
            if self.current_element is not element:
                return
            try:
                element.load_image(path)
                element.update()
            except MemoryError as e:
                show_toast(self, tr("err.image_memory", detail=str(e)), "err", 6000)
            except Exception as e:
                logger.error("load_image from properties: %s", e, exc_info=True)
                show_toast(self, str(e), "err", 5500)

        QTimer.singleShot(0, _apply_image_deferred)

    def _form_add_smoothing_passes(self, form: QFormLayout, element) -> None:
        """Слайдер 0–5: волна/осц/линия — Чайкин; для всех — плавность реакции амплитуды (картинка, текст)."""
        smooth_slider = QSlider(Qt.Orientation.Horizontal)
        smooth_slider.setRange(0, 5)
        smooth_slider.setSingleStep(1)
        smooth_slider.setPageStep(1)
        smooth_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        smooth_slider.setMinimumHeight(36 if app_settings.ui_theme() == "glass" else 28)
        v0 = max(0, min(5, int(getattr(element, "smoothing_passes", 1))))
        smooth_slider.setValue(v0)
        val_lbl = QLabel(str(v0))
        val_lbl.setMinimumWidth(22)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def _on_smooth(x: int) -> None:
            element.smoothing_passes = int(x)
            val_lbl.setText(str(x))
            if isinstance(element, LineElement):
                element._rebuild_smoothed()
            element.update()

        smooth_slider.valueChanged.connect(_on_smooth)

        wrap = QWidget()
        vb = QVBoxLayout(wrap)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(4)
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(smooth_slider, 1)
        hl.addWidget(val_lbl, 0)
        vb.addLayout(hl)
        vb.addWidget(self._hint_one_line(tr("props.smooth.hint")))
        form.addRow(self._wrap_label(tr("props.smooth")), wrap)

    def _setup_wave_properties(
        self,
        element: WaveElement,
        *,
        title: str | None = None,
        show_smoothing: bool = True,
    ):
        group = QGroupBox(title or tr("props.wave"))
        form = self._form()

        color_btn = QPushButton(tr("btn.choose_color"))
        color_btn.clicked.connect(lambda: self._select_color(element))
        form.addRow(self._wrap_label(tr("props.color")), color_btn)

        width_spin = QDoubleSpinBox()
        width_spin.setRange(1.0, 20.0)
        width_spin.setValue(element.line_width)
        width_spin.valueChanged.connect(lambda v: setattr(element, "line_width", v) or element.update())
        form.addRow(self._wrap_label(tr("props.width")), self._prep_field(width_spin))

        if show_smoothing:
            self._form_add_smoothing_passes(form, element)

        form_names = [tr(f"props.wave.form.{i}") for i in range(9)]
        form_sl = QSlider(Qt.Orientation.Horizontal)
        form_sl.setRange(0, 8)
        form_sl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        form_sl.setMinimumHeight(32 if app_settings.ui_theme() == "glass" else 26)
        form_sl.setValue(max(0, min(8, int(getattr(element, "display_form", 0)))))
        form_val = QLabel(form_names[form_sl.value()])
        form_val.setMinimumWidth(120)
        form_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def _on_form(v: int) -> None:
            iv = max(0, min(8, int(v)))
            element.display_form = iv
            form_val.setText(form_names[iv])
            element.update()

        form_sl.valueChanged.connect(_on_form)
        form_wrap = QWidget()
        fwl = QHBoxLayout(form_wrap)
        fwl.setContentsMargins(0, 0, 0, 0)
        fwl.setSpacing(8)
        fwl.addWidget(form_sl, 1)
        fwl.addWidget(form_val, 0)
        form.addRow(self._wrap_label(tr("props.wave.form")), form_wrap)

        if not isinstance(element, OscilloscopeElement):
            bar_sl = QSlider(Qt.Orientation.Horizontal)
            bar_sl.setRange(1, 256)
            bar_sl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bar_sl.setMinimumHeight(32 if app_settings.ui_theme() == "glass" else 26)
            bar_sl.setValue(max(1, min(256, int(getattr(element, "spectrum_bar_count", 128)))))
            bar_lbl = QLabel(str(bar_sl.value()))
            bar_lbl.setMinimumWidth(36)
            bar_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            def _on_bars(v: int) -> None:
                iv = max(1, min(256, int(v)))
                element.spectrum_bar_count = iv
                bar_lbl.setText(str(iv))
                element._spectrum_hold = None
                element.update()

            bar_sl.valueChanged.connect(_on_bars)
            bar_wrap = QWidget()
            bwl = QHBoxLayout(bar_wrap)
            bwl.setContentsMargins(0, 0, 0, 0)
            bwl.setSpacing(8)
            bwl.addWidget(bar_sl, 1)
            bwl.addWidget(bar_lbl, 0)
            bars_block = QWidget()
            bvb = QVBoxLayout(bars_block)
            bvb.setContentsMargins(0, 0, 0, 0)
            bvb.setSpacing(2)
            bvb.addWidget(bar_wrap)
            bvb.addWidget(self._hint_one_line(tr("props.wave.bars_hint")))
            form.addRow(self._wrap_label(tr("props.wave.bars")), self._prep_field(bars_block))

            gap_sl = QSlider(Qt.Orientation.Horizontal)
            gap_sl.setRange(0, 100)
            gap_sl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            gap_sl.setMinimumHeight(32 if app_settings.ui_theme() == "glass" else 26)
            g0 = float(getattr(element, "spectrum_step_gap", 0.0))
            gap_sl.setValue(max(0, min(100, int(round(g0 / 0.95 * 100.0)))))

            def _on_gap(v: int) -> None:
                iv = max(0, min(100, int(v)))
                element.spectrum_step_gap = iv / 100.0 * 0.95
                element._spectrum_hold = None
                element.update()

            gap_sl.valueChanged.connect(_on_gap)
            gap_wrap = QWidget()
            gpl = QHBoxLayout(gap_wrap)
            gpl.setContentsMargins(0, 0, 0, 0)
            gpl.setSpacing(8)
            gpl.addWidget(gap_sl, 1)
            gap_block = QWidget()
            gvb = QVBoxLayout(gap_block)
            gvb.setContentsMargins(0, 0, 0, 0)
            gvb.setSpacing(2)
            gvb.addWidget(gap_wrap)
            gvb.addWidget(self._hint_one_line(tr("props.wave.gap_hint")))
            form.addRow(self._wrap_label(tr("props.wave.gap")), self._prep_field(gap_block))

        dec_sl = QSlider(Qt.Orientation.Horizontal)
        dec_sl.setRange(0, 2000)
        dec_sl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dec_sl.setMinimumHeight(32 if app_settings.ui_theme() == "glass" else 26)

        def _decay_ms_from_slider(v: int) -> float:
            if v <= 0:
                return 0.0
            if v == 1:
                return 100.0
            return 100.0 + (float(v) - 1.0) * (2000.0 - 100.0) / (2000.0 - 1.0)

        def _slider_from_decay_ms(ms: float) -> int:
            if ms <= 0.0:
                return 0
            m = max(100.0, min(2000.0, float(ms)))
            return 1 + int(round((m - 100.0) * (2000.0 - 1.0) / (2000.0 - 100.0)))

        dec_sl.setValue(_slider_from_decay_ms(float(getattr(element, "visual_decay_ms", 0.0))))
        dec_txt = QLabel()
        dec_txt.setMinimumWidth(72)
        dec_txt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def _refresh_dec_lbl() -> None:
            v = int(dec_sl.value())
            if v <= 0:
                dec_txt.setText(tr("props.wave.decay_off"))
            else:
                dec_txt.setText(tr("props.wave.decay_ms", ms=int(round(_decay_ms_from_slider(v)))))

        def _on_dec(v: int) -> None:
            element.visual_decay_ms = _decay_ms_from_slider(int(v))
            _refresh_dec_lbl()
            element.update()

        dec_sl.valueChanged.connect(_on_dec)
        _refresh_dec_lbl()
        dec_wrap = QWidget()
        dwl = QHBoxLayout(dec_wrap)
        dwl.setContentsMargins(0, 0, 0, 0)
        dwl.setSpacing(8)
        dwl.addWidget(dec_sl, 1)
        dwl.addWidget(dec_txt, 0)
        dec_block = QWidget()
        dvb = QVBoxLayout(dec_block)
        dvb.setContentsMargins(0, 0, 0, 0)
        dvb.setSpacing(2)
        dvb.addWidget(dec_wrap)
        dvb.addWidget(self._hint_one_line(tr("props.wave.decay_hint")))
        form.addRow(self._wrap_label(tr("props.wave.decay")), self._prep_field(dec_block))

        group.setLayout(form)
        self.scroll_layout.addWidget(group)

    def _setup_oscilloscope_properties(self, element: OscilloscopeElement):
        self._setup_wave_properties(element, title=tr("props.osc"), show_smoothing=True)
    
    def _setup_text_properties(self, element: TextElement):
        group = QGroupBox(tr("props.text"))
        form = self._form()
        
        # Текст
        text_edit = QLineEdit(element.text)
        text_edit.textChanged.connect(lambda v: setattr(element, 'text', v) or element.update())
        form.addRow(self._wrap_label(tr("props.text.content")), self._prep_field(text_edit))
        
        # Размер шрифта
        font_size_spin = QSpinBox()
        font_size_spin.setRange(8, 200)
        font_size_spin.setValue(element.base_font_size)

        def _on_font_size(v: int) -> None:
            element.base_font_size = int(v)
            element.font.setPointSize(int(v))
            element.update()

        font_size_spin.valueChanged.connect(_on_font_size)
        form.addRow(self._wrap_label(tr("props.text.font_size")), self._prep_field(font_size_spin))
        
        # Цвет
        color_btn = QPushButton(tr("btn.choose_color"))
        color_btn.clicked.connect(lambda: self._select_text_color(element))
        form.addRow(self._wrap_label(tr("props.color")), color_btn)
        
        anim_combo = QComboBox()
        for val in ("pulse", "wave", "bounce", "glow"):
            anim_combo.addItem(animation_label(val), val)
        ai = anim_combo.findData(element.animation_type)
        anim_combo.setCurrentIndex(max(0, ai))

        _el_ref = weakref.ref(element)

        def _set_preview(on: bool) -> None:
            el = _el_ref()
            if el is None:
                return
            try:
                el.set_ui_anim_preview(bool(on))
            except RuntimeError:
                return
            except Exception:
                return

        class _PreviewFilter(QObject):
            def eventFilter(self, obj, ev):
                try:
                    t = ev.type()
                    if t in (QEvent.Type.Enter, QEvent.Type.FocusIn):
                        _set_preview(True)
                    elif t in (QEvent.Type.Leave, QEvent.Type.FocusOut):
                        _set_preview(False)
                except Exception:
                    pass
                return False

        pf = _PreviewFilter(anim_combo)
        anim_combo.installEventFilter(pf)
        try:
            anim_combo.view().viewport().installEventFilter(pf)
        except Exception:
            pass
        anim_combo._preview_filter = pf  # type: ignore[attr-defined]

        def _on_anim(_i: int) -> None:
            d = anim_combo.currentData()
            if d is not None:
                element.animation_type = str(d)
                element.update()

        anim_combo.currentIndexChanged.connect(_on_anim)
        self._prepare_animation_combo(anim_combo)
        form.addRow(self._wrap_label(tr("props.text.anim")), self._prep_field(anim_combo))

        self._form_add_smoothing_passes(form, element)
        
        group.setLayout(form)
        self.scroll_layout.addWidget(group)
    
    def _setup_trackname_properties(self, element: TrackNameElement):
        self._setup_text_properties(element)
    
    def _setup_line_properties(self, element: LineElement):
        group = QGroupBox(tr("props.line"))
        form = self._form()
        
        # Цвет
        color_btn = QPushButton(tr("btn.choose_color"))
        color_btn.clicked.connect(lambda: self._select_color(element))
        form.addRow(self._wrap_label(tr("props.color")), color_btn)
        
        # Толщина
        width_spin = QDoubleSpinBox()
        width_spin.setRange(1.0, 20.0)
        width_spin.setValue(element.line_width)
        width_spin.valueChanged.connect(lambda v: setattr(element, 'line_width', v) or element.update())
        form.addRow(self._wrap_label(tr("props.width")), self._prep_field(width_spin))

        self._form_add_smoothing_passes(form, element)

        anim_combo = QComboBox()
        for val in ("wave", "pulse", "glow"):
            anim_combo.addItem(animation_label(val), val)
        ai = anim_combo.findData(element.animation_type)
        anim_combo.setCurrentIndex(max(0, ai))

        _el_ref = weakref.ref(element)

        def _set_preview(on: bool) -> None:
            el = _el_ref()
            if el is None:
                return
            try:
                el.set_ui_anim_preview(bool(on))
            except RuntimeError:
                return
            except Exception:
                return

        class _PreviewFilter(QObject):
            def eventFilter(self, obj, ev):
                try:
                    t = ev.type()
                    if t in (QEvent.Type.Enter, QEvent.Type.FocusIn):
                        _set_preview(True)
                    elif t in (QEvent.Type.Leave, QEvent.Type.FocusOut):
                        _set_preview(False)
                except Exception:
                    pass
                return False

        pf = _PreviewFilter(anim_combo)
        anim_combo.installEventFilter(pf)
        try:
            anim_combo.view().viewport().installEventFilter(pf)
        except Exception:
            pass
        anim_combo._preview_filter = pf  # type: ignore[attr-defined]

        def _on_la(_i: int) -> None:
            d = anim_combo.currentData()
            if d is not None:
                element.animation_type = str(d)
                element.update()

        anim_combo.currentIndexChanged.connect(_on_la)
        self._prepare_animation_combo(anim_combo)
        form.addRow(self._wrap_label(tr("props.line.anim")), self._prep_field(anim_combo))
        
        group.setLayout(form)
        self.scroll_layout.addWidget(group)

    def _setup_video_properties(self, element: VideoElement) -> None:
        group = QGroupBox(tr("props.video"))
        form = self._form()
        path_edit = QLineEdit(element.video_path or "")
        path_edit.setMinimumWidth(0)
        path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn = QPushButton(tr("btn.choose_file"))
        mw = self.window() or self

        def _pick() -> None:
            p, _ = QFileDialog.getOpenFileName(
                qfile_dialog_parent_for_modal(mw),
                tr("dialog.pick_video"),
                documents_directory(),
                tr("dialog.filter.video"),
                "",
                qfile_dialog_options_stable(),
            )
            if not p:
                return
            path_edit.setText(p)
            element.video_path = p
            try:
                element.open_video(p, mw)
            except Exception:
                pass

        btn.clicked.connect(_pick)
        form.addRow(self._wrap_label(tr("props.video.file")), self._prep_field(path_edit))
        form.addRow("", btn)

        br = QDoubleSpinBox()
        br.setRange(0.05, 4.0)
        br.setDecimals(2)
        br.setSingleStep(0.05)
        br.setValue(float(getattr(element, "playback_rate_base", 1.0)))
        br.valueChanged.connect(lambda v: setattr(element, "playback_rate_base", float(v)))

        ag = QDoubleSpinBox()
        ag.setRange(0.0, 3.0)
        ag.setDecimals(2)
        ag.setSingleStep(0.05)
        ag.setValue(float(getattr(element, "playback_rate_audio_gain", 0.85)))
        ag.valueChanged.connect(lambda v: setattr(element, "playback_rate_audio_gain", float(v)))

        form.addRow(self._wrap_label(tr("props.video.rate_base")), self._prep_field(br))
        form.addRow(self._wrap_label(tr("props.video.rate_audio")), self._prep_field(ag))

        group.setLayout(form)
        self.scroll_layout.addWidget(group)

    def _setup_milkdrop_properties(self, element: MilkdropElement) -> None:
        from elements.milkdrop_element import default_projectm_textures_dir

        group = QGroupBox(tr("props.milkdrop"))
        form = self._form()
        pe = QLineEdit(element.preset_path or "")
        pe.setMinimumWidth(0)
        pe.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mw = self.window() or self

        def _pick_milk() -> None:
            start = (element.preset_path or "").strip() or documents_directory()
            p, _ = QFileDialog.getOpenFileName(
                qfile_dialog_parent_for_modal(mw),
                tr("dialog.pick_milk"),
                start,
                tr("dialog.filter.milk"),
                "",
                qfile_dialog_options_stable(),
            )
            if p:
                pe.setText(p)
                element.preset_path = p
                element.update()

        pb = QPushButton(tr("btn.choose_file"))
        pb.clicked.connect(_pick_milk)
        form.addRow(self._wrap_label(tr("props.milkdrop.preset")), self._prep_field(pe))
        form.addRow("", pb)

        te = QLineEdit(element.textures_dir or "")
        te.setMinimumWidth(0)
        te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        def _pick_tex() -> None:
            d = QFileDialog.getExistingDirectory(
                qfile_dialog_parent_for_modal(mw),
                tr("props.milkdrop.textures"),
                te.text() or default_projectm_textures_dir() or documents_directory(),
                QFileDialog.Option.ShowDirsOnly,
            )
            if d:
                te.setText(d)
                element.textures_dir = d
                element.update()

        tb = QPushButton(tr("btn.browse"))
        tb.clicked.connect(_pick_tex)
        form.addRow(self._wrap_label(tr("props.milkdrop.textures")), self._prep_field(te))
        form.addRow("", tb)

        group.setLayout(form)
        self.scroll_layout.addWidget(group)
    
    def _select_color(self, element):
        color = QColorDialog.getColor(element.color, self, tr("btn.choose_color"))
        if color.isValid():
            element.color = color
            element.update()
    
    def _select_text_color(self, element: TextElement):
        color = QColorDialog.getColor(element.color, self, tr("btn.choose_color"))
        if color.isValid():
            element.color = color
            element.update()
    
    def _add_frequency_range_ui(self, element: BaseVisualizationElement):
        """Диапазоны частот: логарифмическая шкала, два маркера «от / до» на строку + пресеты."""
        block_gen = self._props_ui_generation
        group = QGroupBox(tr("props.freq"))
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._hint_one_line(tr("props.freq.hint")))

        rows_wrap = QWidget()
        rows_v = QVBoxLayout(rows_wrap)
        rows_v.setContentsMargins(0, 0, 0, 0)
        rows_v.setSpacing(8)

        slider_widgets: list[DualLogFreqRangeSlider] = []

        def _apply_sliders_to_element() -> None:
            if self._props_ui_generation != block_gen:
                return
            if self.current_element is not element:
                return
            try:
                if element.scene() is None:
                    return
            except RuntimeError:
                return
            new_ranges: list[tuple[float, float]] = []
            for w in list(slider_widgets):
                try:
                    lo, hi = w.range_hz()
                except RuntimeError:
                    continue
                if hi > lo:
                    new_ranges.append((lo, hi))
            element.frequency_ranges = new_ranges
            try:
                element.update()
            except RuntimeError:
                pass

        def _schedule_apply() -> None:
            if self._props_ui_generation != block_gen:
                return
            if self.current_element is not element:
                return

            def _deferred() -> None:
                try:
                    if self._props_ui_generation != block_gen:
                        return
                    if self.current_element is not element:
                        return
                    _apply_sliders_to_element()
                except Exception:
                    return

            QTimer.singleShot(120, _deferred)

        def _rebuild_rows() -> None:
            if self._props_ui_generation != block_gen:
                return
            if self.current_element is not element:
                return
            slider_widgets.clear()
            while rows_v.count():
                item = rows_v.takeAt(0)
                wdg = item.widget()
                if wdg is not None:
                    wdg.deleteLater()

            for i, (a, b) in enumerate(list(element.frequency_ranges)):
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(6)
                s = DualLogFreqRangeSlider(float(a), float(b))
                s.valueChanged.connect(_schedule_apply)
                slider_widgets.append(s)
                hl.addWidget(s, 1)

                rm = QPushButton("×")
                rm.setObjectName("freqRemoveBtn")
                rm.setFixedSize(32, 32)
                rm.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                rm.setToolTip(tr("freq.remove_row"))
                # Глобальный QSS даёт padding у QPushButton — при узкой ширине «×» пропадает.
                rm.setStyleSheet(_freq_remove_btn_stylesheet())

                def _remove_at(_checked: bool = False, idx: int = i) -> None:
                    if self._props_ui_generation != block_gen:
                        return
                    if self.current_element is not element:
                        return
                    if idx < 0 or idx >= len(element.frequency_ranges):
                        return
                    element.frequency_ranges.pop(idx)
                    try:
                        if element.scene() is not None:
                            element.update()
                    except Exception:
                        pass
                    QTimer.singleShot(0, _rebuild_rows)

                rm.clicked.connect(_remove_at)
                hl.addWidget(rm, 0)
                rows_v.addWidget(row)

        _rebuild_rows()
        layout.addWidget(rows_wrap)

        # Кнопки пресетов: вместо одной длинной строки (которая раздувает ширину)
        # укладываем в сетку.
        presets = QGridLayout()
        presets.setContentsMargins(0, 0, 0, 0)
        presets.setHorizontalSpacing(6)
        presets.setVerticalSpacing(6)
        col = 0
        row = 0
        for label_key, pair in (
            ("freq.preset.bass", (20.0, 250.0)),
            ("freq.preset.mid", (250.0, 4000.0)),
            ("freq.preset.high", (4000.0, 20000.0)),
        ):
            btn = QPushButton(tr(label_key))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            _pf = QFont(btn.font())
            _pf.setPointSize(9)
            btn.setFont(_pf)
            btn.setMinimumHeight(28)

            def _add_preset(_checked: bool = False, p=pair) -> None:
                if self._props_ui_generation != block_gen:
                    return
                if self.current_element is not element:
                    return
                element.frequency_ranges.append((p[0], p[1]))

                def _deferred_sync() -> None:
                    try:
                        if self._props_ui_generation != block_gen:
                            return
                        if self.current_element is not element:
                            return
                        _rebuild_rows()
                    except Exception:
                        return

                QTimer.singleShot(0, _deferred_sync)
                try:
                    if element.scene() is not None:
                        element.update()
                except Exception:
                    pass

            btn.clicked.connect(_add_preset)
            presets.addWidget(btn, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1

        def _add_empty_row(_checked: bool = False) -> None:
            if self._props_ui_generation != block_gen:
                return
            if self.current_element is not element:
                return
            element.frequency_ranges.append((100.0, 500.0))

            def _deferred_sync() -> None:
                try:
                    if self._props_ui_generation != block_gen:
                        return
                    if self.current_element is not element:
                        return
                    _rebuild_rows()
                except Exception:
                    return

            QTimer.singleShot(0, _deferred_sync)
            try:
                if element.scene() is not None:
                    element.update()
            except Exception:
                pass

        add_row_btn = QPushButton(tr("freq.add_row"))
        add_row_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_row_btn.setMinimumHeight(28)
        add_row_btn.clicked.connect(_add_empty_row)
        presets.addWidget(add_row_btn, row, col)
        col += 1
        if col >= 2:
            col = 0
            row += 1

        presets_wrap = QWidget()
        presets_wrap.setLayout(presets)
        presets_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(presets_wrap)

        group.setLayout(layout)
        self.scroll_layout.addWidget(group)
