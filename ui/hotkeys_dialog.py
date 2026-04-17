"""Список горячих клавиш редактора."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

from app.i18n import tr


class HotkeysDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("hotkeys.title"))
        self.setModal(True)
        self.resize(520, 460)
        lay = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(False)
        browser.setPlainText(tr("hotkeys.body"))
        lay.addWidget(browser, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton(tr("btn.ok"), self)
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
        try:
            self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        except Exception:
            pass
