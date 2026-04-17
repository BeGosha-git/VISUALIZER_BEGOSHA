"""
Диалог со справкой по использованию приложения (безрамочное окно в стиле приложения).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.theme_qss import theme_corner_radius_css
from app.version import __version__
from config.app_settings import settings


def _help_html_ru() -> str:
    return f"""
<html><body style="color:#c8c8c8; font-size:13px;">
<p style="margin-top:0;"><b>{tr("app.title")}</b> · версия {__version__}</p>

<p><b>Создание сцены</b></p>
<ul style="margin-left:1.2em;">
<li>Слева — кнопки элементов. Нажмите, чтобы добавить объект на холст.</li>
<li>По центру — холст с рамкой разрешения. Объекты перетаскивайте мышью.</li>
<li>Справа — свойства: цвет, чувствительность, при необходимости частоты.</li>
<li>Размер — синие маркеры по контуру. Мягкая привязка к краям области и к другим объектам; <b>Alt</b> отключает привязку при перетаскивании и изменении размера.</li>
<li>Колёсико — масштаб вида. Средняя кнопка — сдвиг вида.</li>
<li>Правая кнопка по объекту: отражение, вписать в область, дублирование, порядок слоёв, удаление.</li>
<li>Инструмент линия: точки по клику; <b>Esc</b> — отмена.</li>
</ul>

<p><b>Просмотр</b></p>
<ul style="margin-left:1.2em;">
<li>Кнопка «Просмотр» в левой панели — режим с захватом системного звука.</li>
<li>Выберите устройство вывода с поддержкой записи (петля/стерео микшер).</li>
<li>{tr("help.f11")} Кнопка «Назад в редактор» — в панели просмотра.</li>
</ul>

<p><b>Настройки и файлы</b></p>
<ul style="margin-left:1.2em;">
<li>Кнопка ⚙ — порог тишины, пути к треку, визуализация, язык интерфейса.</li>
<li>Сохранение и открытие проекта — кнопки слева внизу (файл JSON).</li>
</ul>

<p style="color:#707070;font-size:12px;">{tr("help.chrome_note")}</p>

<p style="color:#808080;">{tr("help.footer")}</p>
<p style="text-align:right; color:#5a5a5a; font-size:13px; margin-top:8px; letter-spacing:0.05em;">{tr("help.author")}</p>
</body></html>
"""


def _help_html_en() -> str:
    return f"""
<html><body style="color:#c8c8c8; font-size:13px;">
<p style="margin-top:0;"><b>{tr("app.title")}</b> · version {__version__}</p>

<p><b>Building a scene</b></p>
<ul style="margin-left:1.2em;">
<li>Left: element buttons — click to add to the canvas.</li>
<li>Center: canvas with the resolution frame. Drag items with the mouse.</li>
<li>Right: properties — color, sensitivity, optional frequency bands.</li>
<li>Resize with blue handles. Soft snapping to the frame and other items; hold <b>Alt</b> to disable snapping while dragging or resizing.</li>
<li>Wheel — zoom view. Middle button — pan.</li>
<li>Right-click an item: flip, fit to area, duplicate, layer order, delete.</li>
<li>Line tool: click points; <b>Esc</b> — cancel.</li>
</ul>

<p><b>Playback</b></p>
<ul style="margin-left:1.2em;">
<li>“Playback” on the left starts capture from system audio.</li>
<li>Pick an output device with loopback / stereo mix.</li>
<li>{tr("help.f11")} Use the back button in playback to return.</li>
</ul>

<p><b>Settings and files</b></p>
<ul style="margin-left:1.2em;">
<li>⚙ — silence threshold, track paths, visualization, interface language.</li>
<li>Save and open project — buttons at the bottom left (JSON file).</li>
</ul>

<p style="color:#707070;font-size:12px;">{tr("help.chrome_note")}</p>

<p style="color:#808080;">{tr("help.footer")}</p>
<p style="text-align:right; color:#5a5a5a; font-size:13px; margin-top:8px; letter-spacing:0.05em;">{tr("help.author")}</p>
</body></html>
"""


class _GuideTitleBar(QWidget):
    """Полоса заголовка: перетаскивание окна и закрытие."""

    def __init__(self, dialog: QDialog) -> None:
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
        lbl = QLabel(tr("help.title"))
        lbl.setStyleSheet("color: #d0d0d0; font-size: 14px; font-weight: bold;")
        lay.addWidget(lbl)
        lay.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(42, 34)
        close_btn.setToolTip(tr("titlebar.tooltip.close"))
        _br = theme_corner_radius_css()
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: #b0b0b0;
                font-size: 20px;
                padding: 4px 10px;
                border-radius: {_br};
            }}
            QPushButton:hover {{
                background: #2a2a2a;
                color: #ffffff;
                border-radius: {_br};
            }}
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
        if (
            event.buttons() == Qt.MouseButton.LeftButton
            and self._drag_pos is not None
        ):
            self._dialog.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


class UserGuideDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("help.title"))
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setModal(True)
        self.setMinimumSize(520, 420)
        self.resize(560, 480)
        self.setStyleSheet("QDialog { background-color: #0a0a0a; }")

        html = _help_html_en() if settings.language() == "en" else _help_html_ru()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        panel = QWidget()
        panel.setObjectName("helpPanel")
        _panel_br = theme_corner_radius_css()
        panel.setStyleSheet(
            f"""
            QWidget#helpPanel {{
                background-color: #0a0a0a;
                border: 1px solid #2a2a2a;
                border-radius: {_panel_br};
            }}
        """
        )
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        inner.addWidget(_GuideTitleBar(self))

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        _inner_br = theme_corner_radius_css()
        browser.setStyleSheet(
            f"""
            QTextBrowser {{
                background: #121212;
                border: none;
                border-radius: {_inner_br};
                padding: 10px 12px;
            }}
        """
        )

        ok = QPushButton(tr("btn.ok"))
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.setContentsMargins(12, 10, 12, 12)
        row.addStretch()
        row.addWidget(ok)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(browser, 1)
        body.addLayout(row)

        inner.addLayout(body, 1)
        root.addWidget(panel, 1)
