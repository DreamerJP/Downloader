/**
 * injected.js — Downloader Core v3.1
 *
 * Rodado com world: "MAIN" pelo Chrome — injeta ANTES de qualquer
 * script da página, bypassando CSP, sem precisar de <script src>.
 *
 * Usa Proxy em vez de substituição direta:
 *   fetch.toString()      → "function fetch() { [native code] }"   ✓
 *   XHR.open.toString()   → "function open() { [native code] }"    ✓
 *
 * Anti-devtools: override de outerWidth/outerHeight e setInterval
 * para neutralizar as checagens de tamanho comuns.
 */
(function () {
  'use strict';

  // ───────────────────────────────────────────────────────────────
  //  ANTI-DEVTOOLS DETECTION
  //  A maioria dos players usa: outerWidth - innerWidth > 160
  //  ou outerHeight - innerHeight > 200 para detectar DevTools.
  // ───────────────────────────────────────────────────────────────
  try {
    Object.defineProperty(window, 'outerWidth', {
      get: () => window.innerWidth,
      configurable: true,
    });
    Object.defineProperty(window, 'outerHeight', {
      get: () => window.innerHeight,
      configurable: true,
    });
  } catch (_) {}

  // Neutraliza timers que verificam tamanho de janela frequentemente
  // mas preserva timers legítimos do player (throttle generoso)
  const _setInterval = window.setInterval;
  window.setInterval = new Proxy(_setInterval, {
    apply(target, thisArg, args) {
      const [fn, delay, ...rest] = args;
      if (typeof fn === 'function' && typeof delay === 'number' && delay < 800) {
        // Wrappa a função para silenciar erros relacionados a DevTools
        const safeFn = function () {
          try { fn(); } catch (_) {}
        };
        return Reflect.apply(target, thisArg, [safeFn, delay, ...rest]);
      }
      return Reflect.apply(target, thisArg, args);
    },
  });

  // ───────────────────────────────────────────────────────────────
  //  DETECÇÃO DE MÍDIA
  // ───────────────────────────────────────────────────────────────
  const MEDIA_EXT_RE = /\.(m3u8|mpd|mp4|webm|flv|ts|m4s|mkv|mov|aac|mp3|f4v)([\?#]|$)/i;
  const MEDIA_CT_RE  = /(mpegurl|dash\+xml|video\/|audio\/mp4|audio\/aac|audio\/mpeg|x-mpegurl)/i;
  const IGNORE_RE    = /(doubleclick|google-analytics|googlesyndication|facebook\.com\/tr|\/ping\b|\/track\b|\/heartbeat|telemetry|thumbnail|thumb\/|\/poster|\/preview|storyboard|\/ad\/|adserver|pixel\.|beacon\.)/i;
  const SEEN         = new Set();

  function isMedia(url, ct) {
    if (!url) return false;
    if (IGNORE_RE.test(url)) return false;
    if (url.startsWith('blob:') || url.startsWith('data:')) return false;
    return MEDIA_EXT_RE.test(url.split('?')[0]) || MEDIA_CT_RE.test(ct || '');
  }

  function report(url, type, label) {
    if (!url || url.startsWith('blob:') || url.startsWith('data:')) return;
    const key = url.split('?')[0];
    if (SEEN.has(key)) return;
    SEEN.add(key);
    // postMessage para o content.js (isolated world) que tem acesso ao chrome.*
    window.postMessage({ __djp3: true, url, type: type || '', label: label || document.title || '' }, '*');
  }

  // ───────────────────────────────────────────────────────────────
  //  FETCH PROXY  (toString() preservado automaticamente pelo Proxy)
  // ───────────────────────────────────────────────────────────────
  window.fetch = new Proxy(window.fetch, {
    apply(target, thisArg, args) {
      const req  = args[0];
      const url  = typeof req === 'string' ? req : (req && req.url) || '';
      const pr   = Reflect.apply(target, thisArg, args);
      pr.then(resp => {
        try {
          const ct = resp.headers.get('content-type') || '';
          if (isMedia(url, ct)) report(url, ct);
        } catch (_) {}
      }).catch(() => {});
      return pr;
    },
  });

  // ───────────────────────────────────────────────────────────────
  //  XMLHttpRequest PROXY
  // ───────────────────────────────────────────────────────────────
  XMLHttpRequest.prototype.open = new Proxy(XMLHttpRequest.prototype.open, {
    apply(target, xhr, args) {
      xhr._djpUrl = String(args[1] || '');
      return Reflect.apply(target, xhr, args);
    },
  });

  XMLHttpRequest.prototype.send = new Proxy(XMLHttpRequest.prototype.send, {
    apply(target, xhr, args) {
      const url = xhr._djpUrl || '';
      xhr.addEventListener('readystatechange', function () {
        if (this.readyState === 4) {
          try {
            const ct = this.getResponseHeader('content-type') || '';
            if (isMedia(url, ct)) report(url, ct);
          } catch (_) {}
        }
      });
      return Reflect.apply(target, xhr, args);
    },
  });

  // ───────────────────────────────────────────────────────────────
  //  HTMLMediaElement.src PROXY
  //  Captura quando o player faz: videoEl.src = "https://..."
  // ───────────────────────────────────────────────────────────────
  const _srcDescriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
  if (_srcDescriptor && _srcDescriptor.set) {
    Object.defineProperty(HTMLMediaElement.prototype, 'src', {
      get: _srcDescriptor.get,
      set: new Proxy(_srcDescriptor.set, {
        apply(target, el, [val]) {
          if (typeof val === 'string' && val && !val.startsWith('blob:') && !val.startsWith('data:')) {
            if (isMedia(val, '')) report(val, 'video/dom-src', document.title);
          }
          return Reflect.apply(target, el, [val]);
        },
      }),
      configurable: true,
    });
  }

  // ───────────────────────────────────────────────────────────────
  //  MEDIASOURCE PROXY
  //  Detecta quando o player usa MSE (blob: streams).
  //  Registra o mimeType e marca a página como tendo stream ativo.
  // ───────────────────────────────────────────────────────────────
  if (window.MediaSource) {
    MediaSource.prototype.addSourceBuffer = new Proxy(MediaSource.prototype.addSourceBuffer, {
      apply(target, ms, args) {
        const mimeType = args[0] || '';
        if (MEDIA_CT_RE.test(mimeType)) {
          // Reporta a URL da página atual com flag de MSE
          window.postMessage({
            __djp3: true,
            url: window.location.href,
            type: mimeType,
            label: '[MSE] ' + (document.title || ''),
            isMSE: true,
          }, '*');
        }
        return Reflect.apply(target, ms, args);
      },
    });
  }

  // ───────────────────────────────────────────────────────────────
  //  DOM SCAN periódico (fallback para players lentos)
  // ───────────────────────────────────────────────────────────────
  function scanDOM() {
    document.querySelectorAll('video, audio').forEach(el => {
      [el.src, el.currentSrc].forEach(s => {
        if (s && !s.startsWith('blob:') && !s.startsWith('data:')) report(s, 'video/dom');
      });
      el.querySelectorAll('source').forEach(src => {
        if (src.src && !src.src.startsWith('blob:')) report(src.src, src.type || 'video/dom');
      });
    });
  }

  if (document.readyState !== 'loading') scanDOM();
  else document.addEventListener('DOMContentLoaded', scanDOM);
  setInterval(scanDOM, 3000);
})();
