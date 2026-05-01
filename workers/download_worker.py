"""
workers/download_worker.py

QThread que orquestra o download em um processo filho. Não faz I/O em si —
spawna multiprocessing.Process(engine_main) e fica em um loop lendo mensagens
do Pipe, redirecionando como signals Qt para a UI.

Cancelamento é via process.terminate() — equivalente a TerminateProcess no
Windows / SIGKILL no Unix. Encerra todo o processo filho e seus sockets,
threads e file handles imediatamente.
"""

import os
import shutil
import threading
from multiprocessing import Pipe, Process
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.constants import CONNECT_TIMEOUT, TEMP_DIR
from core.speed_calculator import AtomicCounter
from workers.download_engine import engine_main


class DownloadWorker(QThread):
    """
    Bridge entre o processo da UI e o processo filho do download.

    Signals:
        log_signal          : (mensagem, nível)
        finished_signal     : (sucesso, mensagem)
        total_size_signal   : int ou dict {'mode', 'total'}
        segments_map_signal : (total, map_data)
        segment_done_signal : sem args
    """

    log_signal          = pyqtSignal(str, str)
    finished_signal     = pyqtSignal(bool, str)
    total_size_signal   = pyqtSignal(object)
    segments_map_signal = pyqtSignal(object, object)
    segment_done_signal = pyqtSignal()

    def __init__(
        self,
        url: str,
        output_path: str,
        threads: int,
        speed_counter: AtomicCounter,
        checksum: Optional[str] = None,
        proxy: Optional[dict] = None,
        auth: Optional[tuple] = None,
        auto_detect_quality: bool = True,
        connect_timeout: float = CONNECT_TIMEOUT,
        custom_headers: Optional[dict] = None,
        x3d_opt: bool = False,
        is_resume: bool = False,
    ):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.threads = threads
        self.speed_counter = speed_counter
        self.expected_checksum = checksum
        self.proxy = proxy
        self.auth = auth
        self.auto_detect_quality = auto_detect_quality
        self.connect_timeout = connect_timeout
        self.custom_headers = custom_headers
        self.x3d_opt = x3d_opt
        self.is_resume = is_resume

        self._process: Optional[Process] = None
        self._cmd_send = None
        self._is_paused = False
        self._stopped_by_user = False
        self._abandoned = False
        self._final_path: Optional[str] = None
        self._part_dir: Optional[str] = None
        self._child_meipass: Optional[str] = None

    # ------------------------------------------------------------------
    # Controle externo
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """
        Cancela o download terminando o processo filho. Idempotente.
        Equivalente a `taskkill /F /PID` — encerra imediatamente todas
        as threads, sockets e file handles do processo filho.
        """
        if self._stopped_by_user:
            return
        self._stopped_by_user = True
        # Cancelamento limpa arquivos; pause preserva. Reset abandon para
        # que o cleanup remova mesmo se já tinha vindo de um pause.
        self._abandoned = False

        proc = self._process
        if proc is not None and proc.is_alive():
            try:
                proc.terminate()
            except Exception:
                pass

        self.finished_signal.emit(False, "Download cancelado.")
        threading.Thread(target=self._cleanup_after_kill, daemon=True).start()

    def pause(self) -> None:
        """
        Pausa o download encerrando o subprocesso de modo instantâneo —
        equivalente a `taskkill /F` — preservando os arquivos parciais e
        o `state.json` do swarm em disco. A retomada é feita pela UI
        criando um novo `DownloadWorker` com `is_resume=True`, que faz o
        engine detectar o estado e continuar do ponto onde parou.
        """
        if self._is_paused or self._stopped_by_user:
            return
        self._is_paused = True
        # Não apaga arquivos no cleanup — eles são o estado da pausa.
        self._abandoned = True
        proc = self._process
        if proc is not None and proc.is_alive():
            try:
                proc.terminate()
            except Exception:
                pass
        threading.Thread(target=self._cleanup_after_kill, daemon=True).start()

    def resume(self) -> None:
        # Sem efeito direto — a UI (`main_window`) cria um worker novo com
        # `is_resume=True` para retomar; este worker já está encerrado.
        pass

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def abandon(self) -> None:
        """
        Marca este worker como descartado. O cleanup posterior pula a
        remoção dos arquivos para não interferir com um worker novo
        que possa estar usando o mesmo output_path.
        """
        self._abandoned = True

    # ------------------------------------------------------------------
    # Execução principal — encaminha mensagens do processo filho
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._run_impl()
        except Exception as e:
            # Qualquer exceção não tratada aqui mata a QThread silenciosamente
            # e a UI fica esperando um sinal que nunca virá. Capturamos tudo
            # e emitimos finished para que a UI volte ao estado inicial.
            try:
                self.log_signal.emit(f"Erro fatal no worker: {e}", "error")
            except Exception:
                pass
            if not self._stopped_by_user:
                try:
                    self.finished_signal.emit(False, "Falha no download.")
                except Exception:
                    pass

    def _run_impl(self) -> None:
        # Pipe(duplex=False) retorna (reader, writer). Naming explícito para
        # evitar inverter as pontas — bug que silenciava todos os comandos.
        msg_recv, msg_send = Pipe(duplex=False)   # filho envia → pai recebe
        cmd_recv, cmd_send = Pipe(duplex=False)   # pai envia → filho recebe
        self._cmd_send = cmd_send

        config = {
            "url": self.url,
            "output_path": self.output_path,
            "threads": self.threads,
            "proxy": self.proxy,
            "auth": self.auth,
            "auto_detect_quality": self.auto_detect_quality,
            "connect_timeout": self.connect_timeout,
            "custom_headers": self.custom_headers,
            "x3d_opt": self.x3d_opt,
            "expected_checksum": self.expected_checksum,
            "is_resume": self.is_resume,
        }

        self._process = Process(
            target=engine_main,
            args=(config, self.speed_counter._value, msg_send, cmd_recv),
            name="DownloadEngine",
            daemon=True,
        )
        self._process.start()

        # Pontas do filho são fechadas no pai — o filho mantém suas próprias.
        msg_send.close()
        cmd_recv.close()

        finished_emitted = False

        while True:
            try:
                if not msg_recv.poll(0.2):
                    if not self._process.is_alive():
                        break
                    continue
                payload = msg_recv.recv()
            except (EOFError, BrokenPipeError, OSError):
                break

            kind = payload[0] if payload else None
            args = payload[1:]

            if kind == "log":
                self.log_signal.emit(args[0], args[1] if len(args) > 1 else "info")
            elif kind == "total_size":
                self.total_size_signal.emit(args[0])
            elif kind == "segments_map":
                self.segments_map_signal.emit(args[0], args[1])
            elif kind == "segment_done":
                self.segment_done_signal.emit()
            elif kind == "resolved_path":
                self._final_path = args[0]
            elif kind == "part_dir":
                self._part_dir = args[0]
            elif kind == "meipass":
                self._child_meipass = args[0]
            elif kind == "finished":
                if not self._stopped_by_user and not self._is_paused:
                    self.finished_signal.emit(args[0], args[1])
                finished_emitted = True
                break

        try:
            self._process.join(timeout=2)
        except Exception:
            pass

        if not finished_emitted and not self._stopped_by_user and not self._is_paused:
            success = (self._process.exitcode == 0) if self._process else False
            msg = "Download concluído!" if success else "Falha no download."
            self.finished_signal.emit(success, msg)

        try:
            msg_recv.close()
        except Exception:
            pass
        try:
            cmd_send.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _send_cmd(self, cmd: str) -> None:
        pipe = self._cmd_send
        if pipe is None:
            return
        try:
            pipe.send(cmd)
        except (BrokenPipeError, OSError):
            pass

    def _cleanup_after_kill(self) -> None:
        """
        Após terminate(), aguarda o processo realmente sair e remove
        arquivos parciais deixados em disco. Roda em thread daemon, fora
        do caminho da UI.
        """
        proc = self._process
        if proc is not None:
            try:
                proc.join(timeout=5)
                if proc.is_alive():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.join(timeout=2)
                    except Exception:
                        pass
            except Exception:
                pass

        # NÃO apagamos o _MEI órfão aqui: a thread roda em background e
        # pode correr contra a extração de um subprocesso novo (resume),
        # já que PyInstaller usa `_MEI<pid_low_bits>` e PIDs do Windows
        # podem reusar os mesmos 20 bits inferiores. A limpeza acontece no
        # próximo startup do app via cleanup_temp_meipass().
        if self._abandoned:
            return
        self._remove_partial_files()

    def _remove_partial_files(self) -> None:
        """
        Remove o arquivo de saída parcial e o `part_dir` (state.json do
        swarm / segmentos do HLS) reportado pelo engine via Pipe.
        """
        target = self._final_path or self.output_path
        if target and os.path.isfile(target):
            try:
                os.remove(target)
            except OSError:
                pass

        if self._part_dir and os.path.isdir(self._part_dir):
            try:
                shutil.rmtree(self._part_dir, ignore_errors=True)
            except Exception:
                pass

        try:
            if os.path.isdir(TEMP_DIR) and not os.listdir(TEMP_DIR):
                os.rmdir(TEMP_DIR)
        except OSError:
            pass

    def _remove_orphan_meipass(self) -> None:
        """
        PyInstaller extrai o bundle em `_MEI<rand>` no temp do SO. O bootloader
        normalmente faz cleanup ao sair, mas terminate() não dá essa chance —
        o folder fica órfão. Aqui apagamos o _MEI específico do processo filho
        que reportou via Pipe ao iniciar.
        """
        meipass = self._child_meipass
        if not meipass or not os.path.isdir(meipass):
            return
        try:
            shutil.rmtree(meipass, ignore_errors=True)
        except Exception:
            pass
