// ============================================================
//  Downloader — background.js  v4.1
//  Correções principais:
//  - Filtragem agressiva de segmentos HLS/DASH (seg-N, init-, .ts, .m4s)
//  - Detecção mais conservadora de master playlist
//  - Agrupamento por diretório (variantes do mesmo vídeo se juntam)
//  - Cache anti-duplicidade entre onSendHeaders e onHeadersReceived
// ============================================================
'use strict';

const reqHeadersCache = new Map();
const recentUrls      = new Map();   // url -> ts (anti-flood entre listeners)

// ── Padrões de ruído (publicidade, telemetria, assets estáticos) ─
const IGNORE_RE = new RegExp([
  'doubleclick\\.net', 'google-analytics', 'googlesyndication', 'googletagmanager',
  'facebook\\.com\\/tr', 'connect\\.facebook\\.net',
  '\\bpixel\\.', '\\bbeacon\\.', '\\banalytics\\.', '\\btelemetry\\.', '\\bmetrics\\.',
  '\\/ping\\?', '\\/track\\?', '\\/heartbeat', '\\/stats\\?', '\\/metrics\\?',
  'thumbnail', '\\bthumb\\/', '\\/poster', '\\/preview', 'sprite\\.', '\\/storyboard',
  'adserver\\.', '\\/ads?\\/', 'pagead',
  '\\.(?:gif|png|jpe?g|svg|ico|webp|avif|woff2?|ttf|eot|css)(?:[?#]|$)'
].join('|'), 'i');

// ── Mídia válida ────────────────────────────────────────────────
const VIDEO_EXT_RE = /\.(?:m3u8|mpd|mp4|webm|flv|m4v|mkv|mov|aac|mp3|opus|f4v|f4a)(?:[?#]|$)/i;
const VIDEO_CT_RE  = /^(?:application\/(?:vnd\.apple\.mpegurl|x-mpegurl|dash\+xml)|video\/|audio\/(?:mp4|aac|mpeg|ogg|opus))/i;

// ── Segmentos (sempre filtrar) ─────────────────────────────────
//  1) Extensões que SEMPRE são segmento (chunked media)
const SEGMENT_EXT_RE  = /\.(?:ts|m4s|cmft|cmfa|cmfv|3gp)(?:[?#]|$)/i;
//  2) Nome com prefixo de segmento (seg-N, init-, chunk-, frag-, etc.)
const SEGMENT_NAME_RE = /\/(?:seg|seq|segment|chunk|frag|fragment|part|piece|init)[\w-]*\.(?:mp4|m4s|m4a|m4v|ts|aac|cmf[atv])(?:[?#]|$)/i;
//  3) Numérico (chunk_1234.ts, audio_42.aac) — exclui .mp4 pra não pegar vídeo legítimo
const SEGMENT_NUM_RE  = /[_\-\/]\d{2,}\.(?:ts|m4s|aac|m4a|cmf[atv])(?:[?#]|$)/i;

// ── Master playlist ─────────────────────────────────────────────
const HLS_MASTER_NAME_RE = /\/(?:master|manifest|main|stream|playlist|index)(?:[_-]?\d*)?\.m3u8(?:[?#]|$)/i;
const HLS_VARIANT_RE     = /[_\-\/](?:f\d+|v\d+|a\d+|\d{3,4}p|\d{3,4}k|hd|sd|low|high|med(?:ium)?|fhd|uhd|4k|2k)[_\-\.]/i;

// ── Utilidades ──────────────────────────────────────────────────
const isIgnored      = (url) => IGNORE_RE.test(url);
const isVideoUrl     = (url) => VIDEO_EXT_RE.test(url.split('?')[0]);
const isVideoCT      = (ct)  => VIDEO_CT_RE.test((ct || '').trim());
const isSegmentNoise = (url) =>
  SEGMENT_EXT_RE.test(url) || SEGMENT_NAME_RE.test(url) || SEGMENT_NUM_RE.test(url);
const tryParseUrl    = (url) => { try { return new URL(url); } catch { return null; } };

function isRecentlySeen(url) {
  const now = Date.now();
  const last = recentUrls.get(url);
  if (last && now - last < 8000) return true;
  recentUrls.set(url, now);
  if (recentUrls.size > 500) {
    const cutoff = now - 30000;
    for (const [k, v] of recentUrls) if (v < cutoff) recentUrls.delete(k);
  }
  return false;
}

// ── Extração de qualidade/formato ───────────────────────────────
function extractMediaInfo(url, contentType) {
  const info = {
    format: 'Mídia', resolution: null, height: null, bitrate: null,
    isMaster: false, isAudio: false, isLive: false,
  };

  const lower  = url.toLowerCase();
  const base   = lower.split('?')[0];
  const ct     = (contentType || '').toLowerCase();
  const urlObj = tryParseUrl(url);
  const params = urlObj ? urlObj.searchParams : null;

  // Formato
  if      (base.includes('.m3u8') || ct.includes('mpegurl'))   info.format = 'HLS';
  else if (base.includes('.mpd')  || ct.includes('dash'))      info.format = 'DASH';
  else if (base.includes('.mp4')  || ct.includes('mp4'))       info.format = 'MP4';
  else if (base.includes('.webm') || ct.includes('webm'))      info.format = 'WEBM';
  else if (base.includes('.flv'))                              info.format = 'FLV';
  else if (base.includes('.mkv'))                              info.format = 'MKV';
  else if (ct.includes('audio/') || /\.(?:mp3|aac|opus|m4a)(?:[?#]|$)/.test(base)) {
    info.format = 'Áudio';
    info.isAudio = true;
  }

  // Master / arquivo completo
  if (info.format === 'DASH') {
    info.isMaster = true;
  } else if (info.format === 'HLS') {
    if (HLS_MASTER_NAME_RE.test(lower) && !HLS_VARIANT_RE.test(lower)) info.isMaster = true;
    else if (!HLS_VARIANT_RE.test(lower)) info.isMaster = true;
  } else if (info.format === 'MP4' || info.format === 'WEBM' || info.format === 'MKV') {
    info.isMaster = true;
  }

  if (/\b(?:live|event|stream)\b/i.test(lower)) info.isLive = true;

  // Resolução
  const resPatterns = [
    { re: /(\d{3,4})[xX×_](\d{3,4})/,                fn: m => ({ res: `${m[1]}×${m[2]}`, h: parseInt(m[2]) }) },
    { re: /[_\-\/](\d{3,4})p[_\-\/\.\?]/,            fn: m => ({ res: `${m[1]}p`, h: parseInt(m[1]) }) },
    { re: /[_\-\/](4k|2k|uhd|fhd|hd|sd|ld)[_\-\/]/i, fn: m => ({ res: m[1].toUpperCase(), h: { '4K':2160,'2K':1440,'UHD':2160,'FHD':1080,'HD':720,'SD':480,'LD':360 }[m[1].toUpperCase()] || null }) },
  ];
  for (const p of resPatterns) {
    const m = url.match(p.re);
    if (m) { const r = p.fn(m); info.resolution = r.res; info.height = r.h; break; }
  }

  // Resolução via query
  if (!info.resolution && params) {
    for (const q of ['quality','res','resolution','height','h','level','profile','rendition']) {
      const v = params.get(q);
      if (v) {
        info.resolution = isNaN(v) ? v : v + (parseInt(v) > 10 ? 'p' : '');
        info.height = parseInt(v) || null;
        break;
      }
    }
  }

  // Bitrate
  const bm = url.match(/(\d{3,5})[_-]?kbps/i)
          || url.match(/bitrate[=_\/](\d+)/i)
          || url.match(/[_\-\/](\d{4,5})[_\-\/]/);
  if (bm) info.bitrate = parseInt(bm[1]);

  return info;
}

// ── Chaves de dedupe e agrupamento ──────────────────────────────
const SESSION_PARAMS = ['token','expires','expire','expiry','signature','sig','auth','session',
                        '_','ts','t','nonce','hmac','key','cdn_token','s','e','v'];

function dedupeKey(url) {
  const obj = tryParseUrl(url);
  if (!obj) return url;
  SESSION_PARAMS.forEach(p => obj.searchParams.delete(p));
  return obj.toString();
}

// Agrupa por diretório: todas as variantes do mesmo vídeo caem no mesmo grupo
function videoGroupKey(url, tabId) {
  const obj = tryParseUrl(url);
  if (!obj) return `${tabId}::${url}`;
  const dir = obj.pathname.replace(/\/[^\/]*$/, '/') || '/';
  return `${tabId}::${obj.hostname}::${dir}`;
}

// ── webRequest: request headers ─────────────────────────────────
chrome.webRequest.onSendHeaders.addListener(
  function (details) {
    if (isIgnored(details.url) || isSegmentNoise(details.url)) return;

    const reqHeaders = {};
    if (details.requestHeaders) {
      for (const h of details.requestHeaders) reqHeaders[h.name.toLowerCase()] = h.value;
    }

    if (isVideoUrl(details.url)) {
      saveMedia(details.url, 'video/media', reqHeaders, details.tabId, details.initiator || '');
    } else {
      reqHeadersCache.set(details.requestId, reqHeaders);
      setTimeout(() => reqHeadersCache.delete(details.requestId), 20000);
    }
  },
  { urls: ['<all_urls>'] },
  ['requestHeaders', 'extraHeaders']
);

// ── webRequest: response headers ────────────────────────────────
chrome.webRequest.onHeadersReceived.addListener(
  function (details) {
    if (isIgnored(details.url) || isSegmentNoise(details.url)) return;

    let contentType = '', contentLength = null;
    if (details.responseHeaders) {
      for (const h of details.responseHeaders) {
        const n = h.name.toLowerCase();
        if (n === 'content-type')   contentType   = h.value.toLowerCase();
        if (n === 'content-length') contentLength = parseInt(h.value, 10) || null;
      }
    }

    let isVideo = isVideoCT(contentType);
    if (!isVideo && contentType.includes('octet-stream') && isVideoUrl(details.url)) isVideo = true;
    if (!isVideo) return;

    const reqHeaders = reqHeadersCache.get(details.requestId) || {};
    saveMedia(details.url, contentType, reqHeaders, details.tabId, details.initiator || '', contentLength);
  },
  { urls: ['<all_urls>'] },
  ['responseHeaders', 'extraHeaders']
);

// ── Mensagens do content.js ─────────────────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'domVideo') {
    if (!request.url || isSegmentNoise(request.url)) {
      sendResponse({ status: 'ignored' });
      return true;
    }
    const tabId     = sender.tab ? sender.tab.id : -1;
    const initiator = sender.tab ? sender.tab.url : '';
    saveMedia(request.url, request.contentType || 'video/dom', {}, tabId, initiator, null, request.label);
    sendResponse({ status: 'ok' });
    return true;
  }

  if (request.action === 'clear') {
    chrome.storage.local.set({ capturedMedia: [] });
    chrome.tabs.query({}, tabs => {
      tabs.forEach(t => { try { chrome.action.setBadgeText({ text: '', tabId: t.id }); } catch (_) {} });
    });
    sendResponse({ status: 'ok' });
    return true;
  }

  if (request.action === 'clearTab') {
    const tabId = request.tabId;
    chrome.storage.local.get({ capturedMedia: [] }, result => {
      const filtered = result.capturedMedia.filter(m => m.tabId !== tabId);
      chrome.storage.local.set({ capturedMedia: filtered });
      try { chrome.action.setBadgeText({ text: '', tabId }); } catch (_) {}
    });
    sendResponse({ status: 'ok' });
    return true;
  }
});

// ── Limpa ao navegar ────────────────────────────────────────────
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'loading' && changeInfo.url) {
    chrome.storage.local.get({ capturedMedia: [] }, result => {
      const filtered = result.capturedMedia.filter(m => m.tabId !== tabId);
      chrome.storage.local.set({ capturedMedia: filtered });
      try { chrome.action.setBadgeText({ text: '', tabId }); } catch (_) {}
    });
  }
});

// ── Salva mídia ─────────────────────────────────────────────────
function saveMedia(url, type, headers, tabId, initiator, contentLength, domLabel) {
  if (!url || url.length < 12) return;
  if (isIgnored(url) || isSegmentNoise(url)) return;
  if (isRecentlySeen(url)) return;

  const key      = dedupeKey(url);
  const groupKey = videoGroupKey(url, tabId);
  const info     = extractMediaInfo(url, type || '');

  function processMedia(tabTitle, pageUrl) {
    chrome.storage.local.get({ capturedMedia: [] }, function (result) {
      let media = result.capturedMedia;

      const idx = media.findIndex(m => m.key === key);
      if (idx !== -1) {
        if (Object.keys(headers).length > 0) {
          media[idx].headers = { ...media[idx].headers, ...headers };
          chrome.storage.local.set({ capturedMedia: media });
        }
        return;
      }

      const entry = {
        key, groupKey, url,
        format: info.format, mime: type,
        resolution: info.resolution, height: info.height, bitrate: info.bitrate,
        isMaster: info.isMaster, isAudio: info.isAudio, isLive: info.isLive,
        contentLength: contentLength || null,
        headers, initiator: initiator || '',
        timestamp: Date.now(),
        tabId, tabTitle: tabTitle || 'Desconhecido', pageUrl: pageUrl || '',
        domLabel: domLabel || null,
      };

      if (info.isMaster || info.format === 'MP4' || info.format === 'WEBM') media.unshift(entry);
      else media.push(entry);

      if (media.length > 200) media = media.slice(0, 200);
      chrome.storage.local.set({ capturedMedia: media });

      if (tabId >= 0) {
        const tabEntries   = media.filter(m => m.tabId === tabId);
        const uniqueGroups = new Set(tabEntries.map(m => m.groupKey)).size;
        try {
          chrome.action.setBadgeText({ text: uniqueGroups.toString(), tabId });
          chrome.action.setBadgeBackgroundColor({ color: '#22c55e', tabId });
        } catch (_) {}
      }
    });
  }

  if (tabId < 0) {
    processMedia('Background', '');
  } else {
    chrome.tabs.get(tabId, tab => {
      if (chrome.runtime.lastError) processMedia('Aba Desconhecida', '');
      else processMedia(tab ? tab.title : 'Aba Desconhecida', tab ? tab.url : '');
    });
  }
}
