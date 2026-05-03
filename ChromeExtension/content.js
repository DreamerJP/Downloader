/**
 * content.js — Downloader
 * Isolated world — bridge entre injected.js (MAIN) e background.js.
 */

// ── Bridge: recebe do injected.js ──────────────────────────────
window.addEventListener('message', (event) => {
  if (!event.data || !event.data[typeof DJP_KEY !== 'undefined' ? DJP_KEY : '__djp4']) return;
  const { url, type, label, isMSE } = event.data;
  if (!url) return;

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
  // Elementos de vídeo e áudio
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

  // iframes de players conhecidos
  document.querySelectorAll('iframe').forEach(f => {
    try {
      if (f.src && /player|embed|video|stream|watch/i.test(f.src) && f.src.startsWith('http')) {
        reportDOM(f.src, 'text/html', 'iframe:' + document.title);
      }
    } catch (_) {}
  });

  // Links diretos para vídeo no DOM
  document.querySelectorAll('a[href]').forEach(a => {
    try {
      const href = a.href;
      if (href && /\.(mp4|webm|mkv|flv|mov|m3u8|mpd)([?#]|$)/i.test(href)) {
        reportDOM(href, 'video/link', document.title);
      }
    } catch (_) {}
  });
}

scanDOM();

const observer = new MutationObserver(() => scanDOM());
const observeBody = () => {
  if (document.body) observer.observe(document.body, { childList: true, subtree: true });
};
if (document.body) observeBody();
else document.addEventListener('DOMContentLoaded', observeBody);
