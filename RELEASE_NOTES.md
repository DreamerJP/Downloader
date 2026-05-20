# Release Notes - Downloader v2.2

Esta versão traz melhorias estruturais profundas e correções cirúrgicas de bugs que garantem estabilidade absoluta, velocidade máxima de download e uma experiência visual livre de distrações.

---

## O que há de novo na v2.2

### Fim dos erros "403 Forbidden" em Vídeos (Correção na Detecção de Qualidade)
* **Como era:** Ao tentar descobrir a melhor qualidade de um vídeo (ex: mudar de 360p para 1080p), o programa rodava uma regra de substituição de texto na URL inteira. Se a URL contivesse um token ou chave de segurança com letras como `4k` (por exemplo, `&token=3fa4k9d`), ele corrompia o token criptográfico (`&token=3fa360p9d`), fazendo o servidor bloquear o download com erro 403.
* **A melhoria:** Agora, a alteração de qualidade é isolada **estritamente na pasta do arquivo (path)** da URL, mantendo os parâmetros de segurança e chaves de autenticação originais 100% intocados. Além disso, a busca por qualidade agora usa limites de palavras estritos, evitando colisões indesejadas.

---

### Downloads Paralelos Habilitados para YouTube e Blogger (Swarm Ativo)
* **Como era:** Por segurança preventiva antiga, o programa pulava testes de download em servidores do Google Video (`googlevideo.com`). Com isso, ele achava incorretamente que o servidor não aceitava downloads concorrentes e forçava o download em uma única conexão lenta de 1 thread (`single_stream_download`).
* **A melhoria:** O bloqueio foi removido. Agora o programa testa a conexão usando cabeçalhos que simulam perfeitamente o navegador. Caso o servidor tente barrar o teste rápido, adicionamos um sistema de fallback inteligente: "Se for Google Video, assume suporte de range" e ativa o **modo Swarm paralelo com conexões rápidas e simultâneas automaticamente**.

---

### Tempo Restante (ETA) Preciso em Transmissões HLS/M3U8
* **Como era:** Downloads de streaming HLS não têm um tamanho de arquivo declarado de início. Por causa disso, o cálculo de tempo restante ficava exibindo valores incorretos ou em branco.
* **A melhoria:** Implementamos um estimador dinâmico em tempo real. Ele calcula a média de tamanho dos segmentos de vídeo baixados e faz uma projeção matemática altamente precisa do tempo restante de download, sem impactar em nada o processamento ou a velocidade de download.

---

### Integração Confiável com o Chrome no Windows
* **Como era:** Clicar no botão de extensões na interface do programa às vezes travava o programa em background ou falhava silenciosamente se houvesse alguma restrição na API nativa do Windows.
* **A melhoria:** Adicionamos um sistema de fallback robusto via subprocesso secundário (`cmd /c start chrome`). Se o clique direto falhar, o Windows abre o Chrome na aba de extensões instantaneamente e com segurança, sem engasgar a interface do app.

---

### Limpeza de Cookies e Segurança de Dados no Histórico
* **Como era:** Se você colasse um JSON vindo da extensão do Chrome (contendo cookies e cabeçalhos de autenticação) e depois baixasse um link comum, os cookies do primeiro download podiam "vazar" para o segundo link.
* **A melhoria:** Criamos uma redefinição estrita e automática de cabeçalhos no método de escuta de mudança de URL. Assim que uma nova URL comum é digitada ou colada, todos os cookies sensíveis do download anterior são imediatamente destruídos.

---

### Ambiente Limpo de Desenvolvimento (Fim das Pastas __pycache__)
* **Como era:** O interpretador Python gerava automaticamente pastas `__pycache__` e arquivos `.pyc` dentro de todos os diretórios do projeto, poluindo a visualização da barra lateral do editor de código.
* **A melhoria:** Desativamos completamente a geração de bytecode compilado no arquivo inicial (`main.py`) usando a flag `sys.dont_write_bytecode = True`. Além disso, o ambiente virtual local `.venv` foi removido do repositório, permitindo rodar o programa direto do seu Python global.

---

## Detalhes do Commit Técnico
* **Tipo de alteração:** `build` / `refactor` / `bugfix`
* **Arquivos Modificados:**
  * `main.py` — Desativação de escrita de bytecode.
  * `version.json` — Incremento para v2.2 e novo Changelog.
  * `core/quality_detector.py` — Correção cirúrgica de tokens e regex no path de URLs.
  * `core/http_session.py` — Liberação de range probe e fallback no Google Video.
  * `core/speed_calculator.py` — Algoritmo de projeção de tempo HLS.
  * `chrome_ext/installer.py` — Fallback robusto de processo no Windows.
  * `ui/download_tab.py` — Redefinição preventiva de cabeçalhos contra vazamento de cookies.
  * `ui/main_window.py` — Resolução de conflito de nomes de classes (shadowing).
  * `workers/download_worker.py` — Remoção de rotinas órfãs de diretórios.
  * `README.md` — Alinhamento técnico de documentação.
