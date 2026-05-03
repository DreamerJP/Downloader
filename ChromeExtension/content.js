/**
 * content.js — Downloader
 * Isolated world — bridge entre injected.js (MAIN) e background.js.
 */
(() => {
  'use strict';

  const KEY = (typeof DJP_KEY !== 'undefined') ? DJP_KEY : '__djp4';

  // Filtros locais de segmento (espelham background.js)
  const SEGMENT_EXT_RE  = /\.(?:ts|m4s|cmft|cmfa|cmfv|3gp)(?:[?#]|$)/i;
  const SEGMENT_NAME_RE = /\/(?:seg|seq|segment|chunk|frag|fragment|part|piece|init)[\w-]*\.(?:mp4|m4s|m4a|m4v|ts|aac|cmf[atv])(?:[?#]|$)/i;
  const SEGMENT_NUM_RE  = /[_\-\/]\d{2,}\.(?:ts|m4s|aac|m4a|cmf[atv])(?:[?#]|$)/i;

  const isSegmentNoise = (url) =>
    SEGMENT_EXT_RE.test(url) || SEGMENT_NAME_RE.test(url) || SEGMENT_NUM_RE.test(url);

  // ── Bridge: recebe do injected.js ───────────────────────────────
  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data || !data[KEY]) return;
    const { url, type, label, isMSE } = data;
    if (!url) return;
    if (isSegmentNoise(url)) return;

    try {
      chrome.runtime.sendMessage({
        action: 'domVideo',
        url,
        contentType: type || 'video/intercepted',
        label: label || document.title || location.hostname,
        isMediaSource: isMSE || false,
      });
    } catch (_) {}
  });

  // ── DOM scan de fallback ────────────────────────────────────────
  const REPORTED = new Set();

  function reportDOM(url, contentType, label) {
    if (!url || url.startsWith('blob:') || url.startsWith('data:')) return;
    if (isSegmentNoise(url)) return;
    if (REPORTED.has(url)) return;
    REPORTED.add(url);
    try {
      chrome.runtime.sendMessage({
        action: 'domVideo',
        url,
        contentType: contentType || 'video/dom',
        label: label || document.title || location.hostname,
      });
    } catch (_) {}
  }

  function scanDOM() {
    document.querySelectorAll('video, audio').forEach(el => {
      [el.src, el.currentSrc].forEach(s => {
        if (s && !s.startsWith('blob:') && !s.startsWith('data:')) {
          reportDOM(s, 'video/dom', document.title);
        }
      });
      el.querySelectorAll('source').forEach(src => {
        if (src.src && !src.src.startsWith('blob:')) {
          reportDOM(src.src, src.type || 'video/dom', document.title);
        }
      });
    });

    // iframes de players
    document.querySelectorAll('iframe').forEach(f => {
      try {
        if (f.src && /player|embed|video|stream|watch/i.test(f.src) && f.src.startsWith('http')) {
          reportDOM(f.src, 'text/html', 'iframe:' + document.title);
        }
      } catch (_) {}
    });

    // Links diretos para mídia
    document.querySelectorAll('a[href]').forEach(a => {
      try {
        const href = a.href;
        if (href && /\.(?:mp4|webm|mkv|flv|mov|m3u8|mpd)(?:[?#]|$)/i.test(href)) {
          reportDOM(href, 'video/link', document.title);
        }
      } catch (_) {}
    });
  }

  // Debounce — agrupa rajadas de mutações em um único scan
  let scanTimer = null;
  function scheduleScan() {
    if (scanTimer) return;
    scanTimer = setTimeout(() => { scanTimer = null; scanDOM(); }, 500);
  }

  scanDOM();

  const observer = new MutationObserver(scheduleScan);
  const observeBody = () => {
    if (document.body) observer.observe(document.body, { childList: true, subtree: true });
  };
  if (document.body) observeBody();
  else document.addEventListener('DOMContentLoaded', observeBody);
})();
