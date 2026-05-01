"""
ui/dialogs/update_dialog.py
Diálogo visual para informar sobre novas versões disponíveis.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, 
    QTextEdit, QHBoxLayout
)
from PyQt6.QtCore import Qt


class UpdateDialog(QDialog):
    """
    Exibe informações sobre uma nova atualização disponível.
    """

    def __init__(self, version_info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atualização Disponível")
        self.setMinimumSize(400, 300)
        self.info = version_info
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Título
        title = QLabel(f"Uma nova versão ({self.info.get('version')}) está disponível!")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4caf50;")
        layout.addWidget(title)

        # Changelog
        layout.addWidget(QLabel("O que há de novo:"))
        self.changelog_text = QTextEdit()
        self.changelog_text.setReadOnly(True)
        
        # Formata o changelog (lista de strings no JSON)
        changelog = self.info.get("changelog", [])
        if isinstance(changelog, list):
            text = "\n".join([f"• {item}" for item in changelog])
        else:
            text = str(changelog)
            
        self.changelog_text.setText(text)
        layout.addWidget(self.changelog_text)

        # Botões
        btn_layout = QHBoxLayout()
        self.ignore_btn = QPushButton("Ignorar")
        self.ignore_btn.clicked.connect(self.reject)
        
        self.update_btn = QPushButton("ATUALIZAR AGORA")
        self.update_btn.setStyleSheet("background-color: #4caf50; font-weight: bold;")
        self.update_btn.clicked.connect(self.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.ignore_btn)
        btn_layout.addWidget(self.update_btn)
        layout.addLayout(btn_layout)
