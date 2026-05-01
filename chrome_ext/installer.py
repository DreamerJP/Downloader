"""
chrome_ext/installer.py
Lógica para instalação e gerenciamento da extensão do Chrome "Downloader Interceptor".
Sem dependências de PyQt6.
"""

import os
import shutil
import subprocess
import sys
from typing import Optional


class ChromeExtensionInstaller:
    """
    Gerencia os arquivos da extensão do Chrome e facilita a instalação manual.
    
    A extensão permite interceptar downloads no navegador e enviá-los para o app.
    """

    def __init__(self):
        self.app_data_path = self._get_app_data_path()
        self.ext_dest_path = os.path.join(self.app_data_path, "chrome_extension")

    def _get_app_data_path(self) -> str:
        """Retorna o caminho da pasta de dados do app no usuário."""
        path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DownloaderV2")
        os.makedirs(path, exist_ok=True)
        return path

    def get_source_ext_path(self) -> str:
        """Localiza a pasta da extensão nos recursos do programa."""
        # Em modo frozen, o .spec empacota ChromeExtension como chrome_extension.
        # Em modo dev, a pasta fonte fica na raiz do repositório.
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS  # type: ignore[attr-defined]
            candidates = [
                os.path.join(base, "chrome_extension"),
                os.path.join(base, "ChromeExtension"),
            ]
        else:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            candidates = [
                os.path.join(project_root, "ChromeExtension"),
                os.path.join(os.path.dirname(__file__), "source"),
            ]

        for path in candidates:
            if os.path.exists(os.path.join(path, "manifest.json")):
                return path
        return candidates[0]

    def check_status(self) -> dict:
        """Retorna o status atual da instalação da extensão."""
        source_exists = os.path.exists(self.get_source_ext_path())
        installed = os.path.exists(os.path.join(self.ext_dest_path, "manifest.json"))
        
        return {
            "source_available": source_exists,
            "installed": installed,
            "path": self.ext_dest_path
        }

    def install(self) -> bool:
        """Copia os arquivos da extensão para a pasta AppData."""
        source = self.get_source_ext_path()
        if not os.path.exists(source):
            return False
            
        try:
            if os.path.exists(self.ext_dest_path):
                shutil.rmtree(self.ext_dest_path)
            shutil.copytree(source, self.ext_dest_path)
            return True
        except Exception as e:
            print(f"[ChromeExt] Erro na instalação: {e}")
            return False

    def uninstall(self) -> bool:
        """Remove os arquivos da extensão do AppData."""
        try:
            if os.path.exists(self.ext_dest_path):
                shutil.rmtree(self.ext_dest_path)
            return True
        except Exception:
            return False

    def open_chrome_extensions(self):
        """Abre o Chrome na página de extensões."""
        try:
            url = "chrome://extensions/"
            if sys.platform == "win32":
                os.startfile(url)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
        except Exception:
            pass
