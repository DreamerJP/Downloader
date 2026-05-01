"""
core/speed_calculator.py

Telemetria de velocidade via psutil.net_io_counters().

Abordagem: leitura da NIC global a cada tick do QTimer (thread principal).
Mesmo método usado pelo Gerenciador de Tarefas do Windows — suave, preciso,
zero overhead nas threads de download.

As threads de download chamam counter.add(delta) para contabilizar bytes
baixados (usado para progresso e ETA). A velocidade exibida no gráfico vem
exclusivamente da NIC.
"""

import math
import time
from collections import deque
from multiprocessing import Value

import psutil


class AtomicCounter:
    """
    Contador cumulativo de bytes — usado para progresso e ETA.

    Compartilhado entre o processo da UI e o processo filho via
    multiprocessing.Value. As threads do filho chamam add() (com lock); o
    QTimer da UI lê via read() — leitura atômica sem lock, segura em int64
    alinhado em arquiteturas 64-bit. Crucial para que o pai não bloqueie
    quando o filho é suspenso (pause via psutil) com o lock segurado.
    """

    def __init__(self) -> None:
        self._value = Value("q", 0)

    def add(self, delta: int) -> None:
        with self._value.get_lock():
            self._value.value += delta

    def read(self) -> int:
        return self._value.value

    def reset(self) -> None:
        with self._value.get_lock():
            self._value.value = 0


class SpeedCalculator:
    """
    Calcula métricas de velocidade de download.

    Velocidade atual  → psutil.net_io_counters() (suave, como o Task Manager)
    Bytes baixados    → AtomicCounter (para progresso e ETA)
    """

    def __init__(
        self,
        ewma_alpha: float = 0.3,
        chart_interval: float = 0.25,
        chart_history_seconds: float = 180.0,
    ) -> None:
        self._ewma_alpha = ewma_alpha
        self._chart_interval = chart_interval
        self._chart_history_seconds = chart_history_seconds

        self.counter = AtomicCounter()
        self.reset()

    def reset(self) -> None:
        self.counter.reset()
        self._last_read_bytes: int = 0

        self._start_ts: float | None = None
        self._end_ts: float | None = None
        self._last_tick_ts: float | None = None
        self._last_chart_sample_ts: float | None = None
        self._ewma_speed: float = 0.0
        self._total_confirmed_bytes: int = 0

        # Amostra inicial da NIC para calcular delta no primeiro tick
        self._last_nic_bytes: int = self._read_nic()

        self.peak_speed: float = 0.0
        self.total_bytes_target: int = 0
        self.progress_mode: str = "bytes"
        self.total_segments: int = 0
        self.completed_segments: int = 0

        self._chart_points: deque[tuple[float, float]] = deque()

    def set_total_bytes(self, total: int) -> None:
        self.progress_mode = "bytes"
        self.total_bytes_target = max(int(total or 0), 0)

    def set_total_segments(self, total: int) -> None:
        self.progress_mode = "segments"
        self.total_segments = max(int(total or 0), 0)

    def stop_tracking(self) -> None:
        if self._start_ts is None or self._end_ts is not None:
            return
        self._end_ts = time.perf_counter()

    # ------------------------------------------------------------------
    # Snapshot — chamado exclusivamente pelo QTimer (thread principal)
    # ------------------------------------------------------------------

    def get_snapshot(self) -> dict:
        now = time.perf_counter()

        # Leitura cumulativa lock-free — calcular delta a partir do total
        # acumulado. Sem reset no contador, o pai não trava se o filho
        # estiver suspenso (psutil) com o lock segurado.
        current = self.counter.read()
        delta_bytes = max(0, current - self._last_read_bytes)
        self._last_read_bytes = current
        if delta_bytes > 0 and self._start_ts is None:
            self._start_ts = now
            self._last_tick_ts = now
            self._last_chart_sample_ts = now
        self._total_confirmed_bytes += delta_bytes

        if self._start_ts is None:
            return self._empty_snapshot()

        # Velocidade via NIC — suave como o Task Manager
        current_nic = self._read_nic()
        nic_delta = max(0, current_nic - self._last_nic_bytes)
        self._last_nic_bytes = current_nic

        if self._last_tick_ts is not None and now > self._last_tick_ts:
            dt = now - self._last_tick_ts
            instant_speed = nic_delta / dt
        else:
            instant_speed = 0.0

        self._last_tick_ts = now

        # EWMA
        if self._ewma_speed == 0.0 and instant_speed > 0:
            self._ewma_speed = instant_speed
        else:
            self._ewma_speed = (
                self._ewma_alpha * instant_speed
                + (1.0 - self._ewma_alpha) * self._ewma_speed
            )

        current_speed = 0.0 if self._end_ts is not None else self._ewma_speed
        self.peak_speed = max(self.peak_speed, current_speed)

        self._sample_chart(now, current_speed)

        return {
            "current_speed":      current_speed,
            "peak_speed":         self.peak_speed,
            "eta":                self._format_eta(self._get_eta_seconds(current_speed)),
            "progress_ratio":     self.get_progress_ratio(),
            "downloaded_bytes":   self._total_confirmed_bytes,
            "completed_segments": self.completed_segments,
            "total_segments":     self.total_segments,
            "chart_points":       self.get_chart_points(),
        }

    # ------------------------------------------------------------------
    # Métricas derivadas
    # ------------------------------------------------------------------

    def get_duration(self) -> float:
        if self._start_ts is None:
            return 0.0
        end = self._end_ts if self._end_ts is not None else time.perf_counter()
        return max(0.0, end - self._start_ts)

    def get_progress_ratio(self) -> float | None:
        if self.progress_mode == "segments":
            if self.total_segments > 0:
                return min(self.completed_segments / self.total_segments, 1.0)
            return None
        if self.total_bytes_target > 0:
            return min(self._total_confirmed_bytes / self.total_bytes_target, 1.0)
        return None

    # ------------------------------------------------------------------
    # Gráfico
    # ------------------------------------------------------------------

    def _sample_chart(self, now: float, speed: float) -> None:
        if self._start_ts is None or self._last_chart_sample_ts is None:
            return
        while self._last_chart_sample_ts + self._chart_interval <= now:
            self._last_chart_sample_ts += self._chart_interval
            t_rel = self._last_chart_sample_ts - self._start_ts
            self._chart_points.append((t_rel, speed))
        while (
            len(self._chart_points) >= 2
            and self._chart_points[-1][0] - self._chart_points[0][0]
            > self._chart_history_seconds
        ):
            self._chart_points.popleft()

    def get_chart_points(
        self, window_seconds: float = 120.0, max_points: int = 240
    ) -> list[tuple[float, float]]:
        if not self._chart_points:
            return []
        points = list(self._chart_points)
        latest = points[-1][0]
        visible = [(t, s) for t, s in points if t >= latest - window_seconds]
        if len(visible) <= max_points:
            return visible
        step = math.ceil(len(visible) / max_points)
        return visible[::step]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_nic() -> int:
        try:
            return psutil.net_io_counters().bytes_recv
        except Exception:
            return 0

    def _get_eta_seconds(self, speed: float) -> float | None:
        if self.progress_mode == "segments":
            remaining = self.total_segments - self.completed_segments
            if remaining > 0 and speed > 0 and self.total_bytes_target > 0:
                return (remaining * (self.total_bytes_target / self.total_segments)) / speed
            return None
        if self.total_bytes_target <= 0 or speed <= 0:
            return None
        return max(self.total_bytes_target - self._total_confirmed_bytes, 0) / speed

    def _empty_snapshot(self) -> dict:
        return {
            "current_speed":      0.0,
            "peak_speed":         0.0,
            "eta":                "--",
            "progress_ratio":     self.get_progress_ratio(),
            "downloaded_bytes":   self._total_confirmed_bytes,
            "completed_segments": self.completed_segments,
            "total_segments":     self.total_segments,
            "chart_points":       [],
        }

    @staticmethod
    def _format_eta(seconds: float | None) -> str:
        if seconds is None or seconds > 360_000:
            return "--"
        if seconds <= 0:
            return "0s"
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60:02d}s"
        return f"{s // 3600}h {(s % 3600) // 60:02d}m"