// ============================================================
//  DreamerJP Advanced Interceptor — background.js  v3.0
// ============================================================

const requestHeadersCache = new Map();

// URLs / hostnames de rastreamento / analytics que devemos ignorar
const IGNORE_PATTERNS = [
  'doubleclick.net', 'google-analytics.com', 'googlesyndication.com',
  'facebook.com/tr', 'pixel.', 'beacon.', 'analytics.', 'telemetry.',
  '/ping?', '/track?', '/heartbeat', '/stats?', '/metrics?',
  'thumbnail', 'thumb/', '/poster', '/preview', 'sprite.', '/storyboard',
  'adserver.', '/ad/', '/ads/', 'pagead'
];

// Padrões de URL que indicam mídia real
const VIDEO_URL_PATTERNS = [
  '.m3u8', '.mpd', '.mp4', '.webm', '.flv', '.mkv', '.avi', '.mov',
  '.ts', '.f4v', '.mp2t',
  '/manifest', '/master', '/playlist', '/stream',
  'videoplayback', 'video_url', 'media.m3u', 'index.m3u'
];

// Content-Types que indicam vídeo/áudio real
const VIDEO_CONTENT_TYPES = [
  'application/vnd.apple.mpegurl',
  'application/x-mpegurl',
  'application/dash+xml',
  'video/',
  'audio/mp4',
  'audio/aac',
  'audio/mpeg',
  // octet-stream só é aceito se a URL bater em padrões de vídeo (checked inline)
];

// TS isolado: só aceita se for longo ou vier de manifesto — filtramos por tamanho de URL mais tarde
const SEGMENT_PATTERNS = ['.ts', '.mp2t', 'video/mp2t'];

// ============================================================
//  Utilitários
// ============================================================

function isIgnored(url) {
  const lower = url.toLowerCase();
  return IGNORE_PATTERNS.some(p => lower.includes(p));
}

function isVideoUrl(url) {
  const lower = url.toLowerCase().split('?')[0]; // ignora query string na checagem de extensão
  return VIDEO_URL_PATTERNS.some(p => lower.includes(p));
}

function isSegmentOnly(url, type) {
  const lower = url.toLowerCase();
  // Segmentos TS individuais são barulho; só guarda se for master/index ou o primeiro
  return SEGMENT_PATTERNS.some(p => lower.includes(p)) &&
         !lower.includes('index') && !lower.includes('master') && !lower.includes('playlist');
}

/** Extrai informações de qualidade / resolução da URL e do tipo */
function extractQualityInfo(url, contentType) {
  const info = { resolution: null, quality: null, format: 'Mídia', isMaster: false, isAudio: false };

  const lower = url.toLowerCase();
  const urlObj = tryParseUrl(url);
  const params = urlObj ? urlObj.searchParams : null;

  // --- Formato ---
  if (lower.includes('.m3u8') || contentType.includes('mpegurl'))  { info.format = 'M3U8'; }
  else if (lower.includes('.mpd') || contentType.includes('dash')) { info.format = 'MPD'; }
  else if (lower.includes('.mp4') || contentType.includes('mp4'))  { info.format = 'MP4'; }
  else if (lower.includes('.webm') || contentType.includes('webm')){ info.format = 'WEBM'; }
  else if (lower.includes('.flv'))                                  { info.format = 'FLV'; }
  else if (lower.includes('.ts') || contentType.includes('mp2t'))  { info.format = 'TS'; }
  else if (contentType.includes('audio/'))                         { info.format = 'Áudio'; info.isAudio = true; }

  // --- Master playlist ---
  if (lower.includes('master') || lower.includes('/playlist') ||
     (info.format === 'M3U8' && !lower.includes('seg') && !lower.includes('index'))) {
    info.isMaster = true;
  }

  // --- Resolução / qualidade via keyword na URL ---
  const resPatterns = [
    { re: /(\d{3,4})[px_-]?(\d{3,4})/i, label: (m) => `${m[1]}x${m[2]}` },
    { re: /(\d{3,4})p/i,                 label: (m) => `${m[1]}p` },
    { re: /_(4k|2k|uhd|fhd|hd|sd|ld|hq|lq|high|low|medium|med)_?/i, label: (m) => m[1].toUpperCase() },
    { re: /\/(4k|2k|uhd|fhd|hd|sd|ld|hq|lq|high|low|medium|med)\//i, label: (m) => m[1].toUpperCase() },
  ];

  for (const p of resPatterns) {
    const m = url.match(p.re);
    if (m) { info.resolution = p.label(m); break; }
  }

  // --- Via query params comuns ---
  if (!info.resolution && params) {
    const qp = ['quality', 'res', 'resolution', 'height', 'h', 'level', 'profile'];
    for (const q of qp) {
      const v = params.get(q);
      if (v) { info.resolution = v; break; }
    }
  }

  // --- Qualidade numérica (bitrate) ---
  const bitrateMatch = url.match(/(\d{3,5})[_-]?kbps/i) || url.match(/bitrate[=_](\d+)/i);
  if (bitrateMatch) info.quality = bitrateMatch[1] + ' kbps';

  return info;
}

function tryParseUrl(url) {
  try { return new URL(url); } catch { return null; }
}

/** Chave de deduplicação: normaliza query string irrelevante */
function dedupeKey(url) {
  const obj = tryParseUrl(url);
  if (!obj) return url;
  // Remove parâmetros que variam por sessão mas não mudam o stream
  ['token', 'expires', 'signature', 'sig', 'auth', 'session', '_', 'ts', 't', 'nonce'].forEach(p => obj.searchParams.delete(p));
  return obj.toString();
}

// ============================================================
//  Interceptação de headers ENVIADOS (request headers)
// ============================================================
chrome.webRequest.onSendHeaders.addListener(
  function (details) {
    if (isIgnored(details.url)) return;

    const url = details.url.toLowerCase();
    let reqHeaders = {};
    if (details.requestHeaders) {
      for (let h of details.requestHeaders) {
        reqHeaders[h.name.toLowerCase()] = h.value;
      }
    }

    if (isVideoUrl(url)) {
      // Segmentos TS individuais ignoramos — barulho
      if (isSegmentOnly(url, '')) {
        requestHeadersCache.set(details.requestId, reqHeaders);
        setTimeout(() => requestHeadersCache.delete(details.requestId), 15000);
        return;
      }
      saveMedia(details.url, 'video/media', reqHeaders, details.tabId, details.initiator || '');
    } else {
      requestHeadersCache.set(details.requestId, reqHeaders);
      setTimeout(() => requestHeadersCache.delete(details.requestId), 15000);
    }
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

// ============================================================
//  Interceptação de headers RECEBIDOS (response headers)
// ============================================================
chrome.webRequest.onHeadersReceived.addListener(
  function (details) {
    if (isIgnored(details.url)) return;

    let contentType = '';
    let contentLength = null;

    if (details.responseHeaders) {
      for (let h of details.responseHeaders) {
        const name = h.name.toLowerCase();
        if (name === 'content-type')   contentType   = h.value.toLowerCase();
        if (name === 'content-length') contentLength = parseInt(h.value, 10);
      }
    }

    let isVideo = VIDEO_CONTENT_TYPES.some(t => contentType.includes(t));

    // Aceita octet-stream se a URL tiver extensão/padrão de vídeo conhecida
    if (!isVideo && contentType.includes('octet-stream') && isVideoUrl(details.url)) {
      isVideo = true;
    }

    if (!isVideo) return;

    // Ignora segmentos TS muito pequenos (< 50 KB — provavelmente thumbnail/preview)
    if (isSegmentOnly(details.url, contentType) && contentLength !== null && contentLength < 51200) return;

    const reqHeaders = requestHeadersCache.get(details.requestId) || {};
    saveMedia(details.url, contentType, reqHeaders, details.tabId, details.initiator || '', contentLength);
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders", "extraHeaders"]
);

// ============================================================
//  Mensagens do content.js (vídeos detectados no DOM)
// ============================================================
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'domVideo') {
    const tabId = sender.tab ? sender.tab.id : -1;
    const initiator = sender.tab ? sender.tab.url : '';
    const label = request.isMediaSource
      ? '[MSE] ' + (request.label || '')
      : (request.label || null);
    saveMedia(request.url, request.contentType || 'video/dom', {}, tabId, initiator, null, label);
    sendResponse({ status: 'ok' });
    return true;
  }

  if (request.action === 'clear') {
    chrome.storage.local.set({ capturedMedia: [] });
    // Limpa badge de todas as abas
    chrome.tabs.query({}, tabs => {
      tabs.forEach(t => {
        try { chrome.action.setBadgeText({ text: '', tabId: t.id }); } catch (e) {}
      });
    });
    sendResponse({ status: 'ok' });
    return true;
  }

  if (request.action === 'clearTab') {
    const tabId = request.tabId;
    chrome.storage.local.get({ capturedMedia: [] }, result => {
      const filtered = result.capturedMedia.filter(m => m.tabId !== tabId);
      chrome.storage.local.set({ capturedMedia: filtered });
      try { chrome.action.setBadgeText({ text: '', tabId: tabId }); } catch (e) {}
    });
    sendResponse({ status: 'ok' });
    return true;
  }
});

// ============================================================
//  Limpa vídeos de uma aba ao navegar para outra URL
// ============================================================
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'loading' && changeInfo.url) {
    chrome.storage.local.get({ capturedMedia: [] }, result => {
      const filtered = result.capturedMedia.filter(m => m.tabId !== tabId);
      chrome.storage.local.set({ capturedMedia: filtered });
      try { chrome.action.setBadgeText({ text: '', tabId: tabId }); } catch (e) {}
    });
  }
});

// ============================================================
//  Salva a mídia detectada
// ============================================================
function saveMedia(url, type, headers, tabId, initiator, contentLength, domLabel) {
  if (!url || url.length < 15) return;
  if (isIgnored(url)) return;

  const key = dedupeKey(url);
  const qualityInfo = extractQualityInfo(url, type || '');

  function processMedia(tabTitle, pageUrl) {
    chrome.storage.local.get({ capturedMedia: [] }, function (result) {
      let media = result.capturedMedia;

      // Deduplicação por chave normalizada
      const existing = media.findIndex(m => m.key === key);
      if (existing !== -1) {
        // Atualiza headers se necessário mas não duplica
        if (Object.keys(headers).length > 0) {
          media[existing].headers = { ...media[existing].headers, ...headers };
          chrome.storage.local.set({ capturedMedia: media });
        }
        return;
      }

      const entry = {
        key,
        url,
        type: qualityInfo.format,
        mime: type,
        resolution: qualityInfo.resolution,
        quality: qualityInfo.quality,
        isMaster: qualityInfo.isMaster,
        isAudio: qualityInfo.isAudio,
        contentLength: contentLength || null,
        headers,
        initiator: initiator || '',
        timestamp: Date.now(),
        tabId,
        tabTitle: tabTitle || 'Desconhecido',
        pageUrl: pageUrl || '',
        domLabel: domLabel || null,
      };

      // Mídias master (M3U8/MPD) vão para o topo; resto na ordem de chegada
      if (qualityInfo.isMaster || qualityInfo.format === 'MP4' || qualityInfo.format === 'WEBM') {
        media.unshift(entry);
      } else {
        media.push(entry);
      }

      if (media.length > 150) media = media.slice(0, 150);
      chrome.storage.local.set({ capturedMedia: media });

      // Badge com contagem da aba atual
      if (tabId >= 0) {
        const tabCount = media.filter(m => m.tabId === tabId).length;
        try {
          chrome.action.setBadgeText({ text: tabCount.toString(), tabId });
          chrome.action.setBadgeBackgroundColor({ color: '#00FF41', tabId });
        } catch (e) {}
      }
    });
  }

  if (tabId < 0) {
    processMedia('Background', '');
  } else {
    chrome.tabs.get(tabId, tab => {
      if (chrome.runtime.lastError) {
        processMedia('Aba Desconhecida', '');
      } else {
        processMedia(tab ? tab.title : 'Aba Desconhecida', tab ? tab.url : '');
      }
    });
  }
}
