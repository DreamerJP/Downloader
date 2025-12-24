# 🚀 Downloader

**Acelerador de Downloads Ultrarrápido** - Uma ferramenta poderosa para downloads de alta velocidade com interface moderna e recursos avançados.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.0+-green.svg)
![License](https://img.shields.io/badge/License-Apache--2.0-yellow.svg)
![Version](https://img.shields.io/badge/Version-1.4-red.svg)

## ✨ Características Principais

### ⚡ **Performance Superior**
- **Download Multi-Thread**: Até centenas de conexões simultâneas
- **Otimização Inteligente**: Chunk size adaptável baseado no tamanho do arquivo
- **Merge Turbo**: Algoritmo de mesclagem otimizado para arquivos grandes
- **Gráfico de Velocidade**: Monitoramento em tempo real com métricas avançadas

### 🎯 **Inteligência Artificial**
- **Detecção Automática de Qualidade**: Identifica automaticamente a melhor qualidade disponível para vídeos
- **Otimização de Buffer**: Ajuste dinâmico do tamanho do buffer baseado na conexão
- **Compressão Automática**: Redução inteligente do uso de banda

### 🎨 **Interface Moderna**
- **Tema Dark Minimalista**: Design elegante e profissional
- **Interface Intuitiva**: Navegação simples e eficiente
- **Gráficos Interativos**: Visualização em tempo real da velocidade de download
- **Histórico Completo**: Rastreamento detalhado de todos os downloads

### 🔧 **Recursos Avançados**
- **Checksum SHA-256**: Verificação de integridade dos arquivos
- **Proxy e Autenticação**: Suporte completo a configurações de rede
- **Configurações Granulares**: Controle preciso sobre todos os aspectos
- **Sistema de Atualização**: Atualização automática integrada

## 📋 Requisitos do Sistema

- **Python**: 3.8 ou superior
- **PyQt6**: Para interface gráfica
- **matplotlib**: Para gráficos de velocidade
- **requests**: Para downloads HTTP
- **Sistema Operacional**: Windows

## 🚀 Instalação

### Método 1: Via Pip (Recomendado)
```bash
pip install -r requirements.txt
```

### Método 2: Instalação Manual
```bash
pip install PyQt6 matplotlib requests urllib3
```

### Método 3: Executável (Windows)
1. Baixe o executável mais recente das [Releases](https://github.com/DreamerJP/Downloader/releases)
2. Execute o arquivo `.exe`

## 📖 Como Usar

### Interface Básica
1. **URL**: Cole o link do arquivo para download
2. **Destino**: Escolha onde salvar o arquivo
3. **Threads**: Ajuste o número de conexões (recomendado: 512)
4. **Iniciar**: Clique para começar o download

### Configurações Avançadas
- **Qualidade de Vídeo**: Detecção automática ou manual
- **Chunk Size**: Otimização baseada no tamanho do arquivo
- **Buffer**: Ajuste para diferentes tipos de conexão
- **Proxy**: Configurações de rede avançadas

### Gráfico de Velocidade
- **Monitoramento em Tempo Real**: Velocidade atual e média
- **Métricas Detalhadas**: Pico, ETA, progresso percentual
- **Histórico Visual**: Gráfico completo do download

## 🎮 Recursos Especiais

### Sistema de Atualização
- **Verificação Automática**: Checa atualizações na inicialização
- **Download Seguro**: Processo de atualização protegido
- **Reinicialização Automática**: Aplicação atualizada sem intervenção

### Otimizações de Performance
- **Algoritmo de Merge**: Fusão inteligente de partes baixadas
- **Gerenciamento de Memória**: Uso eficiente de recursos do sistema
- **Fallback Seguro**: Recuperação automática de falhas

## 🛠️ Desenvolvimento

### Estrutura do Projeto
```
Downloader/
├── Downloader.py          # Arquivo principal
├── requirements.txt       # Dependências
├── version.json          # Controle de versão
├── README.md             # Documentação
└── ico.ico              # Ícone do aplicativo
```

### Executar em Modo Desenvolvimento
```bash
python Downloader.py
```

### Compilar para Executável
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=ico.ico Downloader.py
```

