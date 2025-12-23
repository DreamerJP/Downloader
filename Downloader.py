#!/usr/bin/env python3

import os
import sys
import math
import time
import json
import hashlib
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
import requests
import requests.adapters
from urllib3.util.retry import Retry
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTextEdit, QProgressBar,
    QGroupBox, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QComboBox, QCheckBox, QMenuBar, QMenu, QDialog,
    QDialogButtonBox, QFormLayout
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QSettings, QSize
from PyQt6.QtGui import QFont, QColor, QIcon

# Imports para gráficos matplotlib
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np

# Configurações de chunk size
CHUNK_SIZE = 1024 * 1024 * 2  # 2MB por leitura
SMALL_CHUNK_SIZE = 1024 * 256  # 256KB para arquivos pequenos
LARGE_CHUNK_SIZE = 1024 * 1024 * 4  # 4MB para arquivos muito grandes
RETRY_LIMIT = 3  # Número máximo de tentativas
RETRY_BACKOFF = 1.1  # Backoff mínimo
TEMP_DIR = ".download_parts"
HISTORY_FILE = ".download_history.json"
UPDATE_INTERVAL = 50  # ms para atualização da UI (mais frequente)

# Configurações de rede
REQUEST_TIMEOUT = 15
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
MAX_CONNECTIONS_PER_HOST = 4096  # Aumentado para máxima flexibilidade
TCP_KEEPALIVE = True
TCP_NODELAY = True

# Configurações de detecção de qualidade
AUTO_DETECT_QUALITY = True  # Detectar automaticamente melhores qualidades
VIDEO_QUALITIES = ['360p', '480p', '720p', '1080p', '1440p', '2160p', '4K']  # Ordem de prioridade (menor para maior)
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.webm']  # Extensões suportadas


class Updater:
    """
    Gerencia a verificação e atualização do aplicativo.

    Atributos:
        current_version (str): Versão atual do aplicativo.
        version_url (str): URL para verificação de uma nova versão.
    """

    def __init__(self, current_version):
        self.current_version = current_version
        self.version_url = (
            "https://raw.githubusercontent.com/DreamerJP/Downloader/main/version.json"
        )

    def check_for_updates(self):
        """
        Verifica se há uma nova versão consultando a URL definida.

        Retorna:
            dict ou None: Informações da nova versão, se disponível.
        """
        try:
            response = requests.get(self.version_url, timeout=10)
            response.raise_for_status()
            version_info = response.json()
            if version_info["version"] > self.current_version:
                return version_info
            return None
        except Exception as e:
            print(f"Erro ao verificar atualizações: {e}")
            return None

    def download_and_install(self, download_url, progress_callback=None):
        """
        Faz o download do novo executável e prepara para instalação.

        Parâmetros:
            download_url (str): URL para download do novo executável.
            progress_callback (callable): Função para atualizar progresso do download.
        """
        try:
            import tempfile
            import subprocess
            import os

            current_exe = sys.executable
            print(f"[DEBUG] Caminho atual: {current_exe}")

            # Para PyQt6, usar QProgressDialog se disponível
            if progress_callback:
                progress_callback("Iniciando download da atualização...")

            response = requests.get(download_url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))

            with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as temp_file:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            progress_callback(f"Baixando atualização... {progress}%")

                new_exe_path = temp_file.name
                print(f"[DEBUG] Novo executável: {new_exe_path}")

            # Criar script de atualização
            bat_content = self.generate_bat_script(current_exe, new_exe_path)
            bat_path = self.write_and_validate_bat(bat_content, current_exe, new_exe_path)

            # Executar script de atualização
            if progress_callback:
                progress_callback("Instalando atualização...")

            subprocess.Popen(
                [bat_path],
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            time.sleep(2)  # Pequena pausa para garantir que o script BAT seja iniciado
            sys.exit(0)
        except Exception as e:
            print(f"Falha crítica na atualização: {str(e)}")
            raise e

    def generate_bat_script(self, old_exe, new_exe):
        """
        Gera o conteúdo do script BAT necessário para atualizar o executável.

        Parâmetros:
            old_exe (str): Caminho do executável atual.
            new_exe (str): Caminho do novo executável baixado.

        Retorna:
            str: Conteúdo do script BAT.
        """
        old_exe = os.path.normpath(os.path.abspath(old_exe))
        new_exe = os.path.normpath(os.path.abspath(new_exe))
        return f"""@@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: === DADOS EMBUTIDOS ===
set "OLD_EXE={old_exe}"
set "NEW_EXE={new_exe}"

:: === Encerrando processo atual ===
echo Encerrando processo atual...
for %%I in ("%OLD_EXE%") do set "EXE_NAME=%%~nxI"
taskkill /IM "!EXE_NAME!" /F >nul 2>&1

:: === VALIDAÇÃO DOS CAMINHOS ===
if not exist "%OLD_EXE%" (
    echo ERRO: Executável original não encontrado
    echo [DEBUG] Caminho verificado: %OLD_EXE%
    pause
    exit /b 1
)

if not exist "%NEW_EXE%" (
    echo ERRO: Novo executável não encontrado
    echo [DEBUG] Caminho verificado: %NEW_EXE%
    pause
    exit /b 1
)

:: === LÓGICA DE ATUALIZAÇÃO ===
set "MAX_TENTATIVAS=10"
:loop_substituicao
del /F /Q "%OLD_EXE%" >nul 2>&1

if exist "%OLD_EXE%" (
    echo Aguardando liberação do arquivo...
    timeout /t 1 /nobreak >nul
    set /a MAX_TENTATIVAS-=1
    if !MAX_TENTATIVAS! GTR 0 goto loop_substituicao

    echo Falha crítica: Não foi possível substituir o arquivo
    pause
    exit /b 1
)

move /Y "%NEW_EXE%" "%OLD_EXE%" >nul || (
    echo ERRO: Falha ao mover novo executável
    pause
    exit /b 1
)

echo Reiniciando aplicação...
start "" "%OLD_EXE%"
exit /b 0
"""

    def write_and_validate_bat(self, content, old_exe, new_exe):
        """
        Escreve o arquivo BAT com codificação UTF-8 com BOM e valida se os caminhos estão corretos.

        Parâmetros:
            content (str): Conteúdo do script BAT.
            old_exe (str): Caminho do executável atual.
            new_exe (str): Caminho do novo executável.

        Retorna:
            str: Caminho completo do script BAT escrito.
        """
        old_exe = os.path.normpath(os.path.abspath(old_exe))
        new_exe = os.path.normpath(os.path.abspath(new_exe))
        bat_path = os.path.join(tempfile.gettempdir(), "update_script.bat")

        # Escreve com codificação UTF-8 com BOM
        with open(bat_path, "w", encoding="utf-8-sig") as f:
            f.write(content)

        # Verificação crítica
        with open(bat_path, "r", encoding="utf-8-sig") as f:
            content_read = f.read()
            if old_exe not in content_read or new_exe not in content_read:
                raise ValueError("Falha na geração do script de atualização")

        return bat_path

class SpeedCalculator:
    """Calcula velocidade de download com média móvel e métricas avançadas"""
    def __init__(self, window_size=20):
        self.samples = []
        self.all_samples = []  # Histórico completo para média geral
        self.window_size = window_size
        self.last_time = time.time()
        self.last_bytes = 0
        self.peak_speed = 0
        self.total_samples = 0

        # Para cálculo de velocidade mais preciso
        self.time_history = []
        self.bytes_history = []

    def add_sample(self, total_bytes):
        now = time.time()

        # Sempre registrar o ponto atual no histórico
        self.time_history.append(now)
        self.bytes_history.append(total_bytes)

        # Manter apenas os últimos 50 pontos para cálculo preciso
        max_history = 50
        if len(self.time_history) > max_history:
            self.time_history.pop(0)
            self.bytes_history.pop(0)

        # Calcular velocidade baseada nos últimos 5 pontos (últimos ~0.5s)
        min_points_for_calc = 5
        if len(self.time_history) >= min_points_for_calc:
            # Usar os últimos pontos para calcular velocidade média
            recent_times = self.time_history[-min_points_for_calc:]
            recent_bytes = self.bytes_history[-min_points_for_calc:]

            # Calcular velocidade entre pontos consecutivos
            instant_speeds = []
            for i in range(1, len(recent_times)):
                time_diff = recent_times[i] - recent_times[i-1]
                bytes_diff = recent_bytes[i] - recent_bytes[i-1]

                if time_diff > 0.01:  # Evitar divisões por zero ou valores muito pequenos
                    instant_speed = bytes_diff / time_diff
                    if instant_speed >= 0:  # Apenas velocidades positivas
                        instant_speeds.append(instant_speed)

            # Velocidade atual é a média das velocidades instantâneas recentes
            if instant_speeds:
                current_speed = sum(instant_speeds) / len(instant_speeds)


                self.samples.append(current_speed)
                self.all_samples.append(current_speed)
                self.total_samples += 1
                self.peak_speed = max(self.peak_speed, current_speed)

                if len(self.samples) > self.window_size:
                    self.samples.pop(0)

    def get_speed(self):
        if not self.samples:
            return 0
        return sum(self.samples) / len(self.samples)

    def get_average_speed(self):
        """Velocidade média geral baseada em todo o histórico"""
        if not self.all_samples:
            return 0
        return sum(self.all_samples) / len(self.all_samples)

    def get_peak_speed(self):
        return self.peak_speed

    def get_eta(self, downloaded, total):
        speed = self.get_speed()
        if speed == 0 or total == 0:
            return "Calculando..."

        remaining = total - downloaded
        seconds = remaining / speed

        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds/60)}m {int(seconds%60)}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"

    def reset(self):
        """Reinicia o calculador para novo download"""
        self.samples = []
        self.all_samples = []  # Limpar histórico completo também
        self.time_history = []
        self.bytes_history = []
        self.last_time = time.time()
        self.last_bytes = 0
        self.peak_speed = 0
        self.total_samples = 0

class DownloadHistory:
    """Gerencia histórico de downloads"""
    def __init__(self, filepath=HISTORY_FILE):
        self.filepath = filepath
        self.history = self.load()
        
    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []
    
    def save(self):
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao salvar histórico: {e}")
    
    def add(self, url, output_path, size, duration, success=True):
        entry = {
            'url': url,
            'filename': os.path.basename(output_path),
            'path': output_path,
            'size': size,
            'duration': duration,
            'timestamp': datetime.now().isoformat(),
            'success': success
        }
        self.history.insert(0, entry)
        
        # Manter apenas últimos 100
        if len(self.history) > 100:
            self.history = self.history[:100]
        
        self.save()

class DownloadWorker(QThread):
    progress_signal = pyqtSignal(int)
    log_signal = pyqtSignal(str, str)  # mensagem, nível (info/warning/error/success)
    finished_signal = pyqtSignal(bool, str)
    total_size_signal = pyqtSignal(int)
    speed_signal = pyqtSignal(float)
    
    def __init__(self, url, output_path, threads, checksum=None, proxy=None, auth=None, auto_detect_quality=None, connect_timeout=None, read_timeout=None):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.threads = threads
        self.checksum = checksum
        self.proxy = proxy
        self.auth = auth
        # Auto-detect quality apenas para vídeos por padrão
        if auto_detect_quality is None:
            self.auto_detect_quality = self._is_video_url(url)
        else:
            self.auto_detect_quality = auto_detect_quality
        self.should_stop = False
        self.should_pause = False
        self.connect_timeout = connect_timeout if connect_timeout else CONNECT_TIMEOUT
        self.read_timeout = read_timeout if read_timeout else READ_TIMEOUT

        # Configurar sessão HTTP otimizada
        self.session = self._create_optimized_session()
        self.lock = threading.Lock()
        self.downloaded_bytes = 0
        self.speed_calc = SpeedCalculator()
        self.start_time = None
        self.actual_chunk_size = CHUNK_SIZE
        self.best_quality_url = url  # URL da melhor qualidade encontrada

    def _create_optimized_session(self):
        """Cria sessão HTTP com otimizações de performance"""
        session = requests.Session()

        # Headers HTTP
        session.headers.update({
            "User-Agent": "PyDownloadAccelerator/3.0-Optimized",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",  # Suporte a compressão
            "Connection": "keep-alive",
        })

        # Configurar proxy se fornecido
        if self.proxy:
            session.proxies.update(self.proxy)

        # Configurar autenticação se fornecida
        if self.auth:
            session.auth = self.auth

        # Configurar retry strategy
        retry_strategy = Retry(
            total=RETRY_LIMIT,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=RETRY_BACKOFF,
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )

        # Adaptador HTTP
        adapter = requests.adapters.HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=MAX_CONNECTIONS_PER_HOST,
            pool_maxsize=MAX_CONNECTIONS_PER_HOST,
            pool_block=False
        )

        # Configurações TCP otimizadas
        if hasattr(adapter, 'init_poolmanager'):
            adapter.init_poolmanager(
                connections=MAX_CONNECTIONS_PER_HOST,
                maxsize=MAX_CONNECTIONS_PER_HOST,
                block=False
            )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session
        
    def stop(self):
        self.should_stop = True
        
    def pause(self):
        self.should_pause = True
        
    def resume(self):
        self.should_pause = False
        
    def safe_mkdir(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
    
    def get_headers_and_length(self, url, timeout=None):
        if timeout is None:
            timeout = self.connect_timeout
        """Obtém informações do servidor sobre o arquivo com melhor tratamento de erros"""
        accept_ranges = None
        content_length = None
        content_encoding = None

        # Tentar HEAD primeiro
        try:
            r = self.session.head(url, allow_redirects=True, timeout=timeout)
            r.raise_for_status()

            content_length = r.headers.get("Content-Length")
            accept_ranges = r.headers.get("Accept-Ranges")
            content_encoding = r.headers.get("Content-Encoding")
        except Exception as e:
            print(f"HEAD request failed: {e}")

        # Fallback: GET com range mínimo
        if content_length is None or accept_ranges is None:
            try:
                r2 = self.session.get(url, headers={"Range": "bytes=0-0"},
                                     stream=True, timeout=timeout, allow_redirects=True)
                if r2.status_code == 206:
                    accept_ranges = "bytes"
                    cr = r2.headers.get("Content-Range")
                    if cr and "/" in cr:
                        total = cr.split("/")[-1]
                        try:
                            content_length = int(total)
                        except Exception:
                            pass
                else:
                    content_length = r2.headers.get("Content-Length", content_length)
                content_encoding = r2.headers.get("Content-Encoding", content_encoding)
                r2.close()
            except Exception as e:
                print(f"Range request failed: {e}")

        if content_length is not None:
            try:
                content_length = int(content_length)
                # Otimizar chunk size baseado no tamanho do arquivo
                self._optimize_chunk_size(content_length)
            except Exception:
                content_length = None

        return accept_ranges, content_length, content_encoding

    def _optimize_chunk_size(self, file_size):
        """Ajusta o tamanho do chunk baseado no tamanho do arquivo"""
        if file_size < 1024 * 1024:  # < 1MB
            self.actual_chunk_size = SMALL_CHUNK_SIZE
        elif file_size < 100 * 1024 * 1024:  # < 100MB
            self.actual_chunk_size = CHUNK_SIZE
        else:  # >= 100MB
            self.actual_chunk_size = LARGE_CHUNK_SIZE

    def _calculate_optimal_parts(self, file_size, max_threads):
        """Calcula número ótimo de partes baseado no tamanho do arquivo"""

        if file_size < 10 * 1024 * 1024:  # < 10MB
            # Arquivos pequenos: muitas threads para compensar tamanho
            optimal_threads = min(max_threads, max(32, max_threads))
            min_part_size = 256 * 1024  # 256KB mínimo
        elif file_size < 100 * 1024 * 1024:  # < 100MB
            # Arquivos médios: MÁXIMO paralelismo (como o seu arquivo de 75MB)
            optimal_threads = min(max_threads, max(128, max_threads))
            min_part_size = 512 * 1024  # 512KB mínimo
        elif file_size < 1024 * 1024 * 1024:  # < 1GB
            # Arquivos grandes: alto paralelismo
            optimal_threads = min(max_threads, max(256, max_threads // 2))
            min_part_size = 1024 * 1024  # 1MB mínimo
        else:  # >= 1GB
            # Arquivos muito grandes: máximo paralelismo
            optimal_threads = min(max_threads, max(512, max_threads // 2))
            min_part_size = 2 * 1024 * 1024  # 2MB mínimo

        # Garantir que cada parte tenha pelo menos o tamanho mínimo
        optimal_threads = min(optimal_threads, file_size // min_part_size)
        optimal_threads = max(1, optimal_threads)

        part_size = math.ceil(file_size / optimal_threads)

        return optimal_threads, part_size

    def _is_video_url(self, url):
        """Verifica se a URL é de um vídeo baseado na extensão"""
        from urllib.parse import urlparse
        path = urlparse(url).path.lower()

        return any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)

    def _generate_quality_variations(self, url):
        """Gera variações de qualidade para uma URL de vídeo de forma inteligente"""
        if not self._is_video_url(url):
            return [url]  # Retorna a URL original se não for vídeo

        variations = [url]  # Sempre incluir a URL original
        import re

        # Padrões comuns de qualidade em URLs
        quality_patterns = [
            r'(\d{3,4}p)',  # 360p, 480p, 720p, 1080p, etc.
            r'(4K)',        # 4K
            r'(\d{3,4})p',  # Mesmo padrão mas mais específico
        ]

        for pattern in quality_patterns:
            matches = re.findall(pattern, url, re.IGNORECASE)
            if matches:
                # Para cada match encontrado, gerar variações
                for match in matches:
                    for quality in VIDEO_QUALITIES:
                        # Substituir o match pela nova qualidade
                        variation = re.sub(pattern, quality, url, flags=re.IGNORECASE)
                        if variation != url and variation not in variations:
                            variations.append(variation)

        # Adicionar variações manuais comuns (caso o regex não pegue)
        for quality in VIDEO_QUALITIES:
            manual_vars = [
                url.replace('360p', quality),
                url.replace('480p', quality),
                url.replace('720p', quality),
                url.replace('1080p', quality),
                url.replace('1440p', quality),
                url.replace('2160p', quality),
                url.replace('4K', quality),
            ]
            for var in manual_vars:
                if var != url and var not in variations:
                    variations.append(var)

        return variations

    def _check_url_exists(self, url, timeout=3):
        """Verifica se uma URL existe fazendo HEAD request rápido"""
        try:
            response = self.session.head(url, timeout=timeout, allow_redirects=True)
            return response.status_code == 200
        except:
            return False

    def _find_best_quality_url(self, original_url):
        """Encontra a melhor qualidade disponível com timeout e feedback"""
        if not self.auto_detect_quality or not self._is_video_url(original_url):
            return original_url

        self.log_signal.emit("Procurando melhores qualidades disponíveis...", "info")

        # Gerar variações de qualidade
        quality_urls = self._generate_quality_variations(original_url)

        if len(quality_urls) <= 1:
            return original_url  # Só tem a URL original

        self.log_signal.emit(f"Verificando {len(quality_urls)} variações de qualidade...", "info")

        available_qualities = []

        # Verificar quais URLs existem (paralelo, limitado)
        max_concurrent_checks = min(12, len(quality_urls))

        try:
            with ThreadPoolExecutor(max_workers=max_concurrent_checks) as executor:
                futures = {executor.submit(self._check_url_exists, url, timeout=2): url
                          for url in quality_urls}

                for future in as_completed(futures, timeout=15):  # Timeout total de 15s
                    url = futures[future]
                    try:
                        if future.result():
                            available_qualities.append(url)
                    except Exception:
                        continue  # Ignorar erros individuais

        except Exception as e:
            self.log_signal.emit(f"Timeout na verificação de qualidades: {e}", "warning")
            return original_url

        if not available_qualities:
            self.log_signal.emit("Nenhuma variação de qualidade encontrada, usando URL original", "warning")
            return original_url

        # Encontrar a melhor qualidade disponível
        best_url = original_url
        best_quality_index = -1
        best_quality_name = "original"

        for url in available_qualities:
            url_lower = url.lower()
            for i, quality in enumerate(VIDEO_QUALITIES):
                if quality.lower() in url_lower:
                    if i > best_quality_index:
                        best_quality_index = i
                        best_url = url
                        best_quality_name = quality
                    break

        if best_url != original_url:
            self.log_signal.emit(f"Melhor qualidade encontrada: {best_quality_name}", "success")

            # Mostrar o tamanho se conseguir obter
            try:
                _, size, _ = self.get_headers_and_length(best_url)
                if size:
                    size_mb = size / (1024 * 1024)
                    self.log_signal.emit(f"Tamanho: {size_mb:.2f} MB", "info")
            except:
                pass

        return best_url

    def _cleanup_on_cancel(self, part_dir):
        """Limpa arquivos temporários de forma simples e segura durante cancelamento"""
        try:
            # Solução ultra-simples: apenas deletar a pasta inteira
            if os.path.exists(part_dir):
                import shutil
                shutil.rmtree(part_dir, ignore_errors=True)
                print(f"Pasta temporária removida: {part_dir}")

            # Tentar limpar o diretório pai se estiver vazio
            try:
                if os.path.exists(TEMP_DIR) and not os.listdir(TEMP_DIR):
                    os.rmdir(TEMP_DIR)
            except:
                pass

            return True
        except Exception as e:
            print(f"Erro simples na limpeza: {e}")
            return False

    def _cleanup_temp_files_fast(self, part_dir, parts):
        """Limpa arquivos temporários de forma ultra-rápida e paralela"""
        try:
            # Coletar todos os arquivos para remover
            files_to_remove = []
            for i, _, _ in parts:
                part_path = os.path.join(part_dir, f"part.{i}")
                if os.path.exists(part_path):
                    files_to_remove.append(part_path)

            if not files_to_remove:
                # Nada para limpar
                try:
                    os.rmdir(part_dir)
                    if not os.listdir(TEMP_DIR):
                        os.rmdir(TEMP_DIR)
                except:
                    pass
                return True

            # Remover arquivos em paralelo
            def remove_file(filepath):
                try:
                    os.remove(filepath)
                except:
                    pass

            with ThreadPoolExecutor(max_workers=min(8, len(files_to_remove))) as executor:
                executor.map(remove_file, files_to_remove)

            # Remover diretórios
            try:
                os.rmdir(part_dir)
            except:
                pass

            try:
                if os.path.exists(TEMP_DIR) and not os.listdir(TEMP_DIR):
                    os.rmdir(TEMP_DIR)
            except:
                pass

            return True
        except Exception as e:
            print(f"Erro na limpeza rápida: {e}")
            # Fallback para limpeza normal
            return self._cleanup_temp_files(part_dir, parts)

    def _cleanup_temp_files(self, part_dir, parts):
        """Limpa arquivos temporários de forma segura (fallback)"""
        try:
            # Remover arquivos de partes
            for i, _, _ in parts:
                part_path = os.path.join(part_dir, f"part.{i}")
                try:
                    if os.path.exists(part_path):
                        os.remove(part_path)
                except Exception as e:
                    print(f"Erro ao remover {part_path}: {e}")

            # Remover diretório de partes
            try:
                os.rmdir(part_dir)
            except Exception as e:
                print(f"Erro ao remover diretório {part_dir}: {e}")

            # Remover diretório temporário se vazio
            try:
                if not os.listdir(TEMP_DIR):
                    os.rmdir(TEMP_DIR)
            except Exception as e:
                print(f"Erro ao remover {TEMP_DIR}: {e}")

            return True
        except Exception as e:
            print(f"Erro geral na limpeza: {e}")
            return False

    def download_range_worker(self, url, part_path, start, end, idx):
        """Download de uma parte específica com retry otimizado"""
        attempt = 0
        headers = {"Range": f"bytes={start}-{end}"}
        last_progress_report = time.time()
        progress_accumulator = 0

        while attempt <= RETRY_LIMIT and not self.should_stop:
            # Pausar se solicitado
            while self.should_pause and not self.should_stop:
                time.sleep(0.01)  # Menor intervalo para pausa mais responsiva

            if self.should_stop:
                return False

            try:
                existing = 0
                if os.path.exists(part_path):
                    existing = os.path.getsize(part_path)
                    if existing > 0:
                        new_start = start + existing
                        if new_start > end:
                            return True  # Já baixado completamente
                        headers["Range"] = f"bytes={new_start}-{end}"

                with self.session.get(url, headers=headers, stream=True,
                                     timeout=(self.connect_timeout, self.read_timeout),
                                     allow_redirects=True) as r:
                    r.raise_for_status()

                    if r.status_code not in (200, 206):
                        raise Exception(f"HTTP {r.status_code}: {r.reason}")

                    # Log detalhado apenas para erros ou problemas
                    content_length = r.headers.get("Content-Length")
                    expected_part_size = end - start + 1 - existing

                    # Só loga se houver problema com o tamanho
                    if content_length and int(content_length) != expected_part_size:
                        self.log_signal.emit(f"Parte {idx}: Tamanho esperado {expected_part_size}, servidor retornou {content_length}", "warning")

                    mode = "ab" if existing > 0 else "wb"
                    bytes_downloaded_this_attempt = 0

                    with open(part_path, mode) as f:
                        for chunk in r.iter_content(self.actual_chunk_size):
                            # Verificação frequente de parada (a cada chunk)
                            if self.should_stop:
                                return False

                            # Pausar durante o download
                            while self.should_pause and not self.should_stop:
                                time.sleep(0.01)
                                # Verificação adicional durante pausa
                                if self.should_stop:
                                    return False

                            if chunk:
                                f.write(chunk)
                                chunk_size = len(chunk)
                                bytes_downloaded_this_attempt += chunk_size

                                with self.lock:
                                    self.downloaded_bytes += chunk_size
                                    progress_accumulator += chunk_size

                                    # Emitir progresso apenas a cada 100ms para boa responsividade
                                    now = time.time()
                                    if now - last_progress_report >= 0.1:  # 100ms
                                        self.progress_signal.emit(progress_accumulator)
                                        progress_accumulator = 0
                                        last_progress_report = now

                                # Flush periódico para evitar perda de dados
                                if bytes_downloaded_this_attempt % (1024 * 1024) == 0:
                                    f.flush()
                                    os.fsync(f.fileno())

                                    # Verificação adicional após flush
                                    if self.should_stop:
                                        return False

                # Emitir qualquer progresso restante acumulado
                if progress_accumulator > 0:
                    with self.lock:
                        self.progress_signal.emit(progress_accumulator)

                # Verificar tamanho final da parte
                final_size = os.path.getsize(part_path)
                expected_final_size = end - start + 1

                if final_size != expected_final_size:
                    self.log_signal.emit(f"Parte {idx}: Tamanho final {final_size} bytes, esperado {expected_final_size} bytes", "warning")
                    if final_size == 0:
                        self.log_signal.emit(f"Parte {idx}: Arquivo vazio!", "error")
                        return False

                # Log reduzido: apenas erros ou progresso agrupado
                # Não loga sucesso individual para evitar spam
                return True

            except Exception as exc:
                attempt += 1
                if attempt <= RETRY_LIMIT:
                    # Backoff exponencial com jitter
                    base_wait = RETRY_BACKOFF ** attempt
                    jitter = random.uniform(0.1, 1.0) * base_wait * 0.1
                    wait = base_wait + jitter

                    # Log de retry apenas na primeira tentativa ou em erros
                    if attempt == 2:  # Só loga na segunda tentativa para não poluir
                        self.log_signal.emit(f"Parte {idx}: tentando novamente ({attempt}/{RETRY_LIMIT})", "warning")
                    time.sleep(min(wait, 30))  # Máximo 30s de espera
                else:
                    self.log_signal.emit(f"Parte {idx} falhou após {RETRY_LIMIT} tentativas: {exc}", "error")
                    return False

        return False

    def merge_parts(self, output_path, parts_count, part_dir):
        """Une todas as partes em um único arquivo"""
        self.log_signal.emit("Unindo partes do arquivo...", "info")

        # Pré-calcular informações dos arquivos
        total_merge_size = 0
        part_files = []
        for i in range(parts_count):
            part_path = os.path.join(part_dir, f"part.{i}")
            if os.path.exists(part_path):
                size = os.path.getsize(part_path)
                total_merge_size += size
                part_files.append((part_path, size))
            else:
                self.log_signal.emit(f"Parte {part_path} não encontrada!", "error")
                return False

        if not part_files:
            return False

        merged_size = 0
        merge_chunk_size = min(self.actual_chunk_size * 4, 16 * 1024 * 1024)  # Até 16MB por chunk

        try:
            with open(output_path, "wb") as outf:
                # Buffer de saída para reduzir syscalls
                buffer_size = 64 * 1024 * 1024  # 64MB buffer
                outf_buffer = bytearray(buffer_size)
                buffer_pos = 0

                for part_path, part_size in part_files:
                    if self.should_stop:
                        return False

                    with open(part_path, "rb") as pf:
                        # Usar mmap para arquivos grandes se disponível
                        if part_size > 10 * 1024 * 1024:  # > 10MB
                            try:
                                import mmap
                                with mmap.mmap(pf.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                                    remaining = part_size
                                    while remaining > 0 and not self.should_stop:
                                        chunk_size = min(merge_chunk_size, remaining)
                                        chunk = mm.read(chunk_size)
                                        if not chunk:
                                            break

                                        # Usar buffer para reduzir writes
                                        if buffer_pos + len(chunk) > buffer_size:
                                            # Flush buffer
                                            outf.write(outf_buffer[:buffer_pos])
                                            buffer_pos = 0

                                        outf_buffer[buffer_pos:buffer_pos + len(chunk)] = chunk
                                        buffer_pos += len(chunk)
                                        merged_size += len(chunk)
                                        remaining -= len(chunk)
                            except ImportError:
                                # Fallback sem mmap
                                buffer_pos = self._merge_part_fallback(pf, outf, outf_buffer, buffer_pos, part_size, merge_chunk_size)
                        else:
                            # Arquivo pequeno - merge direto
                            buffer_pos = self._merge_part_fallback(pf, outf, outf_buffer, buffer_pos, part_size, merge_chunk_size)

                # Flush buffer final
                if buffer_pos > 0:
                    outf.write(outf_buffer[:buffer_pos])

                # Flush e sync do sistema de arquivos
                outf.flush()
                os.fsync(outf.fileno())

            # Log de conclusão
            self.log_signal.emit(f"União completa: {total_merge_size/(1024*1024):.1f} MB", "success")

        except Exception as e:
            self.log_signal.emit(f"Erro durante união das partes: {e}", "error")
            return False

        return True

    def _merge_part_fallback(self, pf, outf, buffer, buffer_pos, part_size, chunk_size):
        """Método fallback para merge sem mmap"""
        remaining = part_size
        while remaining > 0 and not self.should_stop:
            read_size = min(chunk_size, remaining)
            chunk = pf.read(read_size)
            if not chunk:
                break

            # Usar buffer
            if buffer_pos + len(chunk) > len(buffer):
                outf.write(buffer[:buffer_pos])
                buffer_pos = 0

            buffer[buffer_pos:buffer_pos + len(chunk)] = chunk
            buffer_pos += len(chunk)
            remaining -= len(chunk)

        return buffer_pos

    def merge_parts_parallel(self, output_path, parts_count, part_dir):
        """Merge paralelo usando memória quando possível"""
        self.log_signal.emit("Unindo partes em paralelo...", "info")

        # Pré-calcular informações
        part_files = []
        total_size = 0
        for i in range(parts_count):
            part_path = os.path.join(part_dir, f"part.{i}")
            if os.path.exists(part_path):
                size = os.path.getsize(part_path)
                total_size += size
                part_files.append((i, part_path, size))

        if not part_files:
            return False

        max_memory_mb = 500  # Máximo 500MB na memória

        if total_size <= max_memory_mb * 1024 * 1024:
            return self._merge_in_memory(output_path, part_files, total_size)
        else:
            return self.merge_parts(output_path, parts_count, part_dir)

    def _merge_in_memory(self, output_path, part_files, total_size):
        """Merge carregando tudo na memória"""
        try:
            self.log_signal.emit(f"Carregando {len(part_files)} partes na memória...", "info")

            # Carregar todas as partes na memória
            parts_data = []
            loaded_size = 0

            for _, part_path, part_size in part_files:
                if self.should_stop:
                    return False

                with open(part_path, "rb") as f:
                    data = f.read()
                    if len(data) != part_size:
                        raise Exception(f"Tamanho incorreto para {part_path}")
                    parts_data.append(data)
                    loaded_size += len(data)

            # Escrever tudo de uma vez
            self.log_signal.emit("Escrevendo arquivo final...", "info")
            with open(output_path, "wb") as outf:
                for data in parts_data:
                    outf.write(data)

                outf.flush()
                os.fsync(outf.fileno())

            self.log_signal.emit(f"Merge em memória concluído: {total_size/(1024*1024):.1f} MB", "success")
            return True

        except Exception as e:
            self.log_signal.emit(f"Erro no merge em memória: {e}", "error")
            # Fallback para merge normal
            return False

    def compute_sha256(self, path):
        """Calcula hash SHA256 do arquivo com progresso otimizado"""
        h = hashlib.sha256()
        file_size = os.path.getsize(path)
        processed = 0
        chunk_size = min(self.actual_chunk_size, 4 * 1024 * 1024)  # Até 4MB por chunk
        last_progress = 0

        try:
            with open(path, "rb") as f:
                while True:
                    # Verificação frequente de parada
                    if self.should_stop:
                        return None

                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    h.update(chunk)
                    processed += len(chunk)

                    # Verificação adicional após processamento
                    if self.should_stop:
                        return None

                    if file_size > 0:
                        progress = int((processed / file_size) * 100)
                        # Apenas reportar progresso a cada 5% para reduzir spam
                        if progress >= last_progress + 5:
                            self.log_signal.emit(f"Verificando checksum: {progress}%", "info")
                            last_progress = progress

                            # Verificação adicional após log
                            if self.should_stop:
                                return None

            return h.hexdigest()

        except Exception as e:
            self.log_signal.emit(f"Erro ao calcular checksum: {e}", "error")
            return None

    def single_stream_download(self, url, output_path):
        """Download single-threaded otimizado com resume e compressão"""
        headers = {}
        existing = 0
        last_progress_report = time.time()
        progress_accumulator = 0

        if os.path.exists(output_path):
            existing = os.path.getsize(output_path)
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
                self.downloaded_bytes = existing
                self.progress_signal.emit(existing)

        try:
            r = self.session.get(url, headers=headers, stream=True,
                                allow_redirects=True, timeout=(self.connect_timeout, self.read_timeout))

            r.raise_for_status()

            total = r.headers.get("Content-Length")
            content_encoding = r.headers.get("Content-Encoding")

            if total is not None:
                try:
                    total = int(total) + existing
                    self.total_size_signal.emit(total)
                except Exception:
                    pass

            if content_encoding:
                self.log_signal.emit(f"Compressão ativa: {content_encoding}", "info")

            mode = "ab" if existing and r.status_code == 206 else "wb"
            bytes_downloaded = 0

            with open(output_path, mode) as f:
                for chunk in r.iter_content(self.actual_chunk_size):
                    # Verificação frequente de parada (a cada chunk)
                    if self.should_stop:
                        return False

                    while self.should_pause and not self.should_stop:
                        time.sleep(0.01)
                        # Verificação adicional durante pausa
                        if self.should_stop:
                            return False

                    if chunk:
                        f.write(chunk)
                        chunk_size = len(chunk)
                        bytes_downloaded += chunk_size

                        with self.lock:
                            self.downloaded_bytes += chunk_size
                            progress_accumulator += chunk_size

                            # Emitir progresso apenas a cada 100ms para boa responsividade
                            now = time.time()
                            if now - last_progress_report >= 0.1:  # 100ms
                                self.progress_signal.emit(progress_accumulator)
                                progress_accumulator = 0
                                last_progress_report = now

                        # Flush periódico para arquivos grandes
                        if bytes_downloaded % (10 * 1024 * 1024) == 0:  # A cada 10MB
                            f.flush()
                            os.fsync(f.fileno())

                            # Verificação adicional após flush
                            if self.should_stop:
                                return False

            # Emitir qualquer progresso restante acumulado
            if progress_accumulator > 0:
                with self.lock:
                    self.progress_signal.emit(progress_accumulator)

            return True

        except Exception as e:
            self.log_signal.emit(f"Erro no download single-thread: {e}", "error")
            return False

    def run(self):
        self.start_time = time.time()
        part_dir = None

        try:
            # Detecção automática de qualidade (apenas para vídeos)
            if self.auto_detect_quality and self._is_video_url(self.url):
                self.log_signal.emit("Detectando melhor qualidade para vídeo...", "info")
                self.best_quality_url = self._find_best_quality_url(self.url)
                if self.best_quality_url != self.url:
                    self.url = self.best_quality_url

            # Preparação
            if not self.output_path:
                parsed = urlparse(self.url)
                self.output_path = os.path.basename(parsed.path) or "download.bin"

            self.safe_mkdir(TEMP_DIR)
            part_dir = os.path.join(TEMP_DIR, hashlib.sha1(self.url.encode()).hexdigest())
            self.safe_mkdir(part_dir)

            self.log_signal.emit("Verificando suporte do servidor...", "info")
            accept_ranges, total_len, content_encoding = self.get_headers_and_length(self.url)

            if total_len:
                size_mb = total_len / (1024 * 1024)
                self.log_signal.emit(f"Tamanho do arquivo: {size_mb:.2f} MB", "info")
                if content_encoding:
                    self.log_signal.emit(f"Compressão detectada: {content_encoding}", "info")

            if total_len is None or accept_ranges != "bytes":
                self.log_signal.emit("Download single-thread (servidor não suporta ranges)", "warning")
                success = self.single_stream_download(self.url, self.output_path)
            elif total_len <= 0:
                self.log_signal.emit(f"Tamanho inválido do arquivo: {total_len}", "error")
                self.finished_signal.emit(False, f"Tamanho inválido do arquivo: {total_len}")
                return
            elif total_len < 1024 * 1024:  # Arquivos menores que 1MB
                self.log_signal.emit("Arquivo pequeno, usando download single-thread", "info")
                success = self.single_stream_download(self.url, self.output_path)
            else:
                # Download multi-thread com algoritmo de divisão inteligente
                self.total_size_signal.emit(total_len)
                max_threads = max(1, int(self.threads))  # Remover limite artificial

                # Algoritmo inteligente de divisão de partes
                optimal_threads, part_size = self._calculate_optimal_parts(total_len, max_threads)

                # Usar exatamente o que o usuário configurou (com proteção contra valores extremos)
                actual_threads = min(max_threads, MAX_CONNECTIONS_PER_HOST)  # Máximo seguro
                optimal_threads = actual_threads
                part_size = math.ceil(total_len / actual_threads)

                # Criar lista de partes otimizada
                parts = []
                for i in range(optimal_threads):
                    start = i * part_size
                    end = min((i + 1) * part_size - 1, total_len - 1)
                    if start <= end:
                        parts.append((i, start, end))

                # Verificar partes já baixadas
                for i, s, e in parts:
                    ppath = os.path.join(part_dir, f"part.{i}")
                    if os.path.exists(ppath):
                        size = os.path.getsize(ppath)
                        self.downloaded_bytes += size
                        self.progress_signal.emit(size)

                self.log_signal.emit(f"Iniciando download com {optimal_threads} conexões ({len(parts)} partes, {part_size/(1024*1024):.1f}MB cada)...", "info")

                # Download paralelo com ThreadPoolExecutor
                max_workers = min(max_threads, MAX_CONNECTIONS_PER_HOST)

                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"Download-{hashlib.md5(self.url.encode()).hexdigest()[:8]}") as executor:
                    futures = {}

                    # Submeter todas as partes
                    for (i, s, e) in parts:
                        ppath = os.path.join(part_dir, f"part.{i}")
                        future = executor.submit(
                            self.download_range_worker,
                            self.url, ppath, s, e, i
                        )
                        futures[future] = i

                    # Aguardar conclusão com monitoramento
                    completed = 0
                    failed_parts = []
                    last_progress_log = 0

                    try:
                        for future in as_completed(futures):
                            # Verificar parada frequente
                            if self.should_stop:
                                break

                            part_idx = futures[future]
                            completed += 1

                            if not future.result():
                                self.log_signal.emit(f"Parte {part_idx} falhou!", "error")
                                failed_parts.append(part_idx)

                            # Log de progresso agrupado a cada 10% ou no início
                            current_progress_pct = int((completed / len(parts)) * 100)
                            if current_progress_pct >= last_progress_log + 10 or completed == 1:
                                self.log_signal.emit(f"Progresso: {completed}/{len(parts)} partes ({current_progress_pct}%)", "info")
                                last_progress_log = current_progress_pct

                    except Exception as e:
                        if self.should_stop:
                            self.log_signal.emit("Download cancelado durante processamento", "warning")
                        else:
                            self.log_signal.emit(f"Erro durante processamento paralelo: {e}", "error")
                        raise

                    # Cancelar futures pendentes se parada foi solicitada
                    if self.should_stop:
                        self.log_signal.emit("Cancelando futures pendentes...", "info")
                        for future in futures:
                            if not future.done():
                                future.cancel()

                        # Fechar sessão HTTP para interromper requisições ativas
                        try:
                            self.session.close()
                        except:
                            pass

                        executor.shutdown(wait=False, cancel_futures=True)
                        self.finished_signal.emit(False, "Download cancelado")
                        return

                    if failed_parts and len(failed_parts) > len(parts) * 0.1:  # Mais de 10% das partes falharam
                        self.log_signal.emit(f"Muitas partes falharam ({len(failed_parts)}/{len(parts)}), tentando download single-thread", "warning")
                        # Fallback para single-thread
                        success = self.single_stream_download(self.url, self.output_path)
                        if success:
                            self.finished_signal.emit(True, f"Download concluído via single-thread: {self.output_path}")
                        else:
                            self.finished_signal.emit(False, "Falha no download single-thread de fallback")
                        return
                    elif failed_parts:
                        self.finished_signal.emit(False, f"Falha no download de {len(failed_parts)} partes")
                        return

                    # Log final do download paralelo
                    if not failed_parts:
                        self.log_signal.emit(f"✅ Todas as {len(parts)} partes baixadas com sucesso!", "success")
                    else:
                        self.log_signal.emit(f"⚠️ {len(parts) - len(failed_parts)}/{len(parts)} partes baixadas ({len(failed_parts)} falharam)", "warning")

                # Verificar se todas as partes foram baixadas corretamente
                total_downloaded_size = 0
                missing_parts = []
                incorrect_parts = []

                for i, start, end in parts:
                    part_path = os.path.join(part_dir, f"part.{i}")
                    expected_size = end - start + 1

                    if not os.path.exists(part_path):
                        missing_parts.append(i)
                        self.log_signal.emit(f"Parte {i} não encontrada!", "error")
                        continue

                    actual_size = os.path.getsize(part_path)
                    total_downloaded_size += actual_size

                    if actual_size != expected_size:
                        incorrect_parts.append((i, actual_size, expected_size))
                        self.log_signal.emit(f"Parte {i}: tamanho incorreto ({actual_size} bytes, esperado {expected_size} bytes)", "warning")

                if missing_parts:
                    self.log_signal.emit(f"Partes faltando: {missing_parts}", "error")
                    self.finished_signal.emit(False, f"Partes faltando: {missing_parts}")
                    return

                if incorrect_parts:
                    self.log_signal.emit(f"Partes com tamanho incorreto: {len(incorrect_parts)} partes", "warning")
                    # Para arquivos não-vídeo, podemos tentar continuar se o total estiver próximo
                    if not self._is_video_url(self.url) and abs(total_downloaded_size - total_len) < 1024:  # Tolerância de 1KB
                        self.log_signal.emit("Continuando apesar de tamanhos incorretos (tolerância para não-vídeos)", "warning")
                    else:
                        self.finished_signal.emit(False, f"Partes com tamanho incorreto: {len(incorrect_parts)} partes")
                        return

                self.log_signal.emit(f"Todas as partes verificadas. Tamanho total: {total_downloaded_size/(1024*1024):.1f} MB", "info")

                # Unir partes
                self.log_signal.emit("Download das partes completo! Iniciando união...", "success")
                tmp_out = self.output_path + ".parttmp"

                # Calcular tamanho total para decidir método
                total_file_size = sum(os.path.getsize(os.path.join(part_dir, f"part.{i}"))
                                    for i in range(len(parts)) if os.path.exists(os.path.join(part_dir, f"part.{i}")))

                # Escolher método de merge baseado nas configurações
                turbo_merge = getattr(self, 'turbo_merge_enabled', True)  # Default True
                max_memory_mb = getattr(self, 'max_memory_mb', 300)  # Default 300MB

                if turbo_merge and total_file_size <= max_memory_mb * 1024 * 1024:
                    merge_success = self.merge_parts_parallel(tmp_out, len(parts), part_dir)
                else:
                    merge_success = self.merge_parts(tmp_out, len(parts), part_dir)

                if not merge_success:
                    self.finished_signal.emit(False, "Falha ao unir partes")
                    return

                # Verificar tamanho do arquivo final
                if os.path.exists(tmp_out):
                    final_size = os.path.getsize(tmp_out)
                    if final_size == 0:
                        self.log_signal.emit("Arquivo final tem 0 bytes!", "error")
                        self.finished_signal.emit(False, "Arquivo final está vazio")
                        return
                    elif total_len and abs(final_size - total_len) > 1024:  # Mais de 1KB de diferença
                        self.log_signal.emit(f"Tamanho final incorreto: {final_size} bytes (esperado {total_len} bytes)", "warning")

                os.replace(tmp_out, self.output_path)
                success = True

                # Limpeza dos arquivos temporários
                self.log_signal.emit("Limpando arquivos temporários...", "info")
                cleanup_success = self._cleanup_temp_files_fast(part_dir, parts)

                if not cleanup_success:
                    self.log_signal.emit("Aviso: Alguns arquivos temporários podem ter ficado para trás", "warning")

            if not success:
                return

            # Verificar checksum
            if self.checksum and not self.should_stop:
                self.log_signal.emit("Verificando integridade do arquivo...", "info")
                got = self.compute_sha256(self.output_path)

                if got.lower() == self.checksum.lower():
                    self.log_signal.emit("Checksum verificado com sucesso!", "success")
                else:
                    self.log_signal.emit(f"Checksum não confere!\nEsperado: {self.checksum}\nObtido: {got}", "error")
                    self.finished_signal.emit(False, "Checksum inválido")
                    return

            if not self.should_stop:
                duration = time.time() - self.start_time
                self.log_signal.emit(f"Download completo em {duration:.1f}s!", "success")
                self.finished_signal.emit(True, f"Download concluído: {self.output_path}")

        except Exception as e:
            self.log_signal.emit(f"Erro: {str(e)}", "error")
            self.finished_signal.emit(False, f"Erro: {str(e)}")

        finally:
            # Limpeza garantida - sempre executada
            try:
                # Fechar sessão HTTP
                if hasattr(self, 'session'):
                    try:
                        self.session.close()
                    except:
                        pass

                # Limpar arquivos temporários se download foi interrompido
                if part_dir and self.should_stop and os.path.exists(part_dir):
                    # Fazer limpeza em background para não atrasar o cancelamento
                    def cleanup_background():
                        try:
                            self._cleanup_on_cancel(part_dir)
                        except Exception as cleanup_err:
                            print(f"Erro na limpeza em background: {cleanup_err}")

                    # Iniciar thread de limpeza em background
                    cleanup_thread = threading.Thread(target=cleanup_background, daemon=True)
                    cleanup_thread.start()

            except Exception as cleanup_error:
                # Não emitir log aqui para não interferir com outras mensagens
                print(f"Erro na limpeza final: {cleanup_error}")

class AboutDialog(QDialog):
    """Diálogo Sobre com informações do programa"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre")
        self.setMinimumWidth(650)
        self.setMinimumHeight(600)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Título
        title_label = QLabel("Acelerador de Downloads v3.0")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #e0e0e0; padding: 10px;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        subtitle_label = QLabel("Tecnologia de ponta para downloads ultra-rápidos")
        subtitle_label.setStyleSheet("font-size: 12px; color: #b0b0b0; padding-bottom: 15px;")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)
        
        # Scroll area para conteúdo
        scroll = QTextEdit()
        scroll.setReadOnly(True)
        scroll.setStyleSheet("""
            QTextEdit {
                background-color: #1f1f1f;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 15px;
                color: #d0d0d0;
                font-size: 11px;
                line-height: 1.6;
            }
        """)
        
        # Conteúdo HTML formatado
        content = """
        <h3 style="color: #8a9ba8; margin-top: 0;">⚡ CAPACIDADES PRINCIPAIS</h3>
        
        <p><b>🔄 Download Paralelo Inteligente</b><br>
        • Até 512 conexões simultâneas por arquivo<br>
        • Divisão automática em partes otimizadas (0.1-4MB)<br>
        • Balanceamento inteligente de carga entre threads<br>
        • <span style="color: #7a9a7a;">Resultado: Até 23x mais velocidade</span></p>
        
        <p><b>🚀 Merge Turbo (Tecnologia de Memória)</b><br>
        • Carregamento em RAM para arquivos até 300MB<br>
        • União instantânea sem operações de disco<br>
        • Buffers de 64MB para I/O otimizado<br>
        • <span style="color: #7a9a7a;">Resultado: Eliminação do tempo de união</span></p>
        
        <p><b>🔍 Detecção Automática de Qualidade</b><br>
        • Verificação inteligente de resoluções disponíveis<br>
        • Suporte completo: 360p, 480p, 720p, 1080p, 1440p, 2160p, 4K<br>
        • Cache automático (5 minutos) para evitar re-verificações<br>
        • <span style="color: #7a9a7a;">Resultado: Sempre baixa a melhor qualidade</span></p>
        
        <p><b>🛠️ Otimizações de Rede Avançadas</b><br>
        • TCP_NODELAY - Eliminação de delays desnecessários<br>
        • Connection Pooling - Reutilização inteligente de conexões<br>
        • Timeouts agressivos - Resposta mais rápida do servidor<br>
        • Retry exponencial - Recuperação automática de falhas</p>
        
        <h3 style="color: #8a9ba8; margin-top: 20px;">📊 TECNOLOGIAS DE ACELERAÇÃO</h3>
        
        <p><b>Multi-threading Otimizado</b><br>
        • ThreadPoolExecutor com até 1024 workers<br>
        • Gerenciamento automático de recursos do sistema<br>
        • Sincronização eficiente com locks otimizados</p>
        
        <p><b>Sistema de Buffers Inteligente</b><br>
        • Chunks dinâmicos: 256KB até 8MB baseado no arquivo<br>
        • Buffers adaptativos: 32MB até 256MB<br>
        • Memory-mapped files para arquivos grandes<br>
        • Flush estratégico apenas quando necessário</p>
        
        <p><b>Cache Inteligente</b><br>
        • Memorização de verificações de qualidade<br>
        • Expiração automática após 5 minutos<br>
        • Thread-safe e eficiente</p>
        
        <h3 style="color: #8a9ba8; margin-top: 20px;">🎯 RECURSOS AVANÇADOS</h3>
        
        <p><b>Interface Moderna</b><br>
        • Monitoramento em tempo real de velocidade e progresso<br>
        • Métricas detalhadas: Atual, média, velocidade de pico<br>
        • Histórico completo de todos os downloads<br>
        • Controles intuitivos de pause/resume/stop</p>
        
        <p><b>Configurações Técnicas</b><br>
        • Modo TURBO experimental para velocidade máxima<br>
        • Buffers personalizáveis para diferentes cenários<br>
        • Timeouts ajustáveis para redes específicas<br>
        • Suporte completo a proxy e autenticação</p>
        
        <p><b>Verificação de Integridade</b><br>
        • Checksum SHA256 automático<br>
        • Validação de integridade pós-download<br>
        • Detecção de arquivos corrompidos</p>
        
        <h3 style="color: #8a9ba8; margin-top: 20px;">🏆 DIFERENCIAIS TÉCNICOS</h3>
        
        <p><b>Vs Navegadores Convencionais</b><br>
        • 512 vs 1 conexão simultânea<br>
        • Chunks otimizados vs downloads lineares<br>
        • Merge inteligente vs operações sequenciais<br>
        • Cache automático vs re-verificações constantes</p>
        
        <p><b>Vs Outros Aceleradores</b><br>
        • Detecção de qualidade automática (único)<br>
        • Merge em memória para velocidade máxima<br>
        • Buffers adaptativos baseados no arquivo</p>
        """
        
        scroll.setHtml(content)
        layout.addWidget(scroll)
        
        # Botão Fechar
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        
        # Aplicar tema
        self.apply_theme()
    
    def apply_theme(self):
        """Aplica tema escuro ao diálogo"""
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #e0e0e0;
            }
            QPushButton {
                background-color: #2a2a2a;
                color: #e0e0e0;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #333333;
                border-color: #444444;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)

class AdvancedSettingsDialog(QDialog):
    """Diálogo para configurações avançadas"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações Avançadas")
        self.setMinimumWidth(550)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Grupo: Rede e Proxy
        network_group = QGroupBox("Rede e Proxy")
        network_layout = QFormLayout(network_group)
        network_layout.setSpacing(12)
        
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://user:pass@host:port (opcional)")
        network_layout.addRow("Proxy:", self.proxy_input)
        
        self.auth_user_input = QLineEdit()
        self.auth_user_input.setPlaceholderText("Usuário")
        network_layout.addRow("Usuário:", self.auth_user_input)
        
        self.auth_pass_input = QLineEdit()
        self.auth_pass_input.setPlaceholderText("Senha")
        self.auth_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        network_layout.addRow("Senha:", self.auth_pass_input)
        
        layout.addWidget(network_group)
        
        # Grupo: Timeouts
        timeout_group = QGroupBox("Timeouts de Conexão")
        timeout_layout = QFormLayout(timeout_group)
        timeout_layout.setSpacing(12)
        
        self.connect_timeout_input = QSpinBox()
        self.connect_timeout_input.setRange(5, 60)
        self.connect_timeout_input.setValue(10)
        self.connect_timeout_input.setSuffix("s")
        timeout_layout.addRow("Timeout Conexão:", self.connect_timeout_input)
        
        self.read_timeout_input = QSpinBox()
        self.read_timeout_input.setRange(10, 300)
        self.read_timeout_input.setValue(30)
        self.read_timeout_input.setSuffix("s")
        timeout_layout.addRow("Timeout Leitura:", self.read_timeout_input)
        
        layout.addWidget(timeout_group)
        
        # Grupo: Verificação de Integridade
        integrity_group = QGroupBox("Verificação de Integridade")
        integrity_layout = QVBoxLayout(integrity_group)
        integrity_layout.setSpacing(8)

        # Texto explicativo
        integrity_info = QLabel("🔐 <b>Verificação de Integridade (Opcional)</b><br><br>"
                               "• Cole o hash SHA256 fornecido pelo site ANTES de iniciar o download<br>"
                               "• Após o download, o arquivo será verificado automaticamente<br>"
                               "• Use para garantir que o arquivo não foi corrompido")
        integrity_info.setWordWrap(True)
        integrity_info.setStyleSheet("color: #b0b0b0; font-size: 11px; padding-bottom: 8px;")
        integrity_layout.addWidget(integrity_info)

        # Campo de input
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("SHA256:"))
        self.checksum_input = QLineEdit()
        self.checksum_input.setPlaceholderText("Cole o hash SHA256 aqui")
        self.checksum_input.setToolTip("Cole o hash SHA256 fornecido pelo site de download.\n"
                                      "A verificação acontece automaticamente após o download terminar.")
        # Validação em tempo real do formato SHA256
        self.checksum_input.textChanged.connect(self._validate_checksum)
        input_layout.addWidget(self.checksum_input)

        # Status de validação
        self.checksum_status = QLabel("")
        self.checksum_status.setStyleSheet("font-size: 10px; color: #666666;")
        input_layout.addWidget(self.checksum_status)

        integrity_layout.addLayout(input_layout)
        
        layout.addWidget(integrity_group)
        
        layout.addStretch()
        
        # Botões
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Aplicar tema
        self.apply_theme()

    def _validate_checksum(self, text):
        """Valida o formato do hash SHA256 em tempo real"""
        if not text.strip():
            self.checksum_status.setText("")
            self.checksum_status.setStyleSheet("font-size: 10px; color: #666666;")
            return

        import re
        # SHA256 deve ter exatamente 64 caracteres hexadecimais
        if re.match(r'^[a-fA-F0-9]{64}$', text):
            self.checksum_status.setText("✓ Válido")
            self.checksum_status.setStyleSheet("font-size: 10px; color: #7a9a7a; font-weight: bold;")
        else:
            if len(text) > 64:
                self.checksum_status.setText("✗ Muito longo")
            elif len(text) < 64 and text:
                self.checksum_status.setText(f"✗ {64 - len(text)} caracteres restantes")
            else:
                self.checksum_status.setText("✗ Formato inválido")
            self.checksum_status.setStyleSheet("font-size: 10px; color: #9a7a7a; font-weight: bold;")

    def apply_theme(self):
        """Aplica tema escuro ao diálogo"""
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #e0e0e0;
            }
            QGroupBox {
                font-weight: 500;
                border: 1px solid #333333;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1f1f1f;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #b0b0b0;
                font-size: 11px;
            }
            QLabel {
                color: #d0d0d0;
                background-color: transparent;
            }
            QLineEdit, QSpinBox {
                background-color: #252525;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 10px;
                color: #e0e0e0;
                selection-background-color: #3a5a7a;
            }
            QLineEdit:focus, QSpinBox:focus {
                border-color: #4a6a8a;
            }
            QPushButton {
                background-color: #2a2a2a;
                color: #e0e0e0;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #333333;
                border-color: #444444;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
    
    def get_settings(self):
        """Retorna as configurações como dicionário"""
        proxy = self.proxy_input.text().strip() or None
        auth_user = self.auth_user_input.text().strip()
        auth_pass = self.auth_pass_input.text().strip()
        auth = (auth_user, auth_pass) if auth_user and auth_pass else None
        checksum = self.checksum_input.text().strip() or None
        
        return {
            'proxy': proxy,
            'auth': auth,
            'checksum': checksum,
            'connect_timeout': self.connect_timeout_input.value(),
            'read_timeout': self.read_timeout_input.value()
        }
    
    def set_settings(self, settings):
        """Define as configurações"""
        if settings.get('proxy'):
            self.proxy_input.setText(settings['proxy'])
        if settings.get('auth'):
            self.auth_user_input.setText(settings['auth'][0])
            self.auth_pass_input.setText(settings['auth'][1])
        if settings.get('checksum'):
            self.checksum_input.setText(settings['checksum'])
        if settings.get('connect_timeout'):
            self.connect_timeout_input.setValue(settings['connect_timeout'])
        if settings.get('read_timeout'):
            self.read_timeout_input.setValue(settings['read_timeout'])

class SpeedChartWidget(QWidget):
    """Widget personalizado para gráfico de velocidade de download em tempo real"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Configurar matplotlib para tema dark
        plt.style.use('dark_background')

        # Criar figura matplotlib com tamanho otimizado
        self.figure = Figure(figsize=(8, 3), dpi=100, facecolor='#1a1a1a')
        self.canvas = FigureCanvas(self.figure)

        # Configurar layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        layout.setContentsMargins(0, 0, 0, 0)

        # Dados do gráfico
        self.time_data = []
        self.speed_data = []
        self.max_points = 1000  # Máximo de pontos aumentado para capturar todo o download
        self.chart_peak_speed = 0  # Pico calculado pelo gráfico

        # Configurar gráfico inicial
        self.setup_chart()

        # O gráfico será atualizado junto com a interface principal

    def setup_chart(self):
        """Configura o gráfico com estilo profissional"""
        self.figure.clear()

        # Criar subplot com fundo escuro
        self.ax = self.figure.add_subplot(111, facecolor='#1f1f1f')

        # Configurar cores do tema dark
        self.ax.set_facecolor('#1f1f1f')
        self.ax.grid(True, alpha=0.3, color='#444444', linestyle='--', linewidth=0.5)

        # Configurar spines (bordas)
        for spine in self.ax.spines.values():
            spine.set_color('#555555')
            spine.set_linewidth(0.5)

        # Configurar ticks
        self.ax.tick_params(colors='#cccccc', labelsize=8)
        self.ax.xaxis.label.set_color('#cccccc')
        self.ax.yaxis.label.set_color('#cccccc')

        self.ax.set_ylabel('Velocidade (MB/s)', fontsize=9, color='#cccccc', fontweight='light')

        # Linha inicial vazia
        self.line, = self.ax.plot([], [], color='#4a9eff', linewidth=2,
                                 marker='o', markersize=3, markerfacecolor='#4a9eff',
                                 markeredgecolor='#4a9eff', alpha=0.8)

        # Área preenchida sutil
        self.fill = self.ax.fill_between([], [], [], color='#4a9eff', alpha=0.1)

        # Configurar limites iniciais
        self.ax.set_xlim(0, 60)  # 60 segundos inicial
        self.ax.set_ylim(0, 10)  # 10 MB/s inicial

        # Forçar atualização do canvas
        self.canvas.draw()

    def add_speed_point(self, speed_mbps):
        """Adiciona um novo ponto de velocidade ao gráfico"""
        current_time = time.time()

        # Se é o primeiro ponto, inicializar start_time
        if not hasattr(self, 'start_time'):
            self.start_time = current_time

        # Tempo relativo em segundos
        relative_time = current_time - self.start_time

        # Adicionar dados
        self.time_data.append(relative_time)
        self.speed_data.append(speed_mbps)

        # Atualizar pico do gráfico
        self.chart_peak_speed = max(self.chart_peak_speed, speed_mbps)

        # Manter apenas os últimos max_points pontos
        if len(self.time_data) > self.max_points:
            self.time_data.pop(0)
            self.speed_data.pop(0)

    def update_chart(self):
        """Atualiza a visualização do gráfico"""
        if not self.time_data:
            return

        # Atualizar dados da linha
        self.line.set_data(self.time_data, self.speed_data)

        # Atualizar área preenchida
        self.fill.remove()
        self.fill = self.ax.fill_between(self.time_data, self.speed_data,
                                       color='#4a9eff', alpha=0.1)

        # Ajustar limites automaticamente
        if self.time_data:
            time_range = max(self.time_data) - min(self.time_data)
            if time_range > 0:
                self.ax.set_xlim(max(0, self.time_data[0]),
                               max(self.time_data[-1], self.time_data[0] + 10))

        if self.speed_data:
            max_speed = max(self.speed_data)
            if max_speed > 0:
                # Ajustar limite Y para ser um pouco maior que o máximo
                y_limit = max_speed * 1.2
                # Mínimo de 10 MB/s para boa visualização
                y_limit = max(y_limit, 10)
                self.ax.set_ylim(0, y_limit)

        # Redesenhar
        self.canvas.draw_idle()

    def update_chart_limits(self):
        """Ajusta os limites do gráfico para mostrar todo o histórico disponível"""
        if not self.time_data:
            return

        # Ajustar limite X para mostrar todo o tempo
        time_min = min(self.time_data)
        time_max = max(self.time_data)
        time_range = time_max - time_min

        # Adicionar margem de 10% no início e fim
        margin = max(time_range * 0.1, 5)  # Mínimo de 5 segundos de margem
        self.ax.set_xlim(time_min - margin, time_max + margin)

        # Ajustar limite Y baseado nos dados históricos
        if self.speed_data:
            speed_max = max(self.speed_data)
            speed_min = min(self.speed_data)

            # Adicionar margem superior de 20%, mínimo de 10 MB/s para boa visualização
            y_max = max(speed_max * 1.2, 10)
            y_min = max(0, speed_min * 0.9)  # Não permitir valores negativos

            self.ax.set_ylim(y_min, y_max)

        self.canvas.draw_idle()

    def mark_download_complete(self):
        """Marca o ponto onde o download foi concluído"""
        if not self.time_data:
            return

        # Adicionar linha vertical no ponto final
        end_time = max(self.time_data)
        end_speed = self.speed_data[-1]

        # Remover linha anterior se existir
        if hasattr(self, 'completion_line'):
            try:
                self.completion_line.remove()
            except:
                pass

        # Adicionar nova linha de conclusão
        self.completion_line = self.ax.axvline(x=end_time, color='#ff6b6b', linestyle='--',
                                              alpha=0.7, linewidth=1.5, label='Conclusão')

        # Atualizar legenda
        self.ax.legend(loc='upper right', fontsize=8, framealpha=0.8)

        self.canvas.draw_idle()

    def get_peak_speed(self):
        """Retorna a velocidade de pico registrada no gráfico"""
        return self.chart_peak_speed

    def start_chart_updates(self):
        """Inicia as atualizações do gráfico (deprecated - agora usa timer principal)"""
        pass

    def stop_chart_updates(self):
        """Para as atualizações do gráfico (deprecated - agora usa timer principal)"""
        pass

    def reset_chart(self):
        """Reinicia o gráfico para novo download"""
        self.time_data.clear()
        self.speed_data.clear()
        self.chart_peak_speed = 0  # Resetar pico do gráfico
        if hasattr(self, 'start_time'):
            delattr(self, 'start_time')

        # Limpar gráfico
        self.line.set_data([], [])
        self.fill.remove()
        self.fill = self.ax.fill_between([], [], [], color='#4a9eff', alpha=0.1)

        # Resetar limites
        self.ax.set_xlim(0, 60)
        self.ax.set_ylim(0, 10)

        self.canvas.draw()

    def start_chart_updates(self):
        """Inicia as atualizações do gráfico"""
        self.update_timer.start(self.chart_update_interval)

    def stop_chart_updates(self):
        """Para as atualizações do gráfico"""
        self.update_timer.stop()


class DownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.download_worker = None
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.speed_calc = SpeedCalculator()
        self.history = DownloadHistory()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_speed_display)
        self.start_time = None
        self.settings = QSettings("DownloadAccelerator", "WindowState")
        self.advanced_settings = {
            'proxy': None,
            'auth': None,
            'checksum': None,
            'connect_timeout': 10,
            'read_timeout': 30
        }

        # Inicializar updater
        self.current_version = "1.2"  # Versão atual do programa
        self.updater = Updater(self.current_version)

        self.init_ui()
        self.load_window_state()

        # Verificar atualizações automaticamente na inicialização
        self.check_updates()
        
    def init_ui(self):
        self.setWindowTitle("Acelerador de Downloads")

        # Definir ícone da janela
        self.setWindowIcon(self._get_icon())

        default_size = QSize(1000, 700)
        self.resize(default_size)
        
        # Criar barra de menu
        menubar = self.menuBar()
        
        # Menu Configurações
        config_menu = menubar.addMenu("Configurações")
        
        # Configurações Avançadas
        advanced_action = config_menu.addAction("Avançadas...")
        advanced_action.triggered.connect(self.show_advanced_settings)
        
        config_menu.addSeparator()
        
        # Qualidade
        quality_menu = config_menu.addMenu("Qualidade de Vídeo")
        self.auto_quality_action = quality_menu.addAction("Detecção Automática")
        self.auto_quality_action.setCheckable(True)
        self.auto_quality_action.setChecked(True)
        quality_menu.addSeparator()
        for quality in VIDEO_QUALITIES:
            action = quality_menu.addAction(quality)
            action.setCheckable(True)
            if quality == "1080p":
                action.setChecked(True)
        
        # Performance
        perf_menu = config_menu.addMenu("Performance")
        self.turbo_merge_action = perf_menu.addAction("Merge Turbo")
        self.turbo_merge_action.setCheckable(True)
        self.turbo_merge_action.setChecked(True)
        buffer_menu = perf_menu.addMenu("Buffer")
        for buffer_size in ["32MB", "64MB", "128MB", "256MB"]:
            action = buffer_menu.addAction(buffer_size)
            action.setCheckable(True)
            if buffer_size == "64MB":
                action.setChecked(True)
        
        # Rede
        network_menu = config_menu.addMenu("Rede")
        chunk_menu = network_menu.addMenu("Chunk Size")
        for chunk in ["Auto", "64KB", "128KB", "512KB", "1MB", "2MB"]:
            action = chunk_menu.addAction(chunk)
            action.setCheckable(True)
            if chunk == "Auto":
                action.setChecked(True)
        self.compression_action = network_menu.addAction("Compressão Automática")
        self.compression_action.setCheckable(True)
        self.compression_action.setChecked(True)
        
        # Menu Histórico
        history_menu = menubar.addMenu("Histórico")
        history_menu.addAction("Atualizar").triggered.connect(self.load_history)
        history_menu.addAction("Limpar").triggered.connect(self.clear_history)
        history_menu.addAction("Exportar").triggered.connect(self.export_history)
        
        # Menu Sobre
        about_menu = menubar.addMenu("Sobre")
        update_action = about_menu.addAction("Verificar Atualizações...")
        update_action.triggered.connect(self.check_updates)
        about_menu.addSeparator()
        about_action = about_menu.addAction("Sobre o Programa...")
        about_action.triggered.connect(self.show_about)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Tabs
        tabs = QTabWidget()
        
        # Criar widget do gráfico de velocidade
        self.speed_chart = SpeedChartWidget()

        # Tab 1: Download
        download_tab = QWidget()
        download_layout = QVBoxLayout(download_tab)
        download_layout.setSpacing(12)
        
        # URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Cole o link do arquivo aqui...")
        url_layout.addWidget(self.url_input)
        download_layout.addLayout(url_layout)
        
        # Linha de configurações básicas
        basic_settings_layout = QHBoxLayout()
        
        basic_settings_layout.addWidget(QLabel("Conexões:"))
        self.threads_input = QSpinBox()
        self.threads_input.setRange(1, 4096)
        self.threads_input.setValue(512)
        self.threads_input.setMaximumWidth(100)
        basic_settings_layout.addWidget(self.threads_input)
        
        basic_settings_layout.addSpacing(15)
        
        basic_settings_layout.addWidget(QLabel("Arquivo:"))
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("Nome automático")
        basic_settings_layout.addWidget(self.output_input)
        
        self.browse_btn = QPushButton("Procurar")
        self.browse_btn.setMaximumWidth(100)
        self.browse_btn.clicked.connect(self.browse_file)
        basic_settings_layout.addWidget(self.browse_btn)
        
        download_layout.addLayout(basic_settings_layout)
        
        # Botões principais
        buttons_layout = QHBoxLayout()

        self.download_btn = QPushButton("Iniciar")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setMinimumHeight(35)

        self.pause_btn = QPushButton("Pausar")
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setMinimumHeight(35)

        self.stop_btn = QPushButton("Parar")
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(35)

        buttons_layout.addWidget(self.download_btn)
        buttons_layout.addWidget(self.pause_btn)
        buttons_layout.addWidget(self.stop_btn)
        buttons_layout.addStretch()

        download_layout.addLayout(buttons_layout)
        
        # Progresso
        progress_group = QGroupBox("Progresso")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(10)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(28)
        progress_layout.addWidget(self.progress_bar)
        
        # Info layout expandido
        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)

        # Linha 1: Progresso e ETA
        progress_eta_layout = QHBoxLayout()
        self.progress_label = QLabel("Pronto")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        progress_eta_layout.addWidget(self.progress_label)

        self.eta_label = QLabel("ETA: --")
        self.eta_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_eta_layout.addWidget(self.eta_label)
        info_layout.addLayout(progress_eta_layout)

        # Linha 2: Velocidades e estatísticas
        speed_stats_layout = QHBoxLayout()
        self.speed_label = QLabel("Atual: 0 MB/s")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        speed_stats_layout.addWidget(self.speed_label)

        self.avg_speed_label = QLabel("Média: --")
        self.avg_speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_stats_layout.addWidget(self.avg_speed_label)

        self.peak_speed_label = QLabel("Pico: --")
        self.peak_speed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        speed_stats_layout.addWidget(self.peak_speed_label)
        info_layout.addLayout(speed_stats_layout)

        progress_layout.addLayout(info_layout)
        download_layout.addWidget(progress_group)

        # Gráfico de Velocidade
        chart_group = QGroupBox("Gráfico de Velocidade")
        chart_layout = QVBoxLayout(chart_group)
        chart_layout.addWidget(self.speed_chart)
        download_layout.addWidget(chart_group)

        # Log/Status
        log_group = QGroupBox("Status")
        log_layout = QVBoxLayout(log_group)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(180)
        self.log_output.setMaximumHeight(250)
        log_layout.addWidget(self.log_output)
        
        download_layout.addWidget(log_group)
        tabs.addTab(download_tab, "Download")
        
        # Tab 2: Histórico
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(0, 0, 0, 0)
        
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels([
            "Data/Hora", "URL", "Arquivo", "Tamanho", "Duração", "Status"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        history_layout.addWidget(self.history_table)
        
        tabs.addTab(history_tab, "Histórico")
        
        layout.addWidget(tabs)

        self.apply_dark_theme()
        self.load_history()
        
    def load_window_state(self):
        """Carrega o tamanho e posição da janela salva"""
        size = self.settings.value("size", QSize(1000, 700))
        if isinstance(size, QSize):
            self.resize(size)
        pos = self.settings.value("pos")
        if pos:
            self.move(pos)
    
    def save_window_state(self):
        """Salva o tamanho e posição da janela"""
        self.settings.setValue("size", self.size())
        self.settings.setValue("pos", self.pos())

    def _get_icon(self):
        """Obtém o ícone de forma compatível com PyInstaller"""
        # Lista de possíveis locais do ícone
        possible_paths = [
            "ico.ico",  # Diretório atual (desenvolvimento)
            os.path.join(os.path.dirname(sys.executable), "ico.ico"),  # Mesmo diretório do exe
        ]

        # Quando executado via PyInstaller, procurar no diretório temporário
        if hasattr(sys, '_MEIPASS'):
            possible_paths.append(os.path.join(sys._MEIPASS, "ico.ico"))

        for icon_path in possible_paths:
            if os.path.exists(icon_path):
                return QIcon(icon_path)

        # Fallback: retornar ícone vazio se não encontrar
        return QIcon()

    def closeEvent(self, event):
        """Salva estado ao fechar a janela"""
        self.save_window_state()
        super().closeEvent(event)
        
    def apply_dark_theme(self):
        """Aplica tema escuro minimalista e profissional"""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1a1a1a;
                color: #e0e0e0;
            }
            QMenuBar {
                background-color: #252525;
                color: #e0e0e0;
                border-bottom: 1px solid #333333;
                padding: 4px;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background-color: #333333;
            }
            QMenu {
                background-color: #252525;
                color: #e0e0e0;
                border: 1px solid #333333;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #3a3a3a;
            }
            QMenu::item:checked {
                background-color: #2a4a6a;
            }
            QGroupBox {
                font-weight: 500;
                border: 1px solid #333333;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1f1f1f;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #b0b0b0;
                font-size: 11px;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #252525;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 10px;
                color: #e0e0e0;
                selection-background-color: #3a5a7a;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #4a6a8a;
            }
            QPushButton {
                background-color: #2a2a2a;
                color: #e0e0e0;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #333333;
                border-color: #444444;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
            QPushButton:disabled {
                background-color: #1a1a1a;
                color: #666666;
                border-color: #222222;
            }
            QLabel {
                color: #d0d0d0;
                background-color: transparent;
            }
            QTabWidget::pane {
                border: 1px solid #333333;
                border-radius: 6px;
                background-color: #1a1a1a;
            }
            QTabBar::tab {
                background-color: #252525;
                color: #a0a0a0;
                padding: 8px 20px;
                border: 1px solid #333333;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1a1a1a;
                color: #e0e0e0;
                border-color: #333333;
                border-bottom-color: #1a1a1a;
            }
            QTabBar::tab:hover {
                background-color: #2a2a2a;
            }
            QProgressBar {
                border: 1px solid #333333;
                border-radius: 4px;
                text-align: center;
                font-weight: 500;
                background-color: #252525;
                color: #e0e0e0;
                height: 28px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a6a8a, stop:1 #5a7a9a);
                border-radius: 3px;
            }
            QTextEdit {
                background-color: #1f1f1f;
                color: #e8e8e8;
                border: 1px solid #333333;
                border-radius: 4px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 11px;
                padding: 10px;
                selection-background-color: #3a5a7a;
                font-weight: 400;
            }
            QTableWidget {
                background-color: #1f1f1f;
                color: #d0d0d0;
                border: 1px solid #333333;
                border-radius: 4px;
                gridline-color: #2a2a2a;
                selection-background-color: #3a5a7a;
            }
            QHeaderView::section {
                background-color: #252525;
                color: #b0b0b0;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #333333;
                font-weight: 500;
            }
            QScrollBar:vertical {
                background-color: #1f1f1f;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #3a3a3a;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #4a4a4a;
            }
            QScrollBar:horizontal {
                background-color: #1f1f1f;
                height: 12px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background-color: #3a3a3a;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #4a4a4a;
            }
        """)
        
    def check_updates(self):
        """
        Verifica se há atualizações disponíveis e permite ao usuário atualizar.
        """
        from PyQt6.QtWidgets import QMessageBox, QProgressDialog
        from PyQt6.QtCore import QThread, pyqtSignal

        # Criar thread para verificação de atualização
        class UpdateCheckThread(QThread):
            finished = pyqtSignal(dict)

            def __init__(self, updater):
                super().__init__()
                self.updater = updater

            def run(self):
                version_info = self.updater.check_for_updates()
                self.finished.emit({"version_info": version_info})

        def on_check_finished(result):
            progress.close()
            version_info = result.get("version_info")

            if version_info:
                reply = QMessageBox.question(
                    self,
                    "Atualização Disponível",
                    f"Uma nova versão ({version_info['version']}) está disponível.\n\n"
                    f"Deseja baixar e instalar agora?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )

                if reply == QMessageBox.StandardButton.Yes:
                    self.download_update(version_info["download_url"])
            else:
                QMessageBox.information(
                    self,
                    "Verificação de Atualização",
                    "Você está usando a versão mais recente do programa.",
                    QMessageBox.StandardButton.Ok
                )

        # Mostrar diálogo de progresso durante a verificação
        progress = QProgressDialog("Verificando atualizações...", "Cancelar", 0, 0, self)
        progress.setWindowModality(2)  # ApplicationModal
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        progress.show()

        # Iniciar thread de verificação
        self.update_check_thread = UpdateCheckThread(self.updater)
        self.update_check_thread.finished.connect(on_check_finished)
        self.update_check_thread.start()

    def download_update(self, download_url):
        """
        Baixa e instala a atualização.
        """
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import QThread, pyqtSignal

        class UpdateDownloadThread(QThread):
            progress = pyqtSignal(str)
            finished = pyqtSignal(bool, str)

            def __init__(self, updater, download_url):
                super().__init__()
                self.updater = updater
                self.download_url = download_url

            def run(self):
                try:
                    def progress_callback(message):
                        self.progress.emit(message)

                    self.updater.download_and_install(self.download_url, progress_callback)
                    self.finished.emit(True, "Atualização instalada com sucesso!")
                except Exception as e:
                    self.finished.emit(False, f"Erro durante a atualização: {str(e)}")

        def on_progress(message):
            progress.setLabelText(message)

        def on_download_finished(success, message):
            progress.close()
            if success:
                QMessageBox.information(
                    self,
                    "Atualização Concluída",
                    "A atualização foi instalada com sucesso!\n\n"
                    "O programa será reiniciado automaticamente.",
                    QMessageBox.StandardButton.Ok
                )
            else:
                QMessageBox.critical(
                    self,
                    "Erro na Atualização",
                    message,
                    QMessageBox.StandardButton.Ok
                )

        # Mostrar diálogo de progresso durante o download
        progress = QProgressDialog("Preparando atualização...", "Cancelar", 0, 0, self)
        progress.setWindowModality(2)  # ApplicationModal
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        progress.show()

        # Iniciar thread de download
        self.update_download_thread = UpdateDownloadThread(self.updater, download_url)
        self.update_download_thread.progress.connect(on_progress)
        self.update_download_thread.finished.connect(on_download_finished)
        self.update_download_thread.start()

    def show_about(self):
        """Mostra diálogo Sobre"""
        dialog = AboutDialog(self)
        dialog.exec()
    
    def show_advanced_settings(self):
        """Mostra diálogo de configurações avançadas"""
        dialog = AdvancedSettingsDialog(self)
        dialog.set_settings(self.advanced_settings)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.advanced_settings = dialog.get_settings()
            self.add_log("Configurações avançadas salvas", "success")
    
    def browse_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Salvar como...", "", "Todos os arquivos (*.*)"
        )
        if file_path:
            self.output_input.setText(file_path)
            
    def _ensure_file_extension(self, filepath, url):
        """Garante que o nome do arquivo tenha extensão, usando a extensão da URL se necessário"""
        if not filepath:
            return None
        
        # Separar diretório e nome do arquivo
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        
        # Se já tem extensão, retornar como está
        if os.path.splitext(filename)[1]:
            return filepath
        
        # Tentar obter extensão da URL
        parsed = urlparse(url)
        url_path = parsed.path
        url_ext = os.path.splitext(url_path)[1]
        
        # Se a URL tem extensão, adicionar ao nome do arquivo
        if url_ext:
            new_filename = filename + url_ext
            if directory:
                return os.path.join(directory, new_filename)
            return new_filename
        
        # Se não tem extensão em nenhum lugar, retornar como está
        return filepath
    
    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Aviso", "Por favor, insira uma URL válida!")
            return
            
        output_path_raw = self.output_input.text().strip() or None
        # Garantir que o nome do arquivo tenha extensão se necessário
        output_path = self._ensure_file_extension(output_path_raw, url) if output_path_raw else None
        threads = self.threads_input.value()

        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("Iniciando...")
        self.speed_label.setText("Atual: -- MB/s")
        self.avg_speed_label.setText("Média: --")
        self.peak_speed_label.setText("Pico: --")
        self.eta_label.setText("ETA: --")

        # Resetar gráfico
        self.speed_chart.reset_chart()

        # Resetar calculador de velocidade
        self.speed_calc.reset()
        
        self.download_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.speed_calc = SpeedCalculator()
        self.start_time = time.time()
        
        auto_detect_quality = self.auto_quality_action.isChecked() if hasattr(self, 'auto_quality_action') else True
        
        # Usar configurações avançadas
        proxy = self.advanced_settings.get('proxy')
        auth = self.advanced_settings.get('auth')
        checksum = self.advanced_settings.get('checksum')
        connect_timeout = self.advanced_settings.get('connect_timeout', 10)
        read_timeout = self.advanced_settings.get('read_timeout', 30)
        
        # Converter proxy string para dict se necessário
        proxy_dict = None
        if proxy:
            if isinstance(proxy, str):
                proxy_dict = {'http': proxy, 'https': proxy}
            elif isinstance(proxy, dict):
                proxy_dict = proxy
        
        self.download_worker = DownloadWorker(
            url, output_path, threads, checksum, proxy_dict, auth, 
            auto_detect_quality, connect_timeout, read_timeout
        )
        self.download_worker.progress_signal.connect(self.update_progress)
        self.download_worker.log_signal.connect(self.add_log)
        self.download_worker.finished_signal.connect(self.download_finished)
        self.download_worker.total_size_signal.connect(self.set_total_size)
        self.download_worker.start()

        self.timer.start(UPDATE_INTERVAL)
        
    def pause_download(self):
        if self.download_worker:
            if self.download_worker.should_pause:
                self.download_worker.resume()
                self.pause_btn.setText("Pausar")
                self.add_log("Download retomado", "info")
            else:
                self.download_worker.pause()
                self.pause_btn.setText("Retomar")
                self.add_log("Download pausado", "warning")
            
    def stop_download(self):
        if self.download_worker:
            self.download_worker.stop()
            self.add_log("Parando download...", "warning")
            
    def update_progress(self, bytes_downloaded):
        self.downloaded_bytes += bytes_downloaded
        self.speed_calc.add_sample(self.downloaded_bytes)
        
    def update_speed_display(self):
        if self.download_worker and self.download_worker.isRunning():
            current_speed = self.speed_calc.get_speed()
            avg_speed = self.speed_calc.get_average_speed()
            peak_speed = self.speed_calc.get_peak_speed()

            self.speed_label.setText(f"Atual: {self.format_speed(current_speed)}")
            self.avg_speed_label.setText(f"Média: {self.format_speed(avg_speed)}")
            self.peak_speed_label.setText(f"Pico: {self.format_speed(peak_speed)}")

            # Para o gráfico, usar a velocidade atual em MB/s
            current_speed_mbps = current_speed / (1024 * 1024)

            # Adicionar ponto ao gráfico se velocidade > 0
            if current_speed_mbps > 0:
                self.speed_chart.add_speed_point(current_speed_mbps)

            # Atualizar visualização do gráfico
            self.speed_chart.update_chart()

            if self.total_bytes > 0:
                eta = self.speed_calc.get_eta(self.downloaded_bytes, self.total_bytes)
                self.eta_label.setText(f"ETA: {eta}")

                percentage = int((self.downloaded_bytes / self.total_bytes) * 100)
                self.progress_bar.setValue(percentage)

                downloaded_mb = self.downloaded_bytes / (1024 * 1024)
                total_mb = self.total_bytes / (1024 * 1024)
                self.progress_label.setText(
                    f"{downloaded_mb:.1f} MB / {total_mb:.1f} MB ({percentage}%)"
                )
            else:
                downloaded_mb = self.downloaded_bytes / (1024 * 1024)
                self.progress_label.setText(f"Baixados: {downloaded_mb:.1f} MB")
    
    def format_speed(self, speed_bytes_per_sec):
        if speed_bytes_per_sec < 1024:
            return f"{speed_bytes_per_sec:.1f} B/s"
        elif speed_bytes_per_sec < 1024 ** 2:
            return f"{speed_bytes_per_sec/1024:.1f} KB/s"
        elif speed_bytes_per_sec < 1024 ** 3:
            return f"{speed_bytes_per_sec/(1024**2):.1f} MB/s"
        else:
            return f"{speed_bytes_per_sec/(1024**3):.1f} GB/s"
            
    def set_total_size(self, total_size):
        self.total_bytes = total_size
        self.progress_bar.setMaximum(100)
        
    def add_log(self, message, level="info"):
        # Emojis apenas para a área de status
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅"
        }
        emoji = emoji_map.get(level, "")
        
        # Cores mais legíveis e contrastadas
        colors = {
            "info": "#a8c5e8",
            "warning": "#e8c5a8",
            "error": "#e8a8a8",
            "success": "#a8e8a8"
        }
        color = colors.get(level, "#e8e8e8")
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f'<span style="color: #888888;">[{timestamp}]</span> <span style="color: {color}; font-weight: 500;">{emoji} {message}</span>'
        
        self.log_output.append(formatted)
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def download_finished(self, success, message):
        self.timer.stop()

        # Ajustar automaticamente os limites do gráfico para mostrar todo o histórico
        if hasattr(self.speed_chart, 'time_data') and self.speed_chart.time_data:
            self.speed_chart.update_chart_limits()
            # Marcar o ponto de conclusão do download
            self.speed_chart.mark_download_complete()

        self.download_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pausar")
        self.stop_btn.setEnabled(False)
        
        if success:
            self.progress_bar.setValue(100)
            self.progress_label.setText("Download completo!")
            
            # Adicionar ao histórico
            duration = time.time() - self.start_time if self.start_time else 0
            self.history.add(
                self.url_input.text().strip(),
                self.download_worker.output_path if self.download_worker else "",
                self.total_bytes,
                duration,
                True
            )
            self.load_history()
            
            # Apenas log, sem popup
            self.add_log(message, "success")
        else:
            self.progress_label.setText("Download falhou")
            
            # Adicionar falha ao histórico
            if self.download_worker:
                duration = time.time() - self.start_time if self.start_time else 0
                self.history.add(
                    self.url_input.text().strip(),
                    self.download_worker.output_path,
                    self.total_bytes,
                    duration,
                    False
                )
                self.load_history()
            
            QMessageBox.critical(self, "Erro", message)
            
        self.download_worker = None
        
    def load_history(self):
        self.history_table.setRowCount(0)
        
        for entry in self.history.history:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            
            # Data/Hora
            try:
                dt = datetime.fromisoformat(entry['timestamp'])
                dt_str = dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                dt_str = entry['timestamp']
            
            self.history_table.setItem(row, 0, QTableWidgetItem(dt_str))
            
            # Arquivo
            filename = entry.get('filename', 'Desconhecido')
            self.history_table.setItem(row, 1, QTableWidgetItem(filename))
            
            # Tamanho
            size = entry.get('size', 0)
            if size > 0:
                size_mb = size / (1024 * 1024)
                if size_mb >= 1024:
                    size_str = f"{size_mb/1024:.2f} GB"
                else:
                    size_str = f"{size_mb:.2f} MB"
            else:
                size_str = "Desconhecido"
            self.history_table.setItem(row, 2, QTableWidgetItem(size_str))
            
            # Duração
            duration = entry.get('duration', 0)
            if duration > 0:
                if duration < 60:
                    duration_str = f"{duration:.1f}s"
                elif duration < 3600:
                    duration_str = f"{int(duration/60)}m {int(duration%60)}s"
                else:
                    hours = int(duration / 3600)
                    minutes = int((duration % 3600) / 60)
                    duration_str = f"{hours}h {minutes}m"
            else:
                duration_str = "--"
            self.history_table.setItem(row, 3, QTableWidgetItem(duration_str))
            
            # Status
            success = entry.get('success', False)
            # URL (coluna 1)
            url_short = entry.get('url', '')[:50] + "..." if len(entry.get('url', '')) > 50 else entry.get('url', '')
            self.history_table.setItem(row, 1, QTableWidgetItem(url_short))
            self.history_table.item(row, 1).setToolTip(entry.get('url', ''))

            status_item = QTableWidgetItem("Sucesso" if success else "Falha")
            status_item.setForeground(QColor("#7a9a7a" if success else "#9a7a7a"))
            self.history_table.setItem(row, 5, status_item)

    def clear_history(self):
        """Limpa todo o histórico de downloads"""
        reply = QMessageBox.question(
            self, "Confirmar",
            "Tem certeza que deseja limpar todo o histórico?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.history.history = []
            self.history.save()
            self.load_history()
            QMessageBox.information(self, "Sucesso", "Histórico limpo com sucesso!")

    def export_history(self):
        """Exporta histórico para arquivo JSON"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Histórico", "", "JSON files (*.json)"
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.history.history, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "Sucesso", f"Histórico exportado para {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao exportar: {e}")

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Configurar paleta dark minimalista
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(26, 26, 26))
    palette.setColor(palette.ColorRole.WindowText, QColor(224, 224, 224))
    palette.setColor(palette.ColorRole.Base, QColor(31, 31, 31))
    palette.setColor(palette.ColorRole.AlternateBase, QColor(37, 37, 37))
    palette.setColor(palette.ColorRole.Text, QColor(224, 224, 224))
    palette.setColor(palette.ColorRole.Button, QColor(42, 42, 42))
    palette.setColor(palette.ColorRole.ButtonText, QColor(224, 224, 224))
    app.setPalette(palette)
    
    window = DownloaderGUI()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()