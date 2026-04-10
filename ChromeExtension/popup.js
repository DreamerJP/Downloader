// ============================================================
//  popup.js — DreamerJP Advanced Interceptor v2.0
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const mediaListEl    = document.getElementById('mediaList');
  const mediaCountEl   = document.getElementById('mediaCount');
  const statusTextEl   = document.getElementById('statusText');
  const statusDotEl    = document.getElementById('statusDot');
  const clearBtn       = document.getElementById('clearBtn');
  const currentTabOnly = document.getElementById('currentTabOnly');
  const filterPills    = document.getElementById('filterPills');

  let activeFilter = 'all';
  let currentTabId = -1;
  let allMedia     = [];

  // ─── Filtros por tipo ───────────────────────────────────────
  filterPills.querySelectorAll('.pill').forEach(pill => {
    pill.addEventListener('click', () => {
      filterPills.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      activeFilter = pill.dataset.filter;
      renderList();
    });
  });

  // ─── Checkbox Aba Atual ─────────────────────────────────────
  currentTabOnly.addEventListener('change', updateList);

  // ─── Limpar ─────────────────────────────────────────────────
  clearBtn.addEventListener('click', () => {
    const action = currentTabOnly.checked ? 'clearTab' : 'clear';
    chrome.runtime.sendMessage({ action, tabId: currentTabId }, () => updateList());
  });

  // ─── Carrega lista ──────────────────────────────────────────
  function updateList() {
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      currentTabId = tabs[0] ? tabs[0].id : -1;

      chrome.storage.local.get({ capturedMedia: [] }, result => {
        allMedia = result.capturedMedia;

        if (currentTabOnly.checked && currentTabId >= 0) {
          allMedia = allMedia.filter(m => m.tabId === currentTabId);
        }

        renderList();
      });
    });
  }

  // ─── Renderiza cards ────────────────────────────────────────
  function renderList() {
    let media = allMedia;

    if (activeFilter !== 'all') {
      media = media.filter(m => m.type === activeFilter ||
        (activeFilter === 'Áudio' && m.isAudio));
    }

    mediaCountEl.textContent = media.length;
    mediaListEl.innerHTML = '';

    if (media.length === 0) {
      statusTextEl.textContent = 'Aguardando tráfego de mídia...';
      statusDotEl.className = 'status-dot';
      mediaListEl.innerHTML = `
        <div class="no-media">
          <div class="no-media-icon">📡</div>
          <p class="no-media-title">Nenhuma mídia capturada</p>
          <p class="no-media-hint">
            <strong style="color:#f97316">① Recarregue a página (F5)</strong><br>
            ② Dê Play no vídeo novamente.<br>
            <span style="color:#6b7280; font-size:0.8em">A interceptação só registra tráfego após a extensão estar ativa.</span>
          </p>
        </div>`;
      return;
    }

    statusTextEl.textContent = `Interceptação Ativa`;
    statusDotEl.className = 'status-dot active';

    media.forEach((item, idx) => {
      const card = buildCard(item, idx);
      mediaListEl.appendChild(card);
    });
  }

  // ─── Constrói um card de mídia ──────────────────────────────
  function buildCard(item, idx) {
    const card = document.createElement('div');
    card.className = 'media-card';
    if (item.isMaster) card.classList.add('is-master');
    if (item.isAudio)  card.classList.add('is-audio');

    const formatClass = {
      'M3U8': 'fmt-m3u8', 'MPD': 'fmt-mpd', 'MP4': 'fmt-mp4',
      'WEBM': 'fmt-webm', 'TS': 'fmt-ts', 'FLV': 'fmt-flv', 'Áudio': 'fmt-audio'
    }[item.type] || 'fmt-generic';

    // Hostname da URL para resumir
    const urlObj = tryParseUrl(item.url);
    const hostname = urlObj ? urlObj.hostname : '';
    const urlPath  = urlObj ? (urlObj.pathname || '') : item.url;
    const filename = urlPath.split('/').filter(Boolean).pop() || urlPath;

    // Tamanho humanizado
    const sizeLabel = item.contentLength ? formatBytes(item.contentLength) : null;

    // Tempo relativo
    const timeLabel = formatRelativeTime(item.timestamp);

    // Resolução
    const resLabel = item.resolution || null;
    const qualLabel = item.quality || null;

    // Headers disponíveis
    const hasReferer = !!(item.headers && item.headers['referer']);
    const hasUserAgent = !!(item.headers && item.headers['user-agent']);
    const hasCookies  = !!(item.headers && item.headers['cookie']);

    card.innerHTML = `
      <div class="card-top">
        <span class="fmt-badge ${formatClass}">${item.type}${item.isMaster ? ' ★' : ''}</span>
        <div class="card-meta-right">
          ${resLabel   ? `<span class="meta-pill res">${resLabel}</span>` : ''}
          ${qualLabel  ? `<span class="meta-pill qual">${qualLabel}</span>` : ''}
          ${sizeLabel  ? `<span class="meta-pill size">${sizeLabel}</span>` : ''}
          <span class="meta-time">${timeLabel}</span>
        </div>
      </div>

      <div class="card-host" title="${item.pageUrl || ''}">${hostname || '—'}</div>

      <div class="card-filename" title="${item.url}">${filename}</div>

      <div class="card-url-row">
        <span class="card-url" title="${item.url}">${item.url}</span>
      </div>

      <div class="card-tab-row" title="${item.pageUrl || ''}">
        <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="3" width="20" height="14" rx="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line>
        </svg>
        <span>${escHtml(item.tabTitle || 'Aba Desconhecida')}</span>
      </div>

      ${(hasReferer || hasUserAgent || hasCookies) ? `
      <div class="card-headers-row">
        <span class="hdr-tag">HDR</span>
        ${hasReferer    ? '<span class="hdr-chip">Referer</span>' : ''}
        ${hasUserAgent  ? '<span class="hdr-chip">User-Agent</span>' : ''}
        ${hasCookies    ? '<span class="hdr-chip">Cookie</span>' : ''}
      </div>` : ''}

      <div class="card-actions">
        <button class="btn-action btn-copy" title="Copiar URL">
          <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          Copiar URL
        </button>
        <button class="btn-action btn-open" title="Abrir URL em nova aba">
          <svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
            <polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line>
          </svg>
          Abrir
        </button>
      </div>
    `;

    // Botão Copiar URL
    card.querySelector('.btn-copy').addEventListener('click', e => {
      navigator.clipboard.writeText(item.url);
      const btn = e.currentTarget;
      btn.classList.add('copied');
      btn.innerHTML = `<svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg> Copiado!`;
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = `<svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> Copiar URL`;
      }, 2000);
    });

    // Botão Abrir em nova aba
    card.querySelector('.btn-open').addEventListener('click', () => {
      chrome.tabs.create({ url: item.url });
    });

    return card;
  }

  // ─── Utilitários ────────────────────────────────────────────
  function tryParseUrl(url) {
    try { return new URL(url); } catch { return null; }
  }

  function escHtml(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function formatBytes(bytes) {
    if (bytes < 1024)        return bytes + ' B';
    if (bytes < 1048576)     return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1073741824)  return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1073741824).toFixed(2) + ' GB';
  }

  function formatRelativeTime(ts) {
    const diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 5)   return 'agora';
    if (diff < 60)  return diff + 's atrás';
    if (diff < 3600) return Math.floor(diff / 60) + 'min atrás';
    return new Date(ts).toLocaleTimeString();
  }

  // ─── Inicialização e listeners ──────────────────────────────
  updateList();

  chrome.storage.onChanged.addListener((changes, ns) => {
    if (ns === 'local' && changes.capturedMedia) updateList();
  });
});
