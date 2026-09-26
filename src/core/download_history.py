"""
core/download_history.py
Persistência do histórico de downloads em JSON. Sem dependências de PyQt6.
"""

import json
import os
import sys
from datetime import datetime

from core.constants import HISTORY_FILE, LEGACY_HISTORY_FILE


STATUS_DONE = "concluido"
STATUS_FAILED = "falhou"
STATUS_CANCELLED = "cancelado"


def _legacy_history_paths() -> list[str]:
    """Locais onde versões antigas gravavam o histórico (relativo ao CWD)."""
    paths = [os.path.abspath(LEGACY_HISTORY_FILE)]
    if getattr(sys, "frozen", False):
        paths.append(os.path.join(os.path.dirname(sys.executable), LEGACY_HISTORY_FILE))
    return paths


class DownloadHistory:
    """
    Mantém um registro dos últimos 100 downloads em arquivo JSON.
    Cada entrada contém URL, nome do arquivo, tamanho, duração e status.
    """

    MAX_ENTRIES = 100

    def __init__(self, filepath: str = HISTORY_FILE):
        self.filepath = filepath
        self.history: list[dict] = self._load()

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def _load(self) -> list[dict]:
        """Carrega histórico do disco. Retorna lista vazia em caso de erro."""
        if not os.path.exists(self.filepath):
            # Migra o histórico da versão antiga (copiado, o original fica).
            for legacy in _legacy_history_paths():
                data = self._read(legacy)
                if data:
                    self.history = data
                    self.save()
                    return data
            return []
        return self._read(self.filepath)

    @staticmethod
    def _read(path: str) -> list[dict]:
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def save(self) -> None:
        """Persiste o histórico em disco."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[DownloadHistory] Erro ao salvar histórico: {e}")

    # ------------------------------------------------------------------
    # Operações
    # ------------------------------------------------------------------

    def add(
        self,
        url: str,
        output_path: str,
        size: int,
        duration: float,
        status: str,
    ) -> None:
        """
        Adiciona uma entrada ao histórico e salva imediatamente.

        Parâmetros:
            url         : URL do download
            output_path : caminho completo do arquivo salvo
            size        : tamanho do arquivo salvo (0 quando não concluído)
            duration    : duração em segundos
            status      : STATUS_DONE, STATUS_FAILED ou STATUS_CANCELLED
        """
        entry = {
            "url": url,
            "filename": os.path.basename(output_path) if output_path else "",
            "path": output_path or "",
            "size": max(int(size or 0), 0),
            "duration": max(float(duration or 0.0), 0.0),
            "timestamp": datetime.now().isoformat(),
            "success": status == STATUS_DONE,
            "status": status,
        }
        self.history.insert(0, entry)
        if len(self.history) > self.MAX_ENTRIES:
            self.history = self.history[: self.MAX_ENTRIES]
        self.save()

    def clear(self) -> None:
        """Remove todas as entradas e salva."""
        self.history = []
        self.save()

    def export_to_file(self, filepath: str) -> bool:
        """
        Exporta o histórico para um arquivo JSON externo.

        Retorna True em sucesso, False em falha.
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
            return True
        except OSError as e:
            print(f"[DownloadHistory] Erro ao exportar: {e}")
            return False
