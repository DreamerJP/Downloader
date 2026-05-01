"""
ui/widgets/segments_map.py
Widget que exibe o mapa visual de progresso dos segmentos Swarm.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class SegmentsMapWidget(QWidget):
    """
    Barra de progresso detalhada que mostra cada segmento individualmente.

    Cada segmento é representado proporcionalmente ao seu tamanho no arquivo.
    A parte já baixada fica verde; o cursor ativo (cabeça da thread) fica branco.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(12)
        self.setMaximumHeight(16)
        self.total_size: int = 0
        self.segments: list[dict] = []

    def update_map(self, total_size: int, segments: list[dict]) -> None:
        """
        Atualiza os dados e solicita repaint.

        Parâmetros:
            total_size : tamanho total do arquivo em bytes
            segments   : lista de dicts {'start', 'end', 'downloaded', 'active'}
        """
        self.total_size = total_size
        self.segments = segments
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        rect = self.rect()

        # Fundo
        painter.fillRect(rect, QColor("#1e1e1e"))
        painter.setPen(QPen(QColor("#333333"), 1))
        painter.drawRect(0, 0, rect.width() - 1, rect.height() - 1)

        if self.total_size <= 1024 or not self.segments:
            return

        width  = rect.width() - 2
        height = rect.height() - 2

        for seg in self.segments:
            start      = seg.get("start", 0)
            end        = seg.get("end", 0)
            downloaded = seg.get("downloaded", 0)
            active     = seg.get("active", False)

            if end <= start:
                continue

            seg_total = end - start + 1

            # Posição e largura relativas ao arquivo total
            x_start     = 1 + int((start / self.total_size) * width)
            x_end       = 1 + int(((end + 1) / self.total_size) * width)
            block_width = max(1, x_end - x_start)

            # Largura da parte baixada
            downloaded_width = int((downloaded / seg_total) * block_width)

            # Parte baixada — verde mais vivo quando ativo
            if downloaded_width > 0:
                color = QColor("#81c784") if active else QColor("#4caf50")
                painter.fillRect(x_start, 1, downloaded_width, height, color)

            # Cabeça ativa (cursor branco + halo escuro)
            if active:
                head_x = x_start + downloaded_width
                if head_x < rect.width() - 1:
                    painter.fillRect(head_x, 1, 2, height, QColor("#ffffff"))
                    remaining_w = max(1, block_width - downloaded_width - 2)
                    if remaining_w > 0:
                        painter.fillRect(head_x + 2, 1, remaining_w, height, QColor("#2a422a"))
