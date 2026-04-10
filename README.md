# Downloader

Acelerador de downloads multi-thread com suporte a HLS/M3U8, interface gráfica avançada e extensão integrada para o Chrome.

[![Python](https://img.shields.io/badge/python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.5+-41CD52.svg?style=flat&logo=qt&logoColor=white)](https://www.qt.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.6-red.svg?style=flat)](https://github.com/DreamerJP/Downloader/releases)

---

## Visão Geral

Ferramenta de download desenvolvida em Python com interface PyQt6, capaz de baixar arquivos comuns e streams de vídeo HLS/M3U8 com alta performance usando centenas de conexões paralelas. Inclui uma extensão para o Chrome que captura links de vídeo automaticamente enquanto você navega.

---

## Funcionalidades

### ⚡ Performance
- Download paralelo com até **512 conexões simultâneas** por arquivo
- Chunk size adaptativo: **256 KB a 32 MB** dependendo do tamanho do arquivo
- Merge em RAM para arquivos até ~300 MB (zero operações de disco extras)
- Otimização **X3D**: chunks de 32 MB para CPUs com cache L3 3D (AMD X3D e similares)
- Monitoramento em tempo real: velocidade atual, média, pico e ETA

### 🎬 Suporte a Streams HLS/M3U8
- Parser completo de **Master Playlist** com seleção automática da resolução máxima
- Download paralelo de segmentos `.ts` com montagem sequencial automática
- Suporte a **criptografia AES-128** — descriptografia automática por segmento
- Fallback inteligente em caso de segmentos com falha

### 🧩 Extensão do Chrome — DreamerJP Advanced Interceptor
- Captura links de vídeo (M3U8, MP4, TS, MPD) enquanto você assiste no browser
- Instalação com **um clique** diretamente pelo app (via registro do Windows)
- Desinstalação limpa também pela interface
- Sem necessidade de publicar na Chrome Web Store

### 🛠️ Recursos Técnicos
- Headers HTTP customizados por download (`User-Agent`, `Referer`, `Cookie` etc.)
- Verificação de integridade via **checksum SHA-256** pós-download
- Suporte a proxy HTTP/HTTPS com autenticação
- Detecção automática de qualidade para URLs de vídeo (360p → 4K)
- Sistema de **atualização automática** integrado
- Histórico completo de downloads com exportação JSON

---

## Requisitos

| Item | Versão mínima |
|------|--------------|
| Python | 3.10+ |
| SO | Windows 10/11 |
| Chrome (opcional) | Qualquer versão recente |

---

## Instalação

### Executável (recomendado para usuários finais)

Baixe `Downloader.exe` na seção [Releases](https://github.com/DreamerJP/Downloader/releases) e execute diretamente — sem instalar nada.

### Modo desenvolvimento (a partir do código-fonte)

```bash
# 1. Clonar o repositório
git clone https://github.com/DreamerJP/Downloader.git
cd Downloader

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Executar
python Downloader.py
```

### Dependências principais
```
PyQt6>=6.5.0
matplotlib>=3.7.0
numpy>=1.24.0
requests>=2.31.0
urllib3>=2.0.0
m3u8>=6.0.0
pycryptodome>=3.20.0
```

---

## Uso

### Download básico
1. Cole a URL do arquivo no campo **URL**
2. Ajuste o número de **Conexões** (padrão: 512)
3. Clique em **Iniciar**

### Download de vídeo HLS/M3U8
1. Cole a URL da playlist `.m3u8` no campo **URL**
2. O app detecta automaticamente o tipo de stream e seleciona a melhor resolução
3. Clique em **Iniciar** — os segmentos são baixados em paralelo e montados automaticamente

### Extensão do Chrome
1. Abra a aba **🧩 Extensão Chrome** no app
2. Clique em **Instalar Extensão**
3. Reinicie o Chrome
4. Navegue normalmente — a extensão captura vídeos automaticamente

---

## Estrutura do Projeto

```
Downloader/
├── Downloader.py          # Aplicação principal (core + interface)
├── Downloader.spec        # Configuração do PyInstaller
├── ChromeExtension/       # Extensão do Chrome (empacotada no .exe)
│   ├── manifest.json
│   ├── background.js
│   ├── content.js
│   ├── injected.js
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
├── requirements.txt       # Dependências Python
├── version.json           # Controle de versão e changelog
├── ico.ico                # Ícone da aplicação
└── README.md              # Documentação
```

---

## Build do Executável

```bash
pip install pyinstaller
pyinstaller Downloader.spec
```

> O `Downloader.spec` já está configurado com todos os `hiddenimports` necessários (`m3u8`, `Crypto`, `matplotlib` backend Qt6) e inclui a pasta `ChromeExtension` automaticamente no bundle.

---

## Principais Classes

| Classe | Responsabilidade |
|--------|-----------------|
| `DownloadWorker` | Engine de download: multi-thread, HLS, AES, merge |
| `ChromeExtensionInstaller` | Instalação/remoção da extensão via registro do Windows |
| `Updater` | Verificação e instalação de novas versões |
| `SpeedCalculator` | Métricas de velocidade com média móvel |
| `DownloadHistory` | Histórico persistente em JSON |
| `DownloaderGUI` | Interface principal (PyQt6 + matplotlib) |

---

## Licença

Apache License 2.0 — consulte o arquivo [LICENSE](LICENSE) para detalhes.
