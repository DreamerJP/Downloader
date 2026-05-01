"""
core/constants.py
Constantes globais do Downloader v2. Sem dependências externas.
"""

# --- Tamanhos de chunk de leitura HTTP ---
CHUNK_SIZE       = 2 * 1024 * 1024   # 2 MB  — padrão geral
SMALL_CHUNK_SIZE = 256 * 1024         # 256 KB — arquivos < 1 MB
LARGE_CHUNK_SIZE = 6 * 1024 * 1024   # 6 MB  — arquivos >= 100 MB

# --- Política de retry ---
RETRY_LIMIT   = 3    # tentativas máximas por parte/segmento
RETRY_BACKOFF = 1.1  # base do backoff exponencial (segundos)

# --- Paths temporários ---
TEMP_DIR     = ".download_parts"
HISTORY_FILE = ".download_history.json"

# --- Timer da UI ---
UPDATE_INTERVAL = 100  # ms entre cada tick de atualização da interface

# --- Timeouts de rede (segundos) ---
CONNECT_TIMEOUT = 5
READ_TIMEOUT    = 10

# --- Pool de conexões ---
MAX_CONNECTIONS = 4096

# --- Qualidade de vídeo (ordem crescente de qualidade) ---
VIDEO_QUALITIES  = ['360p', '480p', '720p', '1080p', '1440p', '2160p', '4K']
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.webm', '.ts']
