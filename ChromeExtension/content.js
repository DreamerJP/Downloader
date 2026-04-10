/**
 * content.js — DreamerJP Bridge v3.0
 *
 * Roda no mundo isolado (isolated world).
 * Recebe postMessage do injected.js (world: MAIN) e repassa ao background.js.
 * Também faz scan DOM de fallback caso o postMessage não chegue.
 */

// ── Bridge: recebe do injected.js e envia ao background ──────────
window.addEventListener('message', (event) => {
  if (!event.data || !event.data.__djp3) return;
  const { url, type, label, isMSE } = event.data;
  if (!url) return;

  try {
    chrome.runtime.sendMessage({
      action: 'domVideo',
      url,
      contentType: type || 'video/intercepted',
      label: label || document.title || '',
      isMediaSource: isMSE || false,
    });
  } catch (_) {}
});

// ── DOM Scan de fallback ─────────────────────────────────────────
const REPORTED = new Set();

function reportDOM(url, contentType, label) {
  if (!url || url.startsWith('blob:') || url.startsWith('data:')) return;
  if (REPORTED.has(url)) return;
  REPORTED.add(url);
  try {
    chrome.runtime.sendMessage({ action: 'domVideo', url, contentType, label });
  } catch (_) {}
}

function scanDOM() {
  document.querySelectorAll('video, audio').forEach(el => {
    [el.src, el.currentSrc].forEach(s => {
      if (s) reportDOM(s, 'video/dom', el.title || document.title);
    });
    el.querySelectorAll('source').forEach(src => {
      if (src.src) reportDOM(src.src, src.type || 'video/dom', document.title);
    });
  });

  document.querySelectorAll('iframe').forEach(f => {
    try {
      if (f.src && /player|embed|video/i.test(f.src)) {
        reportDOM(f.src, 'text/html', 'iframe player');
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
