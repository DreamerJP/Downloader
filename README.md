# Downloader

Acelerador de downloads multi-thread com interface gráfica avançada e otimizações de performance.

[![Python](https://img.shields.io/badge/python-3.8+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.0+-41CD52.svg?style=flat&logo=qt&logoColor=white)](https://www.qt.io)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.5-red.svg?style=flat)](https://github.com/DreamerJP/Downloader/releases)

---

## Visão Geral

Ferramenta de download multi-thread desenvolvida em Python com interface PyQt6, oferecendo alta performance através de conexões paralelas e otimizações inteligentes de buffer e chunk size.

### Principais Funcionalidades

**Performance**
- Download multi-thread com até centenas de conexões simultâneas
- Otimização automática de chunk size baseada no tamanho do arquivo
- Algoritmo de merge otimizado para arquivos de grande volume
- Monitoramento de velocidade em tempo real com gráficos matplotlib

**Recursos Técnicos**
- Verificação de integridade via checksum SHA-256
- Suporte completo a proxy HTTP/HTTPS com autenticação
- Detecção automática de qualidade para conteúdo de vídeo
- Sistema de atualização automática integrado

**Interface**
- Interface gráfica moderna com tema dark
- Visualização de métricas de download em tempo real
- Histórico completo de downloads realizados
- Configurações granulares de conexão e performance

---

## Requisitos

### Sistema
- **Python**: 3.8 ou superior
- **SO**: Windows (suporte principal)

### Dependências
```
PyQt6>=6.0.0
matplotlib>=3.5.0
requests>=2.28.0
urllib3>=1.26.0
```

---

## Instalação

### Via pip (Recomendado)
```bash
pip install -r requirements.txt
python Downloader.py
```

### Instalação manual de dependências
```bash
pip install PyQt6 matplotlib requests urllib3
```

### Executável pré-compilado
Disponível na seção [Releases](https://github.com/DreamerJP/Downloader/releases) do repositório.

---

## Uso

### Configuração Básica

| Parâmetro | Descrição | Valor Recomendado |
|-----------|-----------|-------------------|
| URL | Endereço do arquivo para download | - |
| Destino | Diretório de salvamento | - |
| Threads | Número de conexões paralelas | 512 |

### Configurações Avançadas

**Otimização de Rede**
- Chunk size adaptável (1KB - 10MB)
- Buffer dinâmico baseado em latência
- Timeout configurável por conexão

**Proxy e Autenticação**
- Suporte a HTTP/HTTPS proxy
- Autenticação básica e digest
- Bypass de proxy para domínios específicos

**Qualidade de Vídeo**
- Detecção automática de resolução disponível
- Seleção manual de qualidade
- Fallback automático para qualidades inferiores

---

## Estrutura do Projeto

```
Downloader/
├── Downloader.py          # Core da aplicação
├── requirements.txt       # Dependências do projeto
├── version.json          # Controle de versionamento
├── README.md             # Documentação
└── ico.ico              # Ícone da aplicação
```

---

## Desenvolvimento

### Executar em modo debug
```bash
python Downloader.py --debug
```

### Build do executável
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=ico.ico Downloader.py
```

### Estrutura de classes principais
- `DownloadManager`: Gerenciamento de threads e chunks
- `UIHandler`: Interface gráfica e eventos
- `UpdateSystem`: Sistema de atualização automática
- `NetworkOptimizer`: Otimizações de rede e buffer

---

## Performance

### Benchmarks
- Arquivo 1GB: ~512 threads = 5-8x mais rápido que download single-thread
- Merge de chunks: Processamento em blocos de 64MB para otimização de memória
- Overhead de thread: <2% do tempo total de download

### Otimizações Implementadas
- Buffer circular para redução de I/O em disco
- Lazy loading de chunks para economia de memória
- Conexão keep-alive para redução de handshakes TCP

---

## Licença

Apache License 2.0 - Consulte o arquivo LICENSE para detalhes.
