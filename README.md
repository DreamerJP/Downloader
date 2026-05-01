# Downloader v2.0

Gerenciador de downloads multithread de alta performance com arquitetura modular, suporte nativo a HLS/M3U8 e integração profunda com o ecossistema Chrome.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-41CD52.svg?style=flat&logo=qt&logoColor=white)](https://www.qt.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0-green.svg?style=flat)](https://github.com/DreamerJP/Downloader/releases)

---

## Visão Geral

O **Downloader v2.0** é uma reengenharia completa focada em performance bruta e estabilidade. Utiliza uma arquitetura multithread massiva com balanceamento dinâmico de carga, permitindo saturar conexões de alta velocidade enquanto mantém uma interface fluida e responsiva baseada no design system "Midnight Pro".

---

## Principais Diferenciais Técnicos

### Performance de Próxima Geração
- **Paralelismo Massivo**: Suporte a até 512 conexões simultâneas por download.
- **Otimização L3 Cache (X3D)**: Algoritmo de segmentação adaptativa (256KB a 32MB) projetado para minimizar cache misses em CPUs modernas.
- **Zero-Disk Overhead**: Sistema de RAM Merging para arquivos até 300MB, processando a união de segmentos inteiramente em memória para máxima velocidade e preservação do SSD.
- **Telemetria via NIC**: Monitoramento de velocidade em tempo real via contadores de hardware (PSUtil), garantindo precisão absoluta sem sobrecarregar as threads de processamento.

### Engine de Mídia Avançada
- **HLS/M3U8 Pro**: Parser inteligente de Master Playlists com seleção automática de resolução (360p até 4K).
- **Descriptografia On-the-fly**: Suporte nativo a streams criptografados com AES-128, realizando a descriptografia de cada segmento em tempo real.
- **Recuperação de Falhas**: Sistema de re-tentativa automática para segmentos corrompidos ou links expirados.

### Integração com Navegador
- **Chrome Extension Monitor**: Captura links de vídeo (M3U8, MP4, TS, MPD) automaticamente durante a navegação.
- **Gerenciamento Nativo**: Instalação e atualização da extensão diretamente pela interface do app, com limpeza automática de metadados ao alternar abas.

---

## Arquitetura Modular (v2.0)

O projeto segue um padrão de separação de responsabilidades rigoroso:

- **core/**: O motor da aplicação. Contém a lógica de segmentação, cálculos de telemetria, detecção de qualidade e persistência de histórico.
- **ui/**: Camada de interface. Componentes desacoplados, diálogos modernos e o design system centralizado em theme.py.
- **workers/**: Orquestração de threads. Gerencia o ciclo de vida dos downloads, atualizações de sistema e tarefas de background.
- **chrome_ext/**: Código fonte da extensão que alimenta o sistema de captura.

---

## Requisitos e Dependências

| Requisito | Versão Mínima |
|-----------|---------------|
| **Sistema Operacional** | Windows 10 ou 11 |
| **Python** | 3.10+ |
| **PyQt6** | 6.4.0+ |
| **Bibliotecas Chave** | requests, m3u8, pycryptodome, psutil |

---

## Desenvolvimento e Build

### Executando via Código Fonte

1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

2. Inicie a aplicação:
   ```bash
   python main.py
   ```

### Geração de Binário (.exe)

O projeto utiliza o PyInstaller com suporte a bundling de assets e metadados de sistema (AppUserModelID):

```bash
# Para gerar o executável usando o spec oficial:
pyinstaller main.spec
```

---

## Licença

Distribuído sob a licença Apache License 2.0. Veja o arquivo LICENSE para detalhes.

---
Desenvolvido por **DreamerJP**
