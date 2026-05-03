"""
core/updater.py
Verificação e instalação de atualizações do executável.
Sem dependências de PyQt6.
"""

import json
import os
import subprocess
import sys
import tempfile
from typing import Callable, Optional

import requests
from packaging.version import Version

from core.file_utils import get_resource_path


# Variáveis de ambiente que o bootloader do PyInstaller injeta no processo.
# Precisam ser removidas antes de lançar o novo .exe pelo BAT, senão o
# bootloader do novo processo acha que é uma re-execução e tenta usar um
# diretório _MEI antigo que já não existe.
_PYI_ENV_VARS = (
    "_PYI_ARCHIVE_FILE",
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_MEIPASS2",
)


class UpdateCheckError(Exception):
    """Erro ao verificar atualizações (rede, timeout, resposta inválida)."""


def get_app_version(default: str = "0.0") -> str:
    """
    Lê a versão atual do `version.json` empacotado com o app.
    Funciona tanto em modo desenvolvimento quanto no .exe PyInstaller.
    Retorna `default` se a leitura falhar, evitando que o app não inicie
    por causa de um arquivo ausente ou corrompido.
    """
    try:
        path = get_resource_path("version.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        version = str(data.get("version", "")).strip()
        return version or default
    except Exception:
        return default


class Updater:
    """
    Gerencia o ciclo de atualização do aplicativo.

    Fluxo:
    1. check_for_updates() consulta version.json no GitHub.
    2. Se versão nova disponível, retorna o dict com informações.
    3. download_and_install() baixa o novo .exe e executa script BAT de substituição.
    """

    VERSION_URL = (
        "https://raw.githubusercontent.com/DreamerJP/Downloader/main/version.json"
    )

    def __init__(self, current_version: str):
        """
        Parâmetros:
            current_version : versão atual do app (ex: "2.1")
        """
        self.current_version = current_version

    # ------------------------------------------------------------------
    # Verificação
    # ------------------------------------------------------------------

    def check_for_updates(self) -> Optional[dict]:
        """
        Consulta o version.json remoto e compara com a versão atual usando
        comparação semântica (packaging.version.Version), que trata corretamente
        casos como "2.10" > "2.9".

        Formato esperado do JSON:
            {
                "version": "2.1",
                "download_url": "https://...",
                "changelog": ["item 1", "item 2"]
            }

        Retorna:
            dict com informações da nova versão, ou None se já atualizado.

        Lança:
            UpdateCheckError se houver falha de rede ou resposta inválida,
            permitindo que o chamador exiba a mensagem correta ao usuário.
        """
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Downloader/2.1"}
        try:
            response = requests.get(self.VERSION_URL, headers=headers, timeout=10)
            response.raise_for_status()
            info = response.json()
        except requests.exceptions.Timeout as exc:
            raise UpdateCheckError("Tempo limite esgotado ao contatar o servidor.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise UpdateCheckError("Não foi possível conectar ao servidor de atualizações.") from exc
        except requests.exceptions.HTTPError as exc:
            raise UpdateCheckError(f"Servidor retornou erro: {exc.response.status_code}") from exc
        except ValueError as exc:  # JSONDecodeError herda de ValueError
            raise UpdateCheckError("Resposta do servidor não é JSON válido.") from exc
        except Exception as exc:
            raise UpdateCheckError(f"Erro inesperado: {exc}") from exc

        remote_ver_str = str(info.get("version", "")).strip()
        if not remote_ver_str:
            raise UpdateCheckError("Resposta do servidor não contém campo 'version'.")

        download_url = str(info.get("download_url", "")).strip()
        if not download_url:
            raise UpdateCheckError("Resposta do servidor não contém campo 'download_url'.")

        try:
            remote_ver = Version(remote_ver_str)
            current_ver = Version(str(self.current_version).strip())
        except Exception as exc:
            raise UpdateCheckError(f"Versão inválida no servidor: {remote_ver_str!r}") from exc

        if remote_ver > current_ver:
            return info
        return None

    # ------------------------------------------------------------------
    # Download e instalação
    # ------------------------------------------------------------------

    def download_and_install(
        self,
        download_url: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Baixa o novo executável e inicia o script BAT de substituição.

        Deve ser chamado em uma thread separada — nunca na thread principal da UI.
        O processo atual é encerrado pelo script BAT após a substituição.

        Parâmetros:
            download_url      : URL do novo executável
            progress_callback : callback(mensagem) para feedback de progresso
        """
        if not getattr(sys, "frozen", False):
            raise RuntimeError(
                "Atualização automática disponível apenas no executável empacotado."
            )

        current_exe = sys.executable
        if not current_exe.lower().endswith(".exe"):
            raise RuntimeError("Atualização automática suportada apenas para executáveis .exe.")

        if progress_callback:
            progress_callback("Iniciando download da atualização...")

        new_exe = self._download_to_tempfile(download_url, progress_callback)

        if progress_callback:
            progress_callback("Instalando atualização...")

        try:
            current_pid = os.getpid()
            bat_content = self._generate_bat_script(current_exe, new_exe, current_pid)
            bat_path = self._write_bat(bat_content)

            # Limpa as variáveis do bootloader PyInstaller no ambiente passado
            # para o BAT — assim o novo .exe inicia como execução nova, não
            # como re-execução do processo antigo (que está prestes a morrer).
            env = os.environ.copy()
            for var in _PYI_ENV_VARS:
                env.pop(var, None)

            subprocess.Popen(
                [bat_path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS,
                env=env,
            )
        except Exception:
            # Se algo falhar antes de o BAT ser disparado, remove o exe baixado
            # para não deixar lixo em %TEMP%.
            try:
                os.remove(new_exe)
            except OSError:
                pass
            raise

        # os._exit(0) é necessário para garantir que todo o processo (incluindo
        # threads de UI) seja encerrado imediatamente, liberando o handle do
        # executável para o script BAT.
        os._exit(0)

    # ------------------------------------------------------------------
    # Internos — download
    # ------------------------------------------------------------------

    def _download_to_tempfile(
        self,
        download_url: str,
        progress_callback: Optional[Callable[[str], None]],
    ) -> str:
        """
        Baixa o conteúdo da URL para um arquivo temporário e retorna o caminho.
        Se o download falhar (rede, tamanho inválido, arquivo vazio), remove
        o arquivo parcial antes de re-lançar a exceção.
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".exe", prefix="downloader_update_")
        try:
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))

            downloaded = 0
            with os.fdopen(fd, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            progress_callback(f"Baixando atualização... {pct}%")

            # Validação: se o servidor declarou content-length, deve bater.
            if total_size > 0 and downloaded != total_size:
                raise RuntimeError(
                    f"Download incompleto: esperado {total_size} bytes, "
                    f"recebido {downloaded}."
                )
            if downloaded == 0:
                raise RuntimeError("Download retornou arquivo vazio.")

            return tmp_path
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Internos — geração do script BAT
    # ------------------------------------------------------------------

    def _generate_bat_script(self, old_exe: str, new_exe: str, pid: int) -> str:
        """
        Gera o conteúdo do script BAT de substituição do executável.

        Usa 'taskkill /PID' em vez de '/IM' para evitar encerrar outras
        instâncias do aplicativo que estejam abertas ao mesmo tempo.
        """
        old_exe = os.path.normpath(os.path.abspath(old_exe))
        new_exe = os.path.normpath(os.path.abspath(new_exe))
        return (
            "@echo off\n"
            "chcp 65001 >nul\n"
            "setlocal enabledelayedexpansion\n\n"
            f'set "OLD_EXE={old_exe}"\n'
            f'set "NEW_EXE={new_exe}"\n'
            f'set "APP_PID={pid}"\n\n'
            "taskkill /PID %APP_PID% /F >nul 2>&1\n"
            "timeout /t 1 /nobreak >nul\n\n"
            'if not exist "%OLD_EXE%" exit /b 1\n'
            'if not exist "%NEW_EXE%" exit /b 1\n\n'
            'set "MAX=20"\n'
            ":loop\n"
            'del /F /Q "%OLD_EXE%" >nul 2>&1\n'
            'if exist "%OLD_EXE%" (\n'
            "    timeout /t 1 /nobreak >nul\n"
            "    set /a MAX-=1\n"
            "    if !MAX! GTR 0 goto loop\n"
            "    exit /b 1\n"
            ")\n"
            'move /Y "%NEW_EXE%" "%OLD_EXE%" >nul || exit /b 1\n'
            'for %%I in ("%OLD_EXE%") do set "EXE_DIR=%%~dpI"\n'
            'start "" /D "%EXE_DIR%" "%OLD_EXE%"\n'
            "exit /b 0\n"
        )

    def _write_bat(self, content: str) -> str:
        """
        Escreve o script BAT em um arquivo temporário com nome único e
        retorna o caminho. Codificação UTF-8 sem BOM — a primeira linha do
        BAT é 'chcp 65001' para que o cmd interprete acentos corretamente.
        """
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="downloader_update_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            try:
                os.remove(bat_path)
            except OSError:
                pass
            raise
        return bat_path
