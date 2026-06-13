"""
ui/chrome_tab.py
Aba de gerenciamento da extensão do Chrome.
Permite instalar os arquivos necessários para o interceptor de downloads.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QGroupBox, QHBoxLayout, QGridLayout, QLineEdit
)
from PyQt6.QtCore import pyqtSignal
from chrome_ext.installer import ChromeExtensionInstaller


class ChromeTab(QWidget):
    # Sinal emitido para avisar a MainWindow sobre mudanças
    status_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.installer = ChromeExtensionInstaller()
        self._init_ui()
        self.refresh_status()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 14, 16, 14)

        desc = QLabel(
            "A extensão do Chrome permite capturar links de downloads protegidos "
            "(como vídeos de streaming) para copiar e usar no Downloader."
        )
        desc.setObjectName("chrome_intro")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        status_group = QGroupBox("Status da Extensão")
        status_layout = QGridLayout(status_group)
        status_layout.setContentsMargins(15, 12, 15, 12)
        status_layout.setHorizontalSpacing(16)
        status_layout.setVerticalSpacing(9)

        self.source_value = QLabel("Verificando")
        self.install_value = QLabel("Verificando")
        self.path_input = QLineEdit()
        self.path_input.setObjectName("chrome_path_field")
        self.path_input.setReadOnly(True)

        status_rows = [
            ("Arquivos fonte", self.source_value),
            ("Instalação no AppData", self.install_value),
            ("Pasta da extensão", self.path_input),
        ]
        for row, (label_text, value_widget) in enumerate(status_rows):
            label = QLabel(label_text)
            label.setObjectName("chrome_field_label")
            if isinstance(value_widget, QLabel):
                value_widget.setObjectName("chrome_status_value")
            status_layout.addWidget(label, row, 0)
            status_layout.addWidget(value_widget, row, 1)
        status_layout.setColumnStretch(1, 1)
        layout.addWidget(status_group)

        actions_group = QGroupBox("Ações")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setContentsMargins(10, 12, 10, 10)
        actions_layout.setSpacing(8)

        self.install_btn = QPushButton("Instalar ou atualizar arquivos")
        self.install_btn.clicked.connect(self._on_install)

        self.chrome_btn = QPushButton("Abrir extensões do Chrome")
        self.chrome_btn.clicked.connect(self.installer.open_chrome_extensions)

        actions_layout.addWidget(self.install_btn)
        actions_layout.addWidget(self.chrome_btn)
        layout.addWidget(actions_group)

        instruct_group = QGroupBox("Instalação Manual")
        instruct_layout = QVBoxLayout(instruct_group)
        instruct_layout.setContentsMargins(15, 12, 15, 12)
        instruct_text = (
            "1. Instale ou atualize os arquivos da extensão.\n"
            "2. Abra a página de extensões do Chrome.\n"
            "3. Ative o Modo do desenvolvedor.\n"
            "4. Selecione Carregar sem compactação.\n"
            "5. Escolha a pasta exibida em Pasta da extensão."
        )
        self.instructions_label = QLabel(instruct_text)
        self.instructions_label.setObjectName("chrome_steps")
        self.instructions_label.setWordWrap(True)
        instruct_layout.addWidget(self.instructions_label)
        layout.addWidget(instruct_group)

        layout.addStretch()

    def refresh_status(self):
        status = self.installer.check_status()

        self._set_status_label(
            self.source_value,
            "Disponível" if status["source_available"] else "Não encontrado",
            ok=status["source_available"],
        )

        self._set_status_label(
            self.install_value,
            "Instalada" if status["installed"] else "Não instalada",
            ok=status["installed"],
        )

        self.path_input.setText(status["path"])
        self.install_btn.setEnabled(status["source_available"])

    @staticmethod
    def _set_status_label(label: QLabel, text: str, ok: bool) -> None:
        label.setText(text)
        label.setObjectName("chrome_status_value" if ok else "chrome_status_warning")
        label.style().unpolish(label)
        label.style().polish(label)

    def _on_install(self):
        if self.installer.install():
            self.refresh_status()
            self.status_changed.emit()
            # Copiar path para o clipboard para facilitar o usuário
            from PyQt6.QtGui import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(self.installer.ext_dest_path)
