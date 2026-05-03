// ============================================================
//  popup.js — Downloader
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  // Exibe versão
  if (typeof EXT_VERSION !== 'undefined') {
    const vTag = document.getElementById('versionTag');
    if (vTag) vTag.textContent = `v${EXT_VERSION}`;
  }
  const listEl    = document.getElementById('mediaList');
  const countEl   = document.getElementById('mediaCount');
  const statusTxt = document.getElementById('statusText');
  const statusDot = document.getElementById('statusDot');
  const clearBtn  = document.getElementById('clearBtn');
  const tabToggle = document.getElementById('currentTabOnly');
  const pills     = document.getElementById('filterPills');

  let activeFilter = 'all';
  let currentTabId = -1;
  let allMedia     = [];

  // ── Filtros ────────────────────────────────────────────────
  pills.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      pills.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeFilter = chip.dataset.filter;
      renderList();
    });
  });

  tabToggle.addEventListener('change', updateList);

  clearBtn.addEventListener('click', () => {
    const action = tabToggle.checked ? 'clearTab' : 'clear';
    chrome.runtime.sendMessage({ action, tabId: currentTabId }, () => updateList());
  });

  // ── Carrega dados ──────────────────────────────────────────
  function updateList() {
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      currentTabId = tabs[0] ? tabs[0].id : -1;
      chrome.storage.local.get({ capturedMedia: [] }, result => {
        allMedia = result.capturedMedia;
        if (tabToggle.checked && currentTabId >= 0) {
          allMedia = allMedia.filter(m => m.tabId === currentTabId);
        }
        renderList();
      });
    });
  }

  // ── Agrupa variantes ───────────────────────────────────────
  function groupMedia(items) {
    const groups = new Map();

    for (const item of items) {
      const gk = item.groupKey || item.key;
      if (!groups.has(gk)) {
        groups.set(gk, {
          groupKey: gk,
          primaryFormat: item.format,
          tabTitle: item.tabTitle,
          pageUrl: item.pageUrl,
          isLive: item.isLive,
          timestamp: item.timestamp,
          variants: [],
        });
      }
      groups.get(gk).variants.push(item);
    }

    // Ordena variantes dentro de cada grupo: master/melhor qualidade primeiro
    for (const g of groups.values()) {
      g.variants.sort((a, b) => {
        if (a.isMaster && !b.isMaster) return -1;
        if (!a.isMaster && b.isMaster) return 1;
        const ha = a.height || 0, hb = b.height || 0;
        if (ha !== hb) return hb - ha;
        const ba = a.bitrate || 0, bb = b.bitrate || 0;
        return bb - ba;
      });
      // Formato primário = o da primeira variante (melhor qualidade)
      g.primaryFormat = g.variants[0].format;
      g.isLive = g.variants.some(v => v.isLive);
    }

    return Array.from(groups.values());
  }

  // ── Renderiza lista ────────────────────────────────────────
  function renderList() {
    let media = allMedia;

    if (activeFilter !== 'all') {
      media = media.filter(m => {
        if (activeFilter === 'Áudio') return m.isAudio;
        return m.format === activeFilter;
      });
    }

    const groups = groupMedia(media);

    countEl.textContent = groups.length;
    listEl.innerHTML = '';

    if (groups.length === 0) {
      statusTxt.textContent = 'Aguardando tráfego...';
      statusDot.className = 'dot';
      listEl.appendChild(buildEmpty());
      return;
    }

    statusTxt.textContent = 'Interceptação ativa';
    statusDot.className = 'dot active';

    groups.forEach(g => listEl.appendChild(buildCard(g)));
  }

  // ── Constrói card de grupo ─────────────────────────────────
  function buildCard(group) {
    const card = document.createElement('div');
    card.className = 'video-card';

    const primary  = group.variants[0];
    const urlObj   = tryParseUrl(primary.url);
    const hostname = urlObj ? urlObj.hostname.replace(/^www\./, '') : '—';
    const filename = getFilename(primary.url);
    const fmtClass = 'fmt-' + (group.primaryFormat || 'Midia').replace(/[^a-zA-Z]/g, '');

    // ── Head ──
    const head = document.createElement('div');
    head.className = 'card-head';
    head.innerHTML = `
      <span class="fmt-tag ${fmtClass}">${esc(group.primaryFormat)}</span>
      <div class="card-title">
        <div class="card-filename" title="${esc(primary.url)}">${esc(filename)}</div>
        <div class="card-host">${esc(hostname)}</div>
      </div>
      ${group.isLive ? '<span class="live-badge">AO VIVO</span>' : ''}
    `;
    card.appendChild(head);

    // ── Dropdown de variantes (se houver mais de uma) ──
    if (group.variants.length > 1) {
      const varRow = document.createElement('div');
      varRow.className = 'variant-row';

      const sel = document.createElement('select');
      sel.className = 'variant-select';

      group.variants.forEach((v, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = buildVariantLabel(v);
        sel.appendChild(opt);
      });

      varRow.appendChild(sel);
      card.appendChild(varRow);

      // Atualiza URL exibida e botões ao trocar variante
      sel.addEventListener('change', () => {
        const selected = group.variants[sel.value];
        updateCardUrl(card, selected);
      });
    }

    // ── URL display ──
    const urlRow = document.createElement('div');
    urlRow.className = 'card-url-row';
    urlRow.innerHTML = `<div class="card-url">${esc(primary.url)}</div>`;
    card.appendChild(urlRow);

    // ── Ações ──
    const actions = document.createElement('div');
    actions.className = 'card-actions';
    actions.innerHTML = `
      <button class="btn-act btn-copy">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
        Copiar URL
      </button>
      <button class="btn-act btn-open">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
          <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
        </svg>
        Abrir
      </button>
    `;
    card.appendChild(actions);

    // ── Eventos dos botões ──
    const copyBtn = actions.querySelector('.btn-copy');
    copyBtn.addEventListener('click', () => {
      const url = getCurrentUrl(card, group);
      navigator.clipboard.writeText(url).then(() => {
        copyBtn.classList.add('copied');
        copyBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          Copiado!
        `;
        setTimeout(() => {
          copyBtn.classList.remove('copied');
          copyBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2"/>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
            Copiar URL
          `;
        }, 2000);
      });
    });

    actions.querySelector('.btn-open').addEventListener('click', () => {
      const url = getCurrentUrl(card, group);
      chrome.tabs.create({ url });
    });

    if (primary.isMaster) card.classList.add('is-master');

    return card;
  }

  // ── Helpers ────────────────────────────────────────────────
  function getCurrentUrl(card, group) {
    const sel = card.querySelector('.variant-select');
    if (sel) return group.variants[parseInt(sel.value)].url;
    return group.variants[0].url;
  }

  function updateCardUrl(card, variant) {
    const urlEl = card.querySelector('.card-url');
    if (urlEl) urlEl.textContent = variant.url;
  }

  function buildVariantLabel(v) {
    const parts = [];
    if (v.resolution) parts.push(v.resolution);
    else if (v.height) parts.push(v.height + 'p');
    if (v.bitrate)  parts.push(v.bitrate + ' kbps');
    parts.push(v.format || 'Mídia');
    if (v.isMaster) parts.push('★ master');
    if (v.isAudio)  parts.push('Áudio');
    if (v.contentLength) parts.push(formatBytes(v.contentLength));
    return parts.join('  ·  ');
  }

  function getFilename(url) {
    try {
      const obj = new URL(url);
      const parts = obj.pathname.split('/').filter(Boolean);
      const last = parts[parts.length - 1] || '';
      if (last && last.includes('.')) return decodeURIComponent(last);
      // Fallback: host + path resumido
      return obj.hostname + (parts.length ? '/' + parts.slice(-2).join('/') : '');
    } catch {
      return url.substring(0, 40);
    }
  }

  function tryParseUrl(url) {
    try { return new URL(url); } catch { return null; }
  }

  function esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatBytes(b) {
    if (b < 1024)       return b + ' B';
    if (b < 1048576)    return (b / 1024).toFixed(1) + ' KB';
    if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
    return (b / 1073741824).toFixed(2) + ' GB';
  }

  function buildEmpty() {
    const el = document.createElement('div');
    el.className = 'empty';
    el.innerHTML = `
      <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/>
        <path d="M9 10l.01 0M15 10l.01 0"/>
        <path d="M9.5 15.5a4 4 0 0 0 5 0"/>
        <path d="M12 3v1M12 20v1M3 12h1M20 12h1"/>
      </svg>
      <div class="empty-title">Nenhuma mídia capturada</div>
      <div class="empty-hint">Recarregue a página e dê play no vídeo. A extensão intercepta o tráfego após ser ativada.</div>
    `;
    return el;
  }

  // ── Init ───────────────────────────────────────────────────
  updateList();

  chrome.storage.onChanged.addListener((changes, ns) => {
    if (ns === 'local' && changes.capturedMedia) updateList();
  });
});
