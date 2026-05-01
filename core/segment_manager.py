"""
core/segment_manager.py
Gerenciador dinâmico de segmentos para o Swarm Download.
Thread-safe. Sem dependências de PyQt6.
"""

import json
import os
import threading
from typing import Optional


class DynamicSegmentManager:
    """
    Divide o arquivo em segmentos e distribui trabalho entre threads.

    Estratégia:
    - Segmentos livres ('free') são atribuídos ao primeiro thread que pedir.
    - Se não há segmentos livres, o maior segmento ativo ('active') é dividido
      ao meio (work-stealing), desde que o restante seja >= 2 * min_split_size.
    - Segmentos concluídos ficam com status 'done'.
    """

    def __init__(self, total_size: int):
        """
        Parâmetros:
            total_size : tamanho total do arquivo em bytes
        """
        self.lock = threading.Lock()
        self.total_size = total_size

        # min_split_size: entre 256 KB e 4 MB, proporcional ao arquivo
        calc = total_size // 200
        self.min_split_size: int = max(256 * 1024, min(calc, 4 * 1024 * 1024))

        self.segments: list[dict] = [
            {"start": 0, "end": total_size - 1, "current": 0, "status": "free"}
        ]

    # ------------------------------------------------------------------
    # Distribuição de trabalho
    # ------------------------------------------------------------------

    def get_work(self) -> Optional[dict]:
        """
        Retorna um segmento para o thread trabalhar, ou None se não há trabalho.

        Prioridade:
        1. Maior segmento 'free' (bytes restantes = end - current).
        2. Divisão do maior segmento 'active' se viável.
        3. None — thread deve aguardar ou encerrar.
        """
        with self.lock:
            free = [s for s in self.segments if s["status"] == "free"]
            if free:
                seg = max(free, key=lambda s: s["end"] - s["current"])
                seg["status"] = "active"
                return seg

            active = [s for s in self.segments if s["status"] == "active"]
            if not active:
                return None

            largest = max(active, key=lambda s: s["end"] - s["current"])
            remaining = largest["end"] - largest["current"]

            if remaining <= self.min_split_size * 2:
                return None

            # Dividir ao meio — o novo segmento começa logo após o split_point
            split_point = largest["current"] + (remaining // 2)
            original_end = largest["end"]
            largest["end"] = split_point

            new_seg: dict = {
                "start": split_point + 1,
                "end": original_end,
                "current": split_point + 1,
                "status": "active",
            }
            self.segments.append(new_seg)
            return new_seg

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def mark_done(self, segment: dict) -> None:
        """Marca um segmento como concluído de forma thread-safe."""
        with self.lock:
            segment["status"] = "done"

    def is_complete(self) -> bool:
        """Retorna True se todos os segmentos estão concluídos."""
        with self.lock:
            return all(s.get("status") == "done" for s in self.segments)

    def get_map_data(self) -> list[dict]:
        """
        Retorna snapshot dos segmentos para renderização do mapa visual.

        Cada item: {'start', 'end', 'downloaded', 'active'}
        """
        with self.lock:
            return [
                {
                    "start": s["start"],
                    "end": s["end"],
                    "downloaded": s["current"] - s["start"],
                    "active": s["status"] == "active",
                }
                for s in self.segments
            ]

    # ------------------------------------------------------------------
    # Persistência (resume)
    # ------------------------------------------------------------------

    def save_to_file(self, filepath: str) -> None:
        """Persiste o estado atual em JSON para permitir resume."""
        with self.lock:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(self.segments, f)
            except OSError:
                pass  # Falha silenciosa — não interromper o download

    @classmethod
    def load_from_file(cls, filepath: str, total_size: int) -> Optional["DynamicSegmentManager"]:
        """
        Restaura estado a partir de arquivo JSON.

        Retorna None se o arquivo não existe, está corrompido ou o total_size
        não coincide com o arquivo salvo (segurança contra resume de arquivo diferente).

        Segmentos com status 'active' são revertidos para 'free' para reprocessamento.
        """
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                segments = json.load(f)

            if not isinstance(segments, list) or not segments:
                return None

            # Validação de integridade: último segmento deve cobrir o arquivo inteiro
            if segments[-1]["end"] != total_size - 1:
                return None

            instance = cls.__new__(cls)
            instance.lock = threading.Lock()
            instance.total_size = total_size
            calc = total_size // 200
            instance.min_split_size = max(256 * 1024, min(calc, 4 * 1024 * 1024))

            # Reverter 'active' → 'free': threads podem ter sido interrompidas
            for s in segments:
                if s.get("status") == "active":
                    s["status"] = "free"
            instance.segments = segments
            return instance

        except (json.JSONDecodeError, KeyError, OSError):
            return None
