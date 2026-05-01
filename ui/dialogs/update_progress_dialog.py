"""
ui/dialogs/update_progress_dialog.py
Diálogo para exibição do progresso de download e instalação da atualização.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton
)
from PyQt6.QtCore import Qt


class UpdateProgressDialog(QDialog):
    """
    Diálogo modal que mostra o progresso do download da atualização.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atualizando Downloader")
        self.setFixedSize(400, 150)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.status_label = QLabel("Preparando download...")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.close_btn = QPushButton("Fechar")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def update_progress(self, message: str):
        """
        Atualiza o texto de status e tenta extrair o percentual da mensagem.
        Mensagem esperada: "Baixando atualização... X%" ou "Instalando..."
        """
        self.status_label.setText(message)
        
        if "%" in message:
            try:
                # Tenta extrair o número antes do %
                parts = message.split("...")
                if len(parts) > 1:
                    pct_str = parts[1].replace("%", "").strip()
                    pct = int(pct_str)
                    self.progress_bar.setValue(pct)
            except Exception:
                pass
        elif "Instalando" in message:
            self.progress_bar.setRange(0, 0)  # Indeterminado

    def finish(self, success: bool, message: str):
        """Finaliza o diálogo com o status final."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if success else 0)
        self.status_label.setText(message)
        self.close_btn.setEnabled(True)
        if success:
            self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
