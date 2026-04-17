"""
Кастомная панель заголовка
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel

from app.i18n import tr
from app.theme_qss import theme_corner_radius_css


class CustomTitleBar(QWidget):
    """Кастомная панель заголовка"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(52)
        self.setStyleSheet("""
            QWidget {
                background-color: #0a0a0a;
                color: #e0e0e0;
                border-bottom: 1px solid #1a1a1a;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(4)
        
        self.title_label = QLabel(tr("app.title"))
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: normal;
                color: #909090;
                padding-left: 5px;
            }
        """)
        layout.addWidget(self.title_label)
        
        layout.addStretch()

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(46, 38)
        self.settings_btn.setToolTip(tr("titlebar.tooltip.settings"))

        self.about_btn = QPushButton("?")
        self.about_btn.setFixedSize(46, 38)
        self.about_btn.setToolTip(tr("titlebar.tooltip.help"))

        layout.addWidget(self.settings_btn)
        layout.addWidget(self.about_btn)

        # Кнопки управления окном
        self.minimize_btn = QPushButton("−")
        self.minimize_btn.setToolTip(tr("titlebar.tooltip.minimize"))
        self.minimize_btn.setFixedSize(48, 38)
        self.minimize_btn.clicked.connect(self.parent_window.showMinimized)

        # Развернуть / восстановить (максимизация, не fullscreen)
        self.maximize_btn = QPushButton("□")
        self.maximize_btn.setToolTip(tr("titlebar.tooltip.maximize"))
        self.maximize_btn.setFixedSize(48, 38)
        self.maximize_btn.clicked.connect(self._toggle_maximize)

        self.close_btn = QPushButton("×")
        self.close_btn.setToolTip(tr("titlebar.tooltip.close"))
        self.close_btn.setFixedSize(48, 38)
        self.close_btn.clicked.connect(self.parent_window.close)
        
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.maximize_btn)
        layout.addWidget(self.close_btn)

        # Подключения задаёт MainWindow (open_settings / show_about).

        self.setLayout(layout)
        self.refresh_theme_style()

    def refresh_theme_style(self) -> None:
        r = theme_corner_radius_css()
        icon_btn = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: #b0b0b0;
                padding: 6px 12px;
                min-width: 40px;
                min-height: 34px;
                border-radius: {r};
            }}
            QPushButton:hover {{
                background-color: #1a1a1a;
                color: #e0e0e0;
                border-radius: {r};
            }}
        """
        self.settings_btn.setStyleSheet(
            icon_btn
            + """
            QPushButton {
                font-size: 18px;
                font-family: "Segoe UI Symbol", "Segoe UI", sans-serif;
            }
        """
        )
        self.about_btn.setStyleSheet(
            icon_btn
            + """
            QPushButton {
                font-size: 17px;
                font-weight: bold;
            }
        """
        )
        self.minimize_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: #b0b0b0;
                font-size: 18px;
                font-weight: bold;
                padding: 6px 14px;
                min-height: 34px;
                border-radius: {r};
            }}
            QPushButton:hover {{
                background-color: #1a1a1a;
                color: #e0e0e0;
                border-radius: {r};
            }}
        """
        )
        self.maximize_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: #b0b0b0;
                font-size: 16px;
                font-weight: bold;
                padding: 6px 14px;
                min-height: 34px;
                border-radius: {r};
            }}
            QPushButton:hover {{
                background-color: #1a1a1a;
                color: #e0e0e0;
                border-radius: {r};
            }}
        """
        )
        self.close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: #b0b0b0;
                font-size: 20px;
                font-weight: bold;
                padding: 6px 14px;
                min-height: 34px;
                border-radius: {r};
            }}
            QPushButton:hover {{
                background-color: #e81123;
                color: white;
                border-radius: {r};
            }}
        """
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_position'):
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _toggle_maximize(self) -> None:
        try:
            if hasattr(self.parent_window, "toggle_maximize"):
                self.parent_window.toggle_maximize()
            else:
                if self.parent_window.isMaximized():
                    self.parent_window.showNormal()
                else:
                    self.parent_window.showMaximized()
        except Exception:
            pass

    def refresh_window_buttons(self) -> None:
        """Обновить подсказки/иконку при смене состояния окна."""
        try:
            if self.parent_window.isMaximized():
                self.maximize_btn.setToolTip(tr("titlebar.tooltip.restore"))
            else:
                self.maximize_btn.setToolTip(tr("titlebar.tooltip.maximize"))
        except Exception:
            pass
