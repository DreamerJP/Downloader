"""
ui/widgets/speed_chart.py
Gráfico de velocidade de download em tempo real.
Renderizado com QPainter — sem dependências externas além do PyQt6.
"""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QWidget


class SpeedChartWidget(QWidget):
    """
    Gráfico de velocidade desenhado com QPainter.

    Exibe a velocidade em MB/s ao longo do tempo com:
    - Linha de velocidade atual com gradiente de preenchimento
    - Linha horizontal de velocidade média
    - Linha vertical de conclusão do download
    - Grid com labels de tempo e velocidade
    - Janela deslizante configurável (padrão: 120s)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.visible_window_seconds: float = 120.0
        self.time_data: list[float] = []
        self.speed_data: list[float] = []
        self.chart_peak_speed: float = 0.0
        self.completion_time: float | None = None

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def set_history(
        self,
        points: list[tuple[float, float]],
        peak_speed: float = 0.0,
    ) -> None:
        """
        Define todos os pontos de uma vez (chamado pelo timer da UI).

        Parâmetros:
            points     : lista de (tempo_s, bytes_por_s)
            peak_speed : velocidade máxima em bytes/s
        """
        self.time_data  = [float(p[0]) for p in points]
        self.speed_data = [float(p[1]) for p in points]
        self.chart_peak_speed = float(peak_speed or 0.0)
        self.update()

    def reset_chart(self) -> None:
        """Limpa todos os dados e força repaint."""
        self.time_data  = []
        self.speed_data = []
        self.chart_peak_speed = 0.0
        self.completion_time  = None
        self.update()

    def mark_download_complete(self) -> None:
        """Registra o tempo de conclusão para desenhar a linha vertical."""
        self.completion_time = self.time_data[-1] if self.time_data else None
        self.update()

    def get_peak_speed(self) -> float:
        """Retorna a velocidade máxima registrada no gráfico."""
        return self.chart_peak_speed

    # ------------------------------------------------------------------
    # Renderização
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        outer_rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(outer_rect, QColor("#181818"))

        chart_rect = QRectF(
            56, 14,
            max(10, outer_rect.width() - 72),
            max(10, outer_rect.height() - 40),
        )
        painter.fillRect(chart_rect, QColor("#1d1f23"))
        painter.setPen(QPen(QColor("#2f3238"), 1))
        painter.drawRoundedRect(chart_rect, 6, 6)

        # Sem dados
        if not self.time_data:
            painter.setPen(QColor("#7f858f"))
            painter.drawText(
                chart_rect, Qt.AlignmentFlag.AlignCenter,
                "Aguardando início do download..."
            )
            return

        visible = self._get_visible_points()
        if not visible:
            painter.setPen(QColor("#7f858f"))
            painter.drawText(
                chart_rect, Qt.AlignmentFlag.AlignCenter,
                "Sem dados suficientes para exibir"
            )
            return

        start_time = visible[0][0]
        end_time   = visible[-1][0]
        time_span  = max(end_time - start_time, 10.0)

        speed_values_mbps = [s / (1024 * 1024) for _, s in visible]
        max_speed_mbps    = max(speed_values_mbps) if speed_values_mbps else 0.0
        y_max = self._nice_axis_limit(
            max(max_speed_mbps, self.chart_peak_speed / (1024 * 1024), 1.0) * 1.15
        )

        # Labels de eixo
        painter.setPen(QColor("#9ba3b0"))
        painter.drawText(
            QRectF(chart_rect.left() + 10, chart_rect.top() + 6, 80, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "MB/s",
        )
        painter.drawText(
            QRectF(chart_rect.right() - 120, chart_rect.top() + 6, 110, 16),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"Janela {int(self.visible_window_seconds)}s",
        )

        self._draw_grid(painter, chart_rect, start_time, end_time, y_max)
        self._draw_series(painter, chart_rect, visible, start_time, time_span, y_max)
        self._draw_completion_line(painter, chart_rect, start_time, time_span)

    # ------------------------------------------------------------------
    # Helpers de renderização
    # ------------------------------------------------------------------

    def _get_visible_points(self) -> list[tuple[float, float]]:
        if not self.time_data:
            return []
        points = list(zip(self.time_data, self.speed_data))
        latest = points[-1][0]
        cutoff = max(0.0, latest - self.visible_window_seconds)
        visible = [(t, s) for t, s in points if t >= cutoff]
        # Garantir ao menos 2 pontos para desenhar linha
        if len(visible) == 1:
            visible.append((visible[0][0] + 0.25, visible[0][1]))
        return visible

    def _draw_grid(
        self,
        painter: QPainter,
        rect: QRectF,
        start_time: float,
        end_time: float,
        y_max: float,
    ) -> None:
        grid_pen = QPen(QColor("#2c3138"), 1)
        grid_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)

        # Linhas horizontais (eixo Y — velocidade)
        for step in range(5):
            ratio = step / 4
            y = rect.bottom() - (ratio * rect.height())
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            label = QRectF(4, y - 10, 46, 20)
            painter.setPen(QColor("#9097a3"))
            painter.drawText(
                label,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._format_speed_axis(y_max * ratio),
            )
            painter.setPen(grid_pen)

        # Linhas verticais (eixo X — tempo)
        for step in range(7):
            ratio = step / 6
            x = rect.left() + (ratio * rect.width())
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            t = start_time + ((end_time - start_time) * ratio)
            label = QRectF(x - 22, rect.bottom() + 4, 44, 18)
            painter.setPen(QColor("#9097a3"))
            painter.drawText(label, Qt.AlignmentFlag.AlignCenter, self._format_time_axis(t))
            painter.setPen(grid_pen)

    def _draw_series(
        self,
        painter: QPainter,
        rect: QRectF,
        points: list[tuple[float, float]],
        start_time: float,
        time_span: float,
        y_max: float,
    ) -> None:
        line_path = QPainterPath()
        fill_path = QPainterPath()
        last_x = last_y = first_x = None

        for i, (t, speed) in enumerate(points):
            speed_mbps = speed / (1024 * 1024)
            x = rect.left() + (((t - start_time) / time_span) * rect.width())
            y = rect.bottom() - ((speed_mbps / y_max) * rect.height())

            if i == 0:
                line_path.moveTo(x, y)
                fill_path.moveTo(x, rect.bottom())
                fill_path.lineTo(x, y)
                first_x = x
            else:
                line_path.lineTo(x, y)
                fill_path.lineTo(x, y)
            last_x, last_y = x, y

        if last_x is None:
            return

        fill_path.lineTo(last_x, rect.bottom())
        fill_path.closeSubpath()

        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(74, 158, 255, 120))
        gradient.setColorAt(1.0, QColor(74, 158, 255, 12))
        painter.fillPath(fill_path, gradient)

        painter.setPen(QPen(QColor("#59a7ff"), 2.4))
        painter.drawPath(line_path)

        # Ponto na ponta da linha (posição atual)
        if last_y is not None:
            painter.setPen(QPen(QColor("#cde3ff"), 1.4))
            painter.setBrush(QColor("#59a7ff"))
            painter.drawEllipse(QPointF(last_x, last_y), 4.2, 4.2)

    def _draw_completion_line(
        self,
        painter: QPainter,
        rect: QRectF,
        start_time: float,
        time_span: float,
    ) -> None:
        if self.completion_time is None or self.completion_time < start_time:
            return
        x = rect.left() + (((self.completion_time - start_time) / time_span) * rect.width())
        pen = QPen(QColor(255, 107, 107, 180), 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

    # ------------------------------------------------------------------
    # Formatação de eixos
    # ------------------------------------------------------------------

    @staticmethod
    def _nice_axis_limit(value: float) -> float:
        if value <= 10:
            return 10.0
        magnitude  = 10 ** math.floor(math.log10(value))
        normalized = value / magnitude
        if normalized <= 1:
            nice = 1
        elif normalized <= 2:
            nice = 2
        elif normalized <= 5:
            nice = 5
        else:
            nice = 10
        return float(nice * magnitude)

    @staticmethod
    def _format_time_axis(seconds: float) -> str:
        total = max(int(seconds), 0)
        m, s  = divmod(total, 60)
        h, m  = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        if m > 0:
            return f"{m}:{s:02d}"
        return f"{s}s"

    @staticmethod
    def _format_speed_axis(speed_mbps: float) -> str:
        if speed_mbps >= 100:
            return f"{speed_mbps:.0f}"
        if speed_mbps >= 10:
            return f"{speed_mbps:.1f}"
        return f"{speed_mbps:.2f}"
