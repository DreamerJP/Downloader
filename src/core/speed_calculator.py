"""
core/speed_calculator.py

Telemetria do download a partir do contador de bytes do próprio download.

As threads de download chamam counter.add(delta); o QTimer da UI lê o total
a cada tick e deriva velocidade (janela deslizante + EWMA), progresso e ETA.
"""

import math
import time
from collections import deque
from multiprocessing import Value


# Janela da média de velocidade. O swarm só contabiliza a cada 1 MB gravado
# por conexão; com ticks de 100 ms, uma janela curta faria o valor saltar.
SPEED_WINDOW_SECONDS = 2.0


class AtomicCounter:
    """
    Contador cumulativo de bytes — usado para velocidade, progresso e ETA.

    Compartilhado entre o processo da UI e o processo filho via
    multiprocessing.Value. As threads do filho chamam add() (com lock); o
    QTimer da UI lê via read() — leitura atômica sem lock, segura em int64
    alinhado em arquiteturas 64-bit. Sem lock na leitura, o pai não trava se
    o filho for morto (pause/cancelamento) segurando o lock.
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
    Calcula métricas de velocidade de download a partir do AtomicCounter.
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
        self._speed_samples: deque[tuple[float, int]] = deque()

        self.peak_speed: float = 0.0
        self.total_bytes_target: int = 0
        self.progress_mode: str = "bytes"
        self.total_segments: int = 0
        self.completed_segments: int = 0

        self._chart_points: deque[tuple[float, float]] = deque()

    def set_total_bytes(self, total: int) -> None:
        self.progress_mode = "bytes"
        self.total_bytes_target = max(int(total or 0), 0)

    def set_total_segments(self, total: int, already_done: int = 0) -> None:
        """`already_done`: segmentos que já estavam em disco (retomada)."""
        self.progress_mode = "segments"
        self.total_segments = max(int(total or 0), 0)
        self.completed_segments = max(int(already_done or 0), 0)

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
        # for morto (pause/cancelamento) com o lock segurado.
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

        samples = self._speed_samples
        samples.append((now, self._total_confirmed_bytes))
        while len(samples) > 2 and now - samples[1][0] >= SPEED_WINDOW_SECONDS:
            samples.popleft()
        oldest_ts, oldest_bytes = samples[0]
        if now > oldest_ts:
            instant_speed = (self._total_confirmed_bytes - oldest_bytes) / (now - oldest_ts)
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

    def _get_eta_seconds(self, speed: float) -> float | None:
        if self.progress_mode == "segments":
            remaining = self.total_segments - self.completed_segments
            if remaining > 0 and speed > 0:
                if self.total_bytes_target > 0:
                    return (remaining * (self.total_bytes_target / self.total_segments)) / speed
                elif self.completed_segments > 0:
                    avg_segment_bytes = self._total_confirmed_bytes / self.completed_segments
                    return (remaining * avg_segment_bytes) / speed
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