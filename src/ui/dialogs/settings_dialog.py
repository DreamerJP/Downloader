"""
ui/dialogs/settings_dialog.py
Diálogo de configurações avançadas: Proxy, Autenticação e Otimizações.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QLineEdit, QSpinBox, QCheckBox,
    QGroupBox, QDialogButtonBox
)
from PyQt6.QtCore import Qt


class SettingsDialog(QDialog):
    """
    Diálogo para configurar Proxy, Autenticação e parâmetros de performance.
    """

    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(460)
        self.settings = current_settings.copy()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # --- Grupo: Rede ---
        network_group = QGroupBox("Rede e Proxy")
        network_group.setObjectName("settings_group")
        network_form = QFormLayout(network_group)
        self._configure_form(network_form)
        
        self.proxy_edit = QLineEdit(self.settings.get("proxy_url", ""))
        self.proxy_edit.setPlaceholderText("http://usuario:senha@host:porta")
        self.proxy_edit.setClearButtonEnabled(True)
        network_form.addRow("Proxy", self.proxy_edit)
        
        self.conn_timeout = QSpinBox()
        self.conn_timeout.setRange(1, 60)
        self.conn_timeout.setValue(self.settings.get("connect_timeout", 5))
        self.conn_timeout.setSuffix(" s")
        self.conn_timeout.setFixedWidth(110)
        network_form.addRow("Timeout de conexão", self.conn_timeout)
        
        layout.addWidget(network_group)

        # --- Grupo: Autenticação HTTP ---
        auth_group = QGroupBox("Autenticação Básica (Opcional)")
        auth_group.setObjectName("settings_group")
        auth_form = QFormLayout(auth_group)
        self._configure_form(auth_form)
        
        self.auth_user = QLineEdit(self.settings.get("auth_user", ""))
        self.auth_user.setClearButtonEnabled(True)
        auth_form.addRow("Usuário", self.auth_user)
        
        self.auth_pass = QLineEdit(self.settings.get("auth_pass", ""))
        self.auth_pass.setEchoMode(QLineEdit.EchoMode.Password)
        auth_form.addRow("Senha", self.auth_pass)
        
        layout.addWidget(auth_group)

        # --- Grupo: Performance ---
        perf_group = QGroupBox("Otimizações")
        perf_group.setObjectName("settings_group")
        perf_layout = QVBoxLayout(perf_group)
        perf_layout.setContentsMargins(12, 12, 12, 12)
        
        self.x3d_check = QCheckBox("Buffers maiores para AMD Ryzen X3D")
        self.x3d_check.setObjectName("settings_check")
        self.x3d_check.setChecked(self.settings.get("x3d_opt", False))
        self.x3d_check.setToolTip("Usa chunks de 32 MB para aproveitar o cache 3D V-Cache.")
        perf_layout.addWidget(self.x3d_check)
        
        layout.addWidget(perf_group)

        # --- Botões ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("settings_buttons")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _configure_form(form: QFormLayout) -> None:
        form.setContentsMargins(12, 12, 12, 12)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

    def get_settings(self) -> dict:
        """Retorna as configurações modificadas."""
        return {
            "proxy_url": self.proxy_edit.text().strip(),
            "connect_timeout": self.conn_timeout.value(),
            "auth_user": self.auth_user.text().strip(),
            "auth_pass": self.auth_pass.text().strip(),
            "x3d_opt": self.x3d_check.isChecked()
        }
