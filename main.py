"""
main.py
Ponto de entrada do Downloader v2.1.
"""

import multiprocessing
import sys
import os
import ctypes

# Adiciona o diretório atual ao sys.path para garantir que os pacotes locais sejam encontrados
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from core.file_utils import cleanup_old_temp_dirs, get_resource_path
from ui.main_window import MainWindow
from ui.theme import apply_app_theme


def _set_windows_app_id() -> None:
    """Define um AppUserModelID para o Windows usar o ícone do app na barra."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DreamerJP.Downloader.2"
        )
    except Exception:
        pass


def main():
    # Sem isso, em PyInstaller frozen + Windows, o processo filho do download
    # rodaria a UI de novo em vez do alvo do multiprocessing.
    multiprocessing.freeze_support()

    # 1. Limpeza de resíduos de execuções anteriores (PyInstaller)
    cleanup_old_temp_dirs()
    _set_windows_app_id()

    # 2. Inicialização do Qt
    app = QApplication(sys.argv)
    app_icon = QIcon(get_resource_path("ico.ico"))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    
    # Melhora a renderização de fontes em telas de alta resolução
    if sys.platform == "win32":
        app.setStyle("Fusion")

    # 3. Aplicação do Design System (Material Design)
    apply_app_theme(app)

    # 4. Janela Principal
    window = MainWindow()
    window.show()

    # 5. Loop de execução
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
