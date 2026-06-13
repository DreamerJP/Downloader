# Downloader

Gerenciador de downloads multithread de alta performance com arquitetura modular, suporte nativo a HLS/M3U8 e integração profunda com o ecossistema Chrome.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-41CD52.svg?style=flat&logo=qt&logoColor=white)](https://www.qt.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat)](LICENSE)
---

## Visão Geral

O **Downloader** é uma reengenharia completa focada em performance bruta e estabilidade. Utiliza uma arquitetura multithread massiva com balanceamento dinâmico de carga, permitindo saturar conexões de alta velocidade enquanto mantém uma interface fluida e responsiva baseada no design system "Midnight Pro".

---

## Principais Diferenciais Técnicos

### Performance de Próxima Geração
- **Paralelismo Massivo**: Centenas de conexões simultâneas por download (512 por padrão, configurável).
- **Segmentação Adaptativa**: O tamanho de chunk se ajusta ao arquivo (256 KB a 6 MB), com um modo opcional de chunk grande (32 MB) para máquinas com bastante cache/memória.
- **Escrita Direta no Arquivo Final**: Cada worker grava sua faixa diretamente no arquivo pré-alocado via `seek`, eliminando a etapa de junção (merge) de partes em disco.
- **Telemetria de Velocidade**: A velocidade exibida é lida da placa de rede via `psutil` — suave como o Gerenciador de Tarefas do Windows e sem sobrecarregar as threads de download. (Observação: reflete o tráfego total da máquina, não apenas este download.)

### Engine de Mídia Avançada
- **HLS/M3U8 Pro**: Parser inteligente de Master Playlists com seleção automática de resolução (360p até 4K).
- **Descriptografia On-the-fly**: Suporte nativo a streams criptografados com AES-128, realizando a descriptografia de cada segmento em tempo real.
- **Recuperação de Falhas**: Sistema de re-tentativa automática para segmentos corrompidos ou links expirados.

### Integração com Navegador
- **Chrome Extension Monitor**: Captura links de vídeo (M3U8, MP4, TS, MPD) automaticamente durante a navegação.
- **Gerenciamento Nativo**: Instalação e atualização da extensão diretamente pela interface do app, com limpeza automática de metadados ao alternar abas.

---

## Arquitetura Modular

O projeto segue um padrão de separação de responsabilidades rigoroso:

- **core/**: O motor da aplicação. Contém a lógica de segmentação, cálculos de telemetria, detecção de qualidade e persistência de histórico.
- **ui/**: Camada de interface. Componentes desacoplados, diálogos modernos e o design system centralizado em theme.py.
- **workers/**: Orquestração de threads. Gerencia o ciclo de vida dos downloads, atualizações de sistema e tarefas de background.
- **ChromeExtension/**: Código fonte da extensão do Chrome que realiza a captura de links de mídia.
- **chrome_ext/**: Lógica interna do aplicativo para instalação, desinstalação e gerenciamento da extensão.

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
   python src/main.py
   ```

### Geração de Binário (.exe)

O projeto utiliza o PyInstaller com suporte a bundling de assets e metadados de sistema (AppUserModelID). Rode a partir da raiz do repositório:

```bash
# Para gerar o executável usando o spec oficial:
pyinstaller build/main.spec
```

---

## Licença

Distribuído sob a licença Apache License 2.0. Veja o arquivo LICENSE para detalhes.

---
Desenvolvido por **DreamerJP**
