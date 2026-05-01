"""
ui/dialogs/about_dialog.py
Diálogo 'Sobre' redesenhado com detalhes técnicos e estética premium.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame, QScrollArea, QWidget
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from core.file_utils import get_resource_path

class AboutDialog(QDialog):
    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre o Downloader")
        self.setFixedSize(450, 580)
        self._init_ui(version)

    def _init_ui(self, version):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── HEADER COM GRADIENTE ───────────────────────────────────────
        header = QFrame()
        header.setObjectName("about_header")
        header.setStyleSheet("""
            QFrame#about_header {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1e30, stop:1 #0f1220);
                border-bottom: 1px solid #1e2438;
            }
        """)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 30, 20, 30)
        header_layout.setSpacing(10)

        # Ícone do App
        icon_label = QLabel()
        try:
            pixmap = QIcon(get_resource_path("ico.ico")).pixmap(QSize(64, 64))
            icon_label.setPixmap(pixmap)
        except:
            pass # Fallback se o ícone não carregar
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(icon_label)

        # Título e Versão
        title = QLabel(f"Downloader v{version}")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #fff; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title)

        subtitle = QLabel("MODULAR HIGH-PERFORMANCE ENGINE")
        subtitle.setStyleSheet("""
            font-size: 10px; 
            color: #3d5aff; 
            font-weight: 700; 
            background: transparent; 
            letter-spacing: 1.5px;
            text-transform: uppercase;
        """)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # ── ÁREA DE CONTEÚDO (SCROLL) ──────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(30, 25, 30, 25)
        content_layout.setSpacing(20)

        # Resumo Técnico
        intro = QLabel(
            "Um gerenciador de downloads modular de alta performance projetado para "
            "máxima eficiência em redes de alta velocidade."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #d8e0f0; font-size: 13px; font-weight: 500; line-height: 1.5;")
        content_layout.addWidget(intro)

        # Divisor
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #1e2438; max-height: 1px;")
        content_layout.addWidget(line)

        # Features Técnicas
        self._add_feature(content_layout, "CORE MULTITHREAD", 
            "Arquitetura paralela massiva com suporte a até 512 conexões simultâneas e algoritmo "
            "de balanceamento de carga para saturação total da largura de banda.")
        
        self._add_feature(content_layout, "SEGMENTAÇÃO ADAPTATIVA", 
            "Divisão dinâmica de arquivos em blocos (256KB a 32MB) otimizada para arquiteturas "
            "de cache L3 modernas, reduzindo o overhead de processamento.")

        self._add_feature(content_layout, "MOTOR HLS/M3U8 PRO", 
            "Parser nativo de streams, download paralelo de segmentos .ts, descriptografia "
            "AES-128 em tempo real e montagem sequencial inteligente.")

        self._add_feature(content_layout, "SMART RAM BUFFER", 
            "Sistema de merge em memória para arquivos até 300MB, minimizando o desgaste do SSD "
            "e eliminando gargalos de I/O durante a finalização.")

        self._add_feature(content_layout, "INTEGRIDADE SHA-256", 
            "Pipeline de validação criptográfica pós-processamento para garantir que cada byte "
            "baixado seja idêntico ao original no servidor.")

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)

        # ── FOOTER ─────────────────────────────────────────────────────
        footer = QFrame()
        footer.setStyleSheet("background: #0b0d14; border-top: 1px solid #1e2438; padding: 20px;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(25, 15, 25, 15)
        
        credits_layout = QVBoxLayout()
        credits_layout.setSpacing(2)
        
        author = QLabel("Desenvolvido por <b>DreamerJP</b>")
        author.setStyleSheet("color: #5c6a94; font-size: 11px;")
        credits_layout.addWidget(author)
        
        repo_link = QLabel('<a href="https://github.com/DreamerJP/Downloader" style="color: #3d5aff; text-decoration: none;">GitHub Repository</a>')
        repo_link.setOpenExternalLinks(True)
        repo_link.setStyleSheet("font-size: 11px; font-weight: 600;")
        credits_layout.addWidget(repo_link)
        footer_layout.addLayout(credits_layout)

        close_btn = QPushButton("Fechar")
        close_btn.setFixedWidth(90)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)

        layout.addWidget(footer)

    def _add_feature(self, layout, title_text, desc_text):
        container = QWidget()
        h_box = QHBoxLayout(container)
        h_box.setContentsMargins(0, 0, 0, 0)
        h_box.setSpacing(15)

        # Marcador minimalista (linha vertical)
        marker = QFrame()
        marker.setFixedWidth(2)
        marker.setMinimumHeight(30)
        marker.setStyleSheet("background-color: #3d5aff; border-radius: 1px;")
        h_box.addWidget(marker)

        v_box = QVBoxLayout()
        v_box.setContentsMargins(0, 0, 0, 0)
        v_box.setSpacing(4)
        
        t = QLabel(title_text)
        t.setStyleSheet("color: #22c97a; font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;")
        v_box.addWidget(t)
        
        d = QLabel(desc_text)
        d.setStyleSheet("color: #8896c8; font-size: 12px; line-height: 1.3;")
        d.setWordWrap(True)
        v_box.addWidget(d)
        
        h_box.addLayout(v_box)
        layout.addWidget(container)
