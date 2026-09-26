"""
ui/main_window.py
Orquestrador principal da UI. Gerencia abas, workers, timers e persistência.
"""

import os
import re

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QMessageBox, QStatusBar, QFileDialog
)
from PyQt6.QtCore import QTimer, QSettings, Qt
from PyQt6.QtGui import QIcon

from core.constants import UPDATE_INTERVAL, HISTORY_FILE
from core.download_history import (
    DownloadHistory, STATUS_CANCELLED, STATUS_DONE, STATUS_FAILED,
)
from core.file_utils import get_resource_path
from core.secret_store import is_protected, protect, unprotect
from core.speed_calculator import SpeedCalculator
from core.updater import Updater, UpdateCheckError, get_app_version
from core.windows_taskbar import WindowsTaskbarProgress
from workers.download_worker import DownloadWorker

from ui.download_tab import DownloadTab
from ui.history_tab import HistoryTab
from ui.chrome_tab import ChromeTab
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.about_dialog import AboutDialog
from ui.dialogs.update_dialog import UpdateDialog
from ui.dialogs.update_progress_dialog import UpdateProgressDialog


# Configurações gravadas cifradas (o proxy pode levar usuário:senha na URL).
_SECRET_SETTINGS = ("proxy_url", "auth_pass")

_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        app_version = get_app_version()
        self.setWindowTitle(f"Downloader v{app_version}")
        self.setWindowIcon(QIcon(get_resource_path("assets/ico.ico")))
        self.setFixedSize(820, 810)

        self.history = DownloadHistory(HISTORY_FILE)
        self.speed_calc = SpeedCalculator()
        self.updater = Updater(app_version)
        self.worker: DownloadWorker | None = None
        # Workers que ainda estão finalizando run() depois de já terem sinalizado
        # finished_signal — segura a referência até QThread.finished disparar
        # para não destruir o QThread enquanto a thread ainda executa.
        self._zombie_workers: list = []
        # Worker do download pausado (processo já encerrado). Quando não-None,
        # o botão Retomar cria um worker novo a partir dele.
        self._paused_worker: DownloadWorker | None = None
        self.taskbar_progress = WindowsTaskbarProgress()
        self._taskbar_token = 0
        self.settings = QSettings("DreamerJP", "DownloaderV2")

        self.app_settings = {
            "proxy_url":       self._load_secret("proxy_url"),
            "connect_timeout": int(self.settings.value("connect_timeout", 5)),
            "auth_user":       self.settings.value("auth_user", ""),
            "auth_pass":       self._load_secret("auth_pass"),
            "x3d_opt":         self.settings.value("x3d_opt", False, type=bool),
        }

        self._init_ui()
        self._setup_menu()
        self.taskbar_progress.initialize(int(self.winId()))

        # QTimer: única fonte de atualização da UI
        # O SpeedCalculator.get_snapshot() é chamado aqui — nunca nas threads.
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_timer_tick)
        self.timer.setInterval(UPDATE_INTERVAL)

        QTimer.singleShot(3000, self._check_for_updates)

    def _load_secret(self, key: str) -> str:
        stored = self.settings.value(key, "") or ""
        value = unprotect(stored)
        if stored and not is_protected(stored):
            # Valor gravado em texto puro por versão antiga: regrava cifrado.
            try:
                self.settings.setValue(key, protect(value))
            except OSError:
                pass
        return value

    def _has_unfinished_download(self) -> bool:
        return self.worker is not None or self._paused_worker is not None

    def _discard_unfinished_download(self) -> None:
        """Cancela o download ativo ou pausado e espera os parciais serem apagados."""
        worker = self.worker
        if worker is not None:
            worker.stop()
            worker.wait_cleanup(15)
        elif self._paused_worker is not None:
            self._abort_paused_download()

    def closeEvent(self, event):
        if self._has_unfinished_download():
            answer = QMessageBox.question(
                self,
                "Fechar o Downloader",
                "Há um download em andamento ou pausado. Fechar agora cancela o "
                "download e apaga o que já foi baixado.\n\nFechar mesmo assim?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._discard_unfinished_download()

        # Espera os QThreads terminarem — evita "QThread: Destroyed while
        # thread is still running" e processo filho órfão.
        for w in self._zombie_workers:
            try:
                w.wait(2000)
            except Exception:
                pass
        self.taskbar_progress.clear()
        super().closeEvent(event)

    def _init_ui(self):
        self.tabs = QTabWidget()

        self.download_tab = DownloadTab()
        self.history_tab  = HistoryTab()
        self.chrome_tab   = ChromeTab()

        self.tabs.addTab(self.download_tab, "Download")
        self.tabs.addTab(self.history_tab,  "Histórico")
        self.tabs.addTab(self.chrome_tab,   "Extensão Chrome")

        self.setCentralWidget(self.tabs)
        self.setStatusBar(QStatusBar())

        self.download_tab.start_btn.clicked.connect(self._start_download)
        self.download_tab.pause_btn.clicked.connect(self._toggle_pause)
        self.download_tab.stop_btn.clicked.connect(self._stop_download)

        self.history_tab.refresh(self.history.history)
        self.history_tab.clear_btn.clicked.connect(self._clear_history)
        self.history_tab.export_btn.clicked.connect(self._export_history)

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Arquivo")
        file_menu.addAction("Configurações...", self._show_settings)
        file_menu.addSeparator()
        file_menu.addAction("Sair", self.close)
        help_menu = menubar.addMenu("Ajuda")
        help_menu.addAction("Verificar Atualizações...", self._manual_check_updates)
        help_menu.addSeparator()
        help_menu.addAction("Sobre", self._show_about)

    # ------------------------------------------------------------------
    # Lógica de Download
    # ------------------------------------------------------------------

    def _start_download(self):
        url = self.download_tab.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Erro", "Informe uma URL válida.")
            return

        output   = self.download_tab.path_input.text().strip()
        threads  = self.download_tab.threads_input.value()
        checksum = "".join(self.download_tab.checksum_input.text().split())
        if checksum and not _SHA256_RE.fullmatch(checksum):
            QMessageBox.warning(
                self,
                "Checksum inválido",
                "O Checksum precisa ser um SHA256: 64 caracteres de 0 a 9 e a a f.\n"
                "Corrija ou apague o campo para baixar sem verificação.",
            )
            return

        # Worker anterior em estado de cleanup pós-cancelamento? Marca como
        # abandonado para que ele não apague arquivos do novo download, e
        # estaciona na lista de zumbis para o QThread terminar com segurança.
        if self.worker is not None:
            try:
                self.worker.abandon()
            except Exception:
                pass
            self._retire_worker(self.worker)
        # Iniciar do zero descarta qualquer download pausado e seus arquivos
        # de estado (state.json + arquivo parcial), pra evitar que o engine
        # auto-retome um download antigo quando o usuário queria começar novo.
        self._purge_paused_files()

        # Resetar estado
        self.speed_calc.reset()
        self.download_tab.progress_bar.setValue(0)
        self.download_tab.speed_chart.reset_chart()
        self.download_tab.segments_map.update_map(0, [])
        self.download_tab.log_output.clear()

        # Criar Worker — recebe o AtomicCounter do SpeedCalculator
        self.worker = DownloadWorker(
            url=url,
            output_path=output,
            threads=threads,
            speed_counter=self.speed_calc.counter,
            checksum=checksum or None,
            proxy=(
                {"http": self.app_settings["proxy_url"], "https": self.app_settings["proxy_url"]}
                if self.app_settings["proxy_url"] else None
            ),
            auth=(
                (self.app_settings["auth_user"], self.app_settings["auth_pass"])
                if self.app_settings["auth_user"] else None
            ),
            connect_timeout=self.app_settings["connect_timeout"],
            custom_headers=self.download_tab.custom_headers,
            x3d_opt=self.app_settings["x3d_opt"],
        )
        self._connect_worker(self.worker)

        self._taskbar_token += 1
        self.taskbar_progress.set_progress(0.0)
        self.worker.start()
        self.timer.start()

        self.download_tab.start_btn.setEnabled(False)
        self.download_tab.pause_btn.setEnabled(True)
        self.download_tab.stop_btn.setEnabled(True)
        self.download_tab.add_log(
            f"Iniciando download em modo paralelo ({threads} threads)...", "info"
        )

    def _connect_worker(self, worker: DownloadWorker) -> None:
        # Telemetria principal vem pelo QTimer; signals só notificam eventos.
        worker.log_signal.connect(self.download_tab.add_log)
        worker.total_size_signal.connect(self._on_worker_total_size)
        worker.finished_signal.connect(
            lambda ok, msg, w=worker: self._on_worker_finished(w, ok, msg)
        )
        worker.segments_map_signal.connect(self.download_tab.segments_map.update_map)
        worker.segment_done_signal.connect(self._on_worker_segment_done)

    def _toggle_pause(self):
        if self._paused_worker is not None:
            self._resume_paused_download()
        elif self.worker is not None:
            self._pause_active_download()

    def _pause_active_download(self):
        """
        Pausa = encerrar o subprocesso (instantâneo) e preservar arquivos.
        A retomada é feita criando um novo `DownloadWorker` com is_resume=True.
        """
        w = self.worker
        if w is None:
            return

        w.pause()  # terminate + preserva arquivos
        self._paused_worker = w
        self._retire_worker(w)
        self.worker = None

        self.timer.stop()
        ratio = self.speed_calc.get_progress_ratio()
        if ratio is not None:
            self.taskbar_progress.set_progress(ratio, paused=True)
        self.download_tab.pause_btn.setText("Retomar")
        self.download_tab.pause_btn.setEnabled(True)
        self.download_tab.stop_btn.setEnabled(True)
        self.download_tab.start_btn.setEnabled(False)
        self.download_tab.speed_label.setText("Velocidade  —")
        self.download_tab.eta_label.setText("Restante  —")
        self.download_tab.add_log(
            "Download pausado. Os arquivos parciais foram preservados.",
            "warning",
        )

    def _resume_paused_download(self):
        """Cria um novo worker que continua do estado salvo pelo pausado."""
        old = self._paused_worker
        if old is None:
            return
        self._paused_worker = None
        # O loop do worker pausado precisa ter lido todo o Pipe para o caminho
        # final estar disponível; normalmente já terminou.
        old.wait(3000)

        # Sem caminho final o engine ainda não tinha criado nada: recomeça como
        # download novo (com nome único), nunca "retoma" em cima do que o
        # usuário digitou, que pode ser um arquivo existente.
        resume_path = old.final_path
        self.worker = DownloadWorker(
            url=old.url,
            output_path=resume_path or old.output_path,
            threads=old.threads,
            speed_counter=self.speed_calc.counter,
            checksum=old.expected_checksum,
            proxy=old.proxy,
            auth=old.auth,
            auto_detect_quality=old.auto_detect_quality,
            connect_timeout=old.connect_timeout,
            custom_headers=old.custom_headers,
            x3d_opt=old.x3d_opt,
            is_resume=resume_path is not None,
        )
        self._connect_worker(self.worker)

        self._taskbar_token += 1
        self.taskbar_progress.set_progress(0.0)
        self.worker.start()
        self.timer.start()

        self.download_tab.start_btn.setEnabled(False)
        self.download_tab.pause_btn.setEnabled(True)
        self.download_tab.pause_btn.setText("Pausar")
        self.download_tab.stop_btn.setEnabled(True)
        self.download_tab.add_log("Retomando download...", "info")

    def _stop_download(self):
        if self.worker:
            self.worker.stop()
        elif self._paused_worker is not None:
            # Stop num download pausado: limpa os arquivos preservados.
            self._abort_paused_download()

    def _purge_paused_files(self):
        """
        Apaga o arquivo em andamento e os part_dirs (swarm/hls) que o engine
        do download pausado declarou ter criado, sem mexer na UI.
        """
        old = self._paused_worker
        self._paused_worker = None
        if old is not None:
            old.remove_partial_files()
            self._record_history(old, STATUS_CANCELLED)

    def _abort_paused_download(self):
        """Stop em download pausado: limpa arquivos e reseta a UI."""
        self._purge_paused_files()
        self.timer.stop()
        self.download_tab.start_btn.setEnabled(True)
        self.download_tab.pause_btn.setEnabled(False)
        self.download_tab.stop_btn.setEnabled(False)
        self.download_tab.pause_btn.setText("Pausar")
        self.download_tab.progress_bar.setValue(0)
        self.download_tab.speed_chart.reset_chart()
        self.speed_calc.reset()
        self.download_tab.segments_map.update_map(0, [])
        self.download_tab.speed_label.setText("Velocidade  —")
        self.download_tab.eta_label.setText("Restante  —")
        self.taskbar_progress.set_error()
        self.download_tab.add_log("Download cancelado.", "warning")

    def _retire_worker(self, worker) -> None:
        """
        Move o worker para a lista de zumbis e agenda sua remoção quando o
        QThread realmente terminar (signal `finished` da QThread, emitido
        após `run()` retornar). Sem isso, o destructor do QObject pode rodar
        enquanto a thread ainda está nos últimos passos do `run()`.
        """
        if worker is None or worker in self._zombie_workers:
            return
        self._zombie_workers.append(worker)

        def _reap():
            try:
                self._zombie_workers.remove(worker)
            except ValueError:
                pass

        worker.finished.connect(_reap)

    # ------------------------------------------------------------------
    # Handlers do Worker
    # ------------------------------------------------------------------

    def _on_worker_total_size(self, total):
        if isinstance(total, dict):
            if total.get("mode") == "segments":
                self.speed_calc.set_total_segments(total["total"], total.get("done", 0))
        else:
            self.speed_calc.set_total_bytes(total)

    def _record_history(self, worker: DownloadWorker, status: str) -> None:
        path = worker.final_path or ""
        size = 0
        if status == STATUS_DONE and path and os.path.isfile(path):
            size = os.path.getsize(path)
        self.history.add(
            url=worker.url,
            output_path=path,
            size=size,
            duration=self.speed_calc.get_duration(),
            status=status,
        )
        self.history_tab.refresh(self.history.history)

    def _on_worker_finished(self, worker, success, message):
        # Sinal atrasado de um worker que já não é o atual (pausado, trocado):
        # tratá-lo apagaria o estado do download em curso.
        if worker is not self.worker:
            return
        self.timer.stop()

        self.download_tab.start_btn.setEnabled(True)
        self.download_tab.pause_btn.setEnabled(False)
        self.download_tab.stop_btn.setEnabled(False)
        self.download_tab.pause_btn.setText("Pausar")

        if success:
            self.download_tab.progress_bar.setValue(100)
            self.taskbar_progress.set_progress(1.0)
            self.download_tab.speed_chart.mark_download_complete()
            self.speed_calc.stop_tracking()
            # Caminho real informado pelo engine (pode ter sufixo "(1)",
            # virado .ts no HLS, etc), e não o input cru do usuário.
            self._record_history(worker, STATUS_DONE)
            self.download_tab.add_log(message, "success")
        else:
            self._record_history(
                worker, STATUS_CANCELLED if worker.stopped_by_user else STATUS_FAILED
            )
            self.download_tab.progress_bar.setValue(0)
            self.download_tab.speed_chart.reset_chart()
            self.speed_calc.reset()
            self.download_tab.segments_map.update_map(0, [])
            self.download_tab.speed_label.setText("Velocidade  —")
            self.download_tab.eta_label.setText("Restante  —")
            self.taskbar_progress.set_error()
            self.download_tab.add_log(message, "warning")

        token = self._taskbar_token
        QTimer.singleShot(1800, lambda: self._clear_taskbar_if_current(token))

        self._retire_worker(worker)
        self.worker = None

    def _on_timer_tick(self):
        """
        Única função que acessa o SpeedCalculator.
        Chamada pelo QTimer a cada UPDATE_INTERVAL ms (thread principal).
        """
        snap = self.speed_calc.get_snapshot()
        self.download_tab.update_ui_with_snapshot(snap)
        self._update_taskbar_progress(snap)

    def _on_worker_segment_done(self):
        self.speed_calc.completed_segments += 1

    def _update_taskbar_progress(self, snap: dict):
        if not self.worker:
            return
        ratio = snap.get("progress_ratio")
        if ratio is None:
            self.taskbar_progress.set_indeterminate()
            return
        self.taskbar_progress.set_progress(ratio, paused=self.worker.is_paused)

    def _clear_taskbar_if_current(self, token: int):
        if token == self._taskbar_token and self.worker is None:
            self.taskbar_progress.clear()

    # ------------------------------------------------------------------
    # Dialogs e Persistência
    # ------------------------------------------------------------------

    def _show_settings(self):
        dlg = SettingsDialog(self.app_settings, self)
        if dlg.exec():
            self.app_settings = dlg.get_settings()
            for k, v in self.app_settings.items():
                if k in _SECRET_SETTINGS:
                    v = protect(v)
                self.settings.setValue(k, v)
            self.download_tab.add_log("Configurações atualizadas.", "success")

    def _show_about(self):
        AboutDialog(get_app_version(), self).exec()

    def _clear_history(self):
        if QMessageBox.question(self, "Confirmar", "Deseja limpar todo o histórico?") == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.history_tab.refresh([])

    def _export_history(self):
        if not self.history.history:
            QMessageBox.information(self, "Exportar", "Não há histórico para exportar.")
            return
        from datetime import datetime
        default_name = f"historico_downloads_{datetime.now():%Y%m%d_%H%M%S}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar histórico", default_name, "JSON (*.json)"
        )
        if not path:
            return
        if self.history.export_to_file(path):
            self.download_tab.add_log(f"Histórico exportado para {path}", "success")
        else:
            QMessageBox.critical(self, "Erro", "Falha ao exportar o histórico.")

    def _check_for_updates(self):
        # Verificação automática em segundo plano
        self.download_tab.add_log("Procurando por atualizações...", "info")
        self._run_update_thread(manual=False)

    def _manual_check_updates(self):
        # Verificação manual com feedback na barra de status
        self.statusBar().showMessage("Verificando atualizações...")
        self._run_update_thread(manual=True)

    def _run_update_thread(self, manual: bool):
        from PyQt6.QtCore import QThread, pyqtSignal

        class UpdateCheckWorker(QThread):
            finished = pyqtSignal(object)
            error = pyqtSignal(str)

            def __init__(self, updater):
                super().__init__()
                self.updater = updater

            def run(self):
                try:
                    info = self.updater.check_for_updates()
                    self.finished.emit(info)
                except Exception as e:
                    self.error.emit(str(e))

        def on_finished(info):
            if manual:
                self.statusBar().clearMessage()
                if info:
                    self._show_update_dialog(info)
                else:
                    QMessageBox.information(self, "Atualização", "Você já está usando a versão mais recente.")
            else:
                if info:
                    self.download_tab.add_log("Nova atualização encontrada!", "success")
                    self._show_update_dialog(info)
                else:
                    self.download_tab.add_log("O programa já está na versão mais recente.", "info")

        def on_error(err):
            if manual:
                self.statusBar().clearMessage()
                QMessageBox.critical(self, "Erro de Conexão", f"Falha ao consultar servidor:\n{err}")
            else:
                self.download_tab.add_log(f"Falha ao procurar atualizações: {err}", "warning")

        # Referência persistente para evitar que o GC limpe a thread
        self._update_thread = UpdateCheckWorker(self.updater)
        self._update_thread.finished.connect(on_finished)
        self._update_thread.error.connect(on_error)
        self._update_thread.start()

    def _show_update_dialog(self, info):
        dlg = UpdateDialog(info, self)
        if not dlg.exec():
            return

        if self._has_unfinished_download():
            # O processo do download roda do mesmo .exe: vivo, ele impede a
            # troca do arquivo e o app fecharia sem reabrir.
            answer = QMessageBox.question(
                self,
                "Atualizar agora",
                "Atualizar agora cancela o download em andamento ou pausado e "
                "apaga o que já foi baixado.\n\nContinuar?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._discard_unfinished_download()

        # Diálogo de progresso
        progress_dlg = UpdateProgressDialog(self)
        progress_dlg.show()

        from PyQt6.QtCore import QThread, pyqtSignal

        class UpdateDownloadWorker(QThread):
            progress = pyqtSignal(str)
            finished = pyqtSignal(bool, str)

            def __init__(self, updater, url):
                super().__init__()
                self.updater = updater
                self.url = url

            def run(self):
                try:
                    def cb(msg):
                        self.progress.emit(msg)
                    self.updater.download_and_install(self.url, progress_callback=cb)
                    # Se chegar aqui, o os._exit(0) dentro do download_and_install
                    # já encerrou o processo — esta linha nunca é alcançada.
                except Exception as e:
                    self.finished.emit(False, str(e))

        self._download_thread = UpdateDownloadWorker(self.updater, info["download_url"])
        self._download_thread.progress.connect(progress_dlg.update_progress)
        self._download_thread.progress.connect(lambda msg: self.download_tab.add_log(msg, "info"))
        self._download_thread.finished.connect(lambda success, msg: progress_dlg.finish(success, msg))
        
        self._download_thread.start()
