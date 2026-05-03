"""
core/http_session.py
Criação de sessão HTTP otimizada e detecção de capacidades do servidor.
Sem dependências de PyQt6.
"""

import socket
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
import requests.adapters
from urllib3.util.retry import Retry

from core.constants import (
    CONNECT_TIMEOUT,
    MAX_CONNECTIONS,
    RETRY_BACKOFF,
    RETRY_LIMIT,
)


# CDN de streaming costuma barrar UA de bot e responde igual ao navegador com Chrome UA.
DEFAULT_STREAMING_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Downloader/2.1"
)


def _host_avoids_byte_range_probe(hostname: Optional[str]) -> bool:
    h = (hostname or "").lower()
    return "googlevideo.com" in h or h.endswith(".googleusercontent.com")


def _google_stream_refer_origin(url: str) -> tuple[str, str]:
    """
    Fallback quando só temos URL e nenhum Referer nos headers:
    vídeos source=blogger exigem contexto Blogger; demais urls googlevideo tendem youtube.com.
    """
    qp = parse_qs(urlparse(url).query)
    source = (qp.get("source") or [""])[0].lower()
    if source == "blogger":
        referer = "https://www.blogger.com/"
        origin = "https://www.blogger.com"
    else:
        referer = "https://www.youtube.com/"
        origin = "https://www.youtube.com"
    return referer, origin


def apply_streaming_compat_headers(session: requests.Session, url: str) -> None:
    """
    Preenche Referer/Origin típicos de player embutido para CDNs Google quando o cliente
    não enviou overrides (JSON do interceptor). Para googlevideo Blogger, evita usar só YouTube.

    Preferência máxima: copiar pelo popup da extensão em JSON (cookies + Referer da aba).
    """
    hostname = urlparse(url).hostname
    if not _host_avoids_byte_range_probe(hostname):
        return
    h = session.headers

    ua = (h.get("User-Agent") or "").lower()

    chrome_profile = [
        ("Accept-Language", "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"),
        ("Sec-CH-UA", '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'),
        ("Sec-CH-UA-Mobile", "?0"),
        ("Sec-CH-UA-Platform", '"Windows"'),
        ("Sec-Fetch-Dest", "video"),
        ("Sec-Fetch-Mode", "no-cors"),
        ("Sec-Fetch-Site", "cross-site"),
        ("Priority", "i"),
    ]
    for name, value in chrome_profile:
        if not h.get(name):
            h[name] = value

    if not ua or "chrom" not in ua:
        h["User-Agent"] = DEFAULT_STREAMING_UA

    ref, ori = _google_stream_refer_origin(url)
    if not h.get("Referer"):
        h["Referer"] = ref
    if not h.get("Origin"):
        rref = h.get("Referer") or ref
        rp = urlparse(rref)
        if rp.scheme and rp.hostname:
            h["Origin"] = f"{rp.scheme}://{rp.hostname}"
        else:
            h["Origin"] = ori


def create_session(
    proxy: Optional[dict] = None,
    auth: Optional[tuple] = None,
    custom_headers: Optional[dict] = None,
) -> requests.Session:
    """
    Cria uma sessão HTTP com pool de conexões, retry automático e buffers TCP otimizados.

    Parâmetros:
        proxy          : dict {'http': url, 'https': url} ou None
        auth           : tupla (usuário, senha) para autenticação HTTP básica, ou None
        custom_headers : headers adicionais/sobrescritos (valores vazios são ignorados)

    Retorna:
        requests.Session configurada e pronta para uso.
    """
    session = requests.Session()

    # Headers padrão — sobrescritos por custom_headers quando fornecidos
    headers = {
        "User-Agent": DEFAULT_STREAMING_UA,
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if custom_headers:
        for key, val in custom_headers.items():
            if val:  # Ignorar headers com valor vazio
                headers[key] = val
    session.headers.update(headers)

    if proxy:
        session.proxies.update(proxy)

    if auth:
        session.auth = auth

    # Retry automático para erros transientes
    retry = Retry(
        total=RETRY_LIMIT,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=RETRY_BACKOFF,
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        raise_on_status=False,
    )

    adapter = requests.adapters.HTTPAdapter(
        max_retries=retry,
        pool_connections=MAX_CONNECTIONS,
        pool_maxsize=MAX_CONNECTIONS,
        pool_block=False,
    )

    # Otimização de buffer TCP — aumenta throughput em redes Gigabit
    try:
        adapter.init_poolmanager(
            connections=MAX_CONNECTIONS,
            maxsize=MAX_CONNECTIONS,
            block=False,
            socket_options=[
                (socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024),
                (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
            ],
        )
    except Exception:
        pass  # Fallback silencioso — funciona sem as otimizações de socket

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def get_server_info(
    session: requests.Session,
    url: str,
    timeout: float = CONNECT_TIMEOUT,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Detecta capacidades do servidor: suporte a range requests e tamanho do arquivo.

    Fluxo:
    1. Tenta HEAD para obter Content-Length, Accept-Ranges e Content-Encoding.
    2. Se informações ausentes, faz GET com Range: bytes=0-0 como fallback.
    3. Resposta 206 confirma suporte a ranges; Content-Range revela tamanho total.

    Parâmetros:
        session : sessão HTTP já configurada
        url     : URL do arquivo
        timeout : timeout de conexão em segundos

    Retorna:
        (accept_ranges, content_length, content_encoding)
        Qualquer campo pode ser None se o servidor não informar.
    """
    accept_ranges: Optional[str] = None
    content_length: Optional[int] = None
    content_encoding: Optional[str] = None

    # --- Passo 1: HEAD ---
    try:
        r = session.head(url, allow_redirects=True, timeout=timeout)
        r.raise_for_status()
        accept_ranges = r.headers.get("Accept-Ranges")
        content_encoding = r.headers.get("Content-Encoding")
        raw_len = r.headers.get("Content-Length")
        if raw_len is not None:
            try:
                content_length = int(raw_len)
            except ValueError:
                content_length = None
    except Exception:
        pass  # Prosseguir para fallback

    # --- Passo 2: GET com range mínimo (fallback) ---
    hostname = urlparse(url).hostname
    # googlevideo não costuma responder 206 a sondagens com Range usando cliente script;
    # o probe pode até retornar 403 enquanto o GET completo (como no browser) aceita.
    if not _host_avoids_byte_range_probe(hostname) and (
        content_length is None or accept_ranges is None
    ):
        try:
            r2 = session.get(
                url,
                headers={"Range": "bytes=0-0"},
                stream=True,
                timeout=timeout,
                allow_redirects=True,
            )
            if r2.status_code == 206:
                accept_ranges = "bytes"
                content_range = r2.headers.get("Content-Range", "")
                # Formato: "bytes 0-0/TOTAL"
                if "/" in content_range:
                    try:
                        content_length = int(content_range.split("/")[-1])
                    except ValueError:
                        pass
            else:
                raw_len = r2.headers.get("Content-Length")
                if raw_len and content_length is None:
                    try:
                        content_length = int(raw_len)
                    except ValueError:
                        pass

            if content_encoding is None:
                content_encoding = r2.headers.get("Content-Encoding")

            r2.close()
        except Exception:
            pass

    return accept_ranges, content_length, content_encoding
