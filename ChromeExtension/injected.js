/**
 * injected.js — Downloader
 * world: MAIN — roda antes de qualquer script da página.
 */
(function () {
  'use strict';

  // ── Anti-DevTools ───────────────────────────────────────────────
  const _defineProperty = Object.defineProperty;
  try {
    _defineProperty(window, 'outerWidth',  { get: () => window.innerWidth,  configurable: true });
    _defineProperty(window, 'outerHeight', { get: () => window.innerHeight, configurable: true });
  } catch (_) {}

  // Neutraliza verificações frequentes de tamanho de janela
  const _origSetInterval = window.setInterval;
  window.setInterval = new Proxy(_origSetInterval, {
    apply(target, thisArg, args) {
      const [fn, delay, ...rest] = args;
      if (typeof fn === 'function' && typeof delay === 'number' && delay < 600) {
        const wrapped = function () { try { fn(); } catch (_) {} };
        return Reflect.apply(target, thisArg, [wrapped, delay, ...rest]);
      }
      return Reflect.apply(target, thisArg, args);
    },
  });

  // Bloqueia console.clear (usado por alguns players para limpar evidências)
  try {
    const _cc = console.clear.bind(console);
    _defineProperty(console, 'clear', { value: () => {}, writable: true, configurable: true });
  } catch (_) {}

  // ── Filtros ─────────────────────────────────────────────────────
  const MEDIA_EXT_RE = /\.(m3u8|mpd|mp4|webm|flv|ts|m4s|m4v|mkv|mov|aac|mp3|opus|f4v|f4a)([?#]|$)/i;
  const MEDIA_CT_RE  = /(mpegurl|dash\+xml|video\/|audio\/mp4|audio\/aac|audio\/mpeg|audio\/ogg|audio\/opus|x-mpegurl|octet-stream)/i;
  const IGNORE_RE    = /(doubleclick|googlesyndication|google-analytics|facebook\.com\/tr|\/ping\b|\/track\b|\/heartbeat|telemetry|thumbnail|thumb\/|\/poster|\/preview|storyboard|\/ad\/|adserver|pixel\.|beacon\.|analytics\.|\/stats\?|\/metrics\?|pagead|\.gif$|\.png$|\.jpg$|\.jpeg$|\.svg$|\.ico$|\.woff|\.ttf|\.css\b|\.js\b(?!on))/i;
  const SEGMENT_RE   = /[_-](seg|segment|frag|chunk|part)[_-]?\d|\/seg\d|\/frag\d|\d{6,}\.ts$|\d{4,}\.m4s$/i;
  const SEEN         = new Set();

  function isMedia(url, ct) {
    if (!url || url.length < 10) return false;
    if (url.startsWith('blob:') || url.startsWith('data:')) return false;
    if (IGNORE_RE.test(url)) return false;
    const base = url.split('?')[0];
    if (MEDIA_EXT_RE.test(base)) return true;
    if (ct && MEDIA_CT_RE.test(ct) && !ct.includes('octet-stream')) return true;
    if (ct && ct.includes('octet-stream') && MEDIA_EXT_RE.test(base)) return true;
    return false;
  }

  function isSegmentNoise(url) {
    // Ignora segmentos individuais de HLS/DASH que não são master/index
    return SEGMENT_RE.test(url) && !/master|index|playlist|manifest/i.test(url);
  }

  function report(url, type, label, extra) {
    if (!url || url.startsWith('blob:') || url.startsWith('data:')) return;
    const key = url.split('?')[0].split('#')[0];
    if (SEEN.has(key)) return;
    SEEN.add(key);
    const msg = {
      url,
      type: type || '',
      label: label || document.title || location.hostname,
      ...(extra || {}),
    };
    if (typeof DJP_KEY !== 'undefined') msg[DJP_KEY] = true;
    else msg.__djp4 = true;

    window.postMessage(msg, '*');
  }

  // ── fetch Proxy ─────────────────────────────────────────────────
  window.fetch = new Proxy(window.fetch, {
    apply(target, thisArg, args) {
      const req = args[0];
      const url = typeof req === 'string' ? req
                : (req instanceof Request) ? req.url
                : (req && req.url) ? req.url : '';
      const promise = Reflect.apply(target, thisArg, args);
      if (url) {
        promise.then(resp => {
          try {
            const ct = resp.headers.get('content-type') || '';
            if (isMedia(url, ct) && !isSegmentNoise(url)) report(url, ct);
          } catch (_) {}
        }).catch(() => {});
      }
      return promise;
    },
  });

  // ── XMLHttpRequest Proxy ─────────────────────────────────────────
  XMLHttpRequest.prototype.open = new Proxy(XMLHttpRequest.prototype.open, {
    apply(target, xhr, args) {
      xhr._djpUrl    = String(args[1] || '');
      xhr._djpMethod = String(args[0] || 'GET').toUpperCase();
      return Reflect.apply(target, xhr, args);
    },
  });

  XMLHttpRequest.prototype.send = new Proxy(XMLHttpRequest.prototype.send, {
    apply(target, xhr, args) {
      const url = xhr._djpUrl || '';
      if (url && isMedia(url, '') && !isSegmentNoise(url)) {
        xhr.addEventListener('readystatechange', function () {
          if (this.readyState === 4) {
            try {
              const ct = this.getResponseHeader('content-type') || '';
              if (isMedia(url, ct) && !isSegmentNoise(url)) report(url, ct);
            } catch (_) {}
          }
        }, { once: true });
      }
      return Reflect.apply(target, xhr, args);
    },
  });

  // ── HTMLMediaElement.src setter ──────────────────────────────────
  const _srcDesc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
  if (_srcDesc && _srcDesc.set) {
    _defineProperty(HTMLMediaElement.prototype, 'src', {
      get: _srcDesc.get,
      set: new Proxy(_srcDesc.set, {
        apply(target, el, [val]) {
          if (typeof val === 'string' && val && !val.startsWith('blob:') && !val.startsWith('data:')) {
            if (isMedia(val, '') && !isSegmentNoise(val)) report(val, 'video/dom-src');
          }
          return Reflect.apply(target, el, [val]);
        },
      }),
      configurable: true,
    });
  }

  // ── HTMLMediaElement.currentSrc observer ────────────────────────
  // Players modernos como Shaka, HLS.js atribuem currentSrc via objeto interno
  const _currentSrcDesc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'currentSrc');
  // currentSrc é read-only, mas podemos monitorar via polling mínimo no scanDOM

  // ── setAttribute proxy para <video src="..."> dinâmico ──────────
  Element.prototype.setAttribute = new Proxy(Element.prototype.setAttribute, {
    apply(target, el, args) {
      const [attr, val] = args;
      if ((attr === 'src' || attr === 'data-src') && el instanceof HTMLMediaElement) {
        if (typeof val === 'string' && val && !val.startsWith('blob:') && isMedia(val, '') && !isSegmentNoise(val)) {
          report(val, 'video/attr-src');
        }
      }
      return Reflect.apply(target, el, args);
    },
  });

  // ── MediaSource (MSE) ────────────────────────────────────────────
  if (window.MediaSource) {
    // Captura o mimeType via addSourceBuffer
    MediaSource.prototype.addSourceBuffer = new Proxy(MediaSource.prototype.addSourceBuffer, {
      apply(target, ms, args) {
        const mimeType = args[0] || '';
        if (MEDIA_CT_RE.test(mimeType)) {
          const msg = {
            url: location.href,
            type: mimeType,
            label: document.title || location.hostname,
            isMSE: true,
          };
          if (typeof DJP_KEY !== 'undefined') msg[DJP_KEY] = true;
          else msg.__djp4 = true;

          window.postMessage(msg, '*');
        }
        return Reflect.apply(target, ms, args);
      },
    });
  }

  // ── WebSocket intercept (para streams via WS) ────────────────────
  const _OrigWS = window.WebSocket;
  if (_OrigWS) {
    window.WebSocket = new Proxy(_OrigWS, {
      construct(target, args) {
        const url = args[0] || '';
        const ws = Reflect.construct(target, args);
        // Reporta apenas WS de media (wss:// de stream servers)
        if (/wss?:\/\/.*(stream|media|video|live|cdn|player)/i.test(url)) {
          const msg = {
            url: url,
            type: 'websocket/stream',
            label: document.title || location.hostname,
          };
          if (typeof DJP_KEY !== 'undefined') msg[DJP_KEY] = true;
          else msg.__djp4 = true;

          window.postMessage(msg, '*');
        }
        return ws;
      },
    });
  }

  // ── DOM scan periódico ───────────────────────────────────────────
  function scanDOM() {
    document.querySelectorAll('video, audio').forEach(el => {
      [el.src, el.currentSrc].forEach(s => {
        if (s && !s.startsWith('blob:') && !s.startsWith('data:') && isMedia(s, '') && !isSegmentNoise(s)) {
          report(s, 'video/dom');
        }
      });
      el.querySelectorAll('source').forEach(src => {
        if (src.src && !src.src.startsWith('blob:') && isMedia(src.src, src.type || '') && !isSegmentNoise(src.src)) {
          report(src.src, src.type || 'video/dom');
        }
      });
    });

    // Captura data-src (lazy loaders)
    document.querySelectorAll('[data-src],[data-video-src],[data-stream-url]').forEach(el => {
      const s = el.dataset.src || el.dataset.videoSrc || el.dataset.streamUrl;
      if (s && isMedia(s, '') && !isSegmentNoise(s)) report(s, 'video/data-attr');
    });
  }

  if (document.readyState !== 'loading') scanDOM();
  else document.addEventListener('DOMContentLoaded', scanDOM);
  setInterval(scanDOM, 3500);
})();
