"""
ui/download_tab.py
Aba principal de downloads.
"""

import json
import os
from urllib.parse import urlparse

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QSpinBox, QLabel, QProgressBar,
    QTextEdit, QFileDialog, QGroupBox, QFrame
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon

from core.file_utils import get_default_download_dir, resolve_output_path
from ui.widgets.speed_chart import SpeedChartWidget
from ui.widgets.segments_map import SegmentsMapWidget


class DownloadTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self.custom_headers = {}

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 14, 16, 14)

        # ── Configuração ────────────────────────────────────
        input_group = QGroupBox("Configuração do Download")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(9)
        input_layout.setContentsMargins(15, 8, 15, 8)

        url_row = QHBoxLayout()
        lbl_url = QLabel("URL")
        lbl_url.setFixedWidth(68)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Cole a URL ou o JSON do interceptor aqui...")
        self.url_input.textChanged.connect(self._on_url_changed)
        url_row.addWidget(lbl_url)
        url_row.addWidget(self.url_input)
        input_layout.addLayout(url_row)

        path_row = QHBoxLayout()
        lbl_path = QLabel("Salvar em")
        lbl_path.setFixedWidth(68)
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Caminho de salvamento (Padrão: Downloads)")
        self.browse_btn = QPushButton("Procurar...")
        self.browse_btn.setObjectName("browse_btn")
        self.browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(lbl_path)
        path_row.addWidget(self.path_input)
        path_row.addWidget(self.browse_btn)
        input_layout.addLayout(path_row)

        opts_row = QHBoxLayout()
        lbl_thr = QLabel("Threads")
        lbl_thr.setFixedWidth(68)
        self.threads_input = QSpinBox()
        self.threads_input.setRange(1, 4096)
        self.threads_input.setValue(512)
        opts_row.addWidget(lbl_thr)
        opts_row.addWidget(self.threads_input)
        opts_row.addSpacing(16)
        lbl_chk = QLabel("Checksum")
        self.checksum_input = QLineEdit()
        self.checksum_input.setPlaceholderText("SHA256 opcional para verificação")
        opts_row.addWidget(lbl_chk)
        opts_row.addWidget(self.checksum_input)
        input_layout.addLayout(opts_row)

        layout.addWidget(input_group)

        # ── Controles ────────────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        # Caminho base para os ícones
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")

        self.start_btn = QPushButton("Iniciar download")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.setIcon(QIcon(os.path.join(assets_dir, "play.svg")))
        self.start_btn.setIconSize(QSize(20, 20))

        self.pause_btn = QPushButton("Pausar")
        self.pause_btn.setObjectName("pause_btn")
        self.pause_btn.setIcon(QIcon(os.path.join(assets_dir, "pause.svg")))
        self.pause_btn.setIconSize(QSize(18, 18))
        self.pause_btn.setEnabled(False)

        self.stop_btn = QPushButton("Parar")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setIcon(QIcon(os.path.join(assets_dir, "stop.svg")))
        self.stop_btn.setIconSize(QSize(18, 18))
        self.stop_btn.setEnabled(False)

        ctrl_row.addWidget(self.start_btn, 2)
        ctrl_row.addWidget(self.pause_btn, 1)
        ctrl_row.addWidget(self.stop_btn, 1)
        layout.addLayout(ctrl_row)

        # ── Progress bar ─────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)   # texto via label abaixo
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)

        # ── Mapa de segmentos ────────────────────────────────
        self.segments_map = SegmentsMapWidget()
        layout.addWidget(self.segments_map)

        # ── Estatísticas ─────────────────────────────────────
        stats_frame = QFrame()
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(0, 4, 0, 4)

        self.speed_label    = QLabel("Velocidade  —")
        self.eta_label      = QLabel("Restante  —")

        for lbl in (self.speed_label, self.eta_label):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stats_layout.addWidget(self.speed_label)
        stats_layout.addWidget(self.eta_label)
        layout.addWidget(stats_frame)

        # ── Gráfico de velocidade ────────────────────────────
        self.speed_chart = SpeedChartWidget()
        layout.addWidget(self.speed_chart)

        # ── Log ──────────────────────────────────────────────
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(140)
        layout.addWidget(self.log_output)

    # ─────────────────────────────────────────────────────────
    def _on_url_changed(self, text):
        text = text.strip()
        if text.startswith('{') and '"url"' in text:
            try:
                data = json.loads(text)
                url = data.get("url", "")
                self.custom_headers = data.get("headers", {})
                self.url_input.blockSignals(True)
                self.url_input.setText(url)
                self.url_input.blockSignals(False)
                self.add_log("Headers customizados importados do interceptor.", "success")
            except Exception:
                pass

        if not self.path_input.text() and self.url_input.text():
            url = self.url_input.text()
            filename = os.path.basename(urlparse(url).path) or "download.bin"
            default_path = os.path.join(get_default_download_dir(), filename)
            self.path_input.setPlaceholderText(default_path)

    def _on_browse(self):
        url = self.url_input.text()
        default_dir = get_default_download_dir()
        filename = os.path.basename(urlparse(url).path) or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar Arquivo", os.path.join(default_dir, filename)
        )
        if path:
            self.path_input.setText(path)

    def add_log(self, message, level="info"):
        from datetime import datetime
        ts = datetime.now().strftime("[%H:%M:%S]")
        colors = {
            "info":    "#5c6a94",
            "warning": "#f0a832",
            "error":   "#e8475f",
            "success": "#22c97a",
        }
        color = colors.get(level, "#5c6a94")
        html = (
            f'<span style="color:#2e364f;">{ts}</span> '
            f'<span style="color:{color};">{message}</span>'
        )
        self.log_output.append(html)
        self.log_output.ensureCursorVisible()

    def update_ui_with_snapshot(self, snap: dict):
        spd = snap['current_speed'] / (1024 * 1024)
        self.speed_label.setText(f"Velocidade  {spd:.2f} MB/s")
        self.eta_label.setText(f"Restante  {snap['eta']}")

        ratio = snap['progress_ratio']
        if ratio is not None:
            self.progress_bar.setValue(int(ratio * 100))

        self.speed_chart.set_history(
            snap['chart_points'],
            snap['peak_speed'],
        )
