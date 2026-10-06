// Anonymous per-browser identity: generated once, kept in localStorage, and sent
// as X-Client-Id on every API call so history/results are scoped to this user.
const STORAGE_KEY = 'priceextractor.clientId';
const VALID_ID = /^[A-Za-z0-9_-]{16,64}$/;

let memoryId = null;

function generateId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  const bytes = window.crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function getClientId() {
  try {
    let id = window.localStorage.getItem(STORAGE_KEY);
    if (!id || !VALID_ID.test(id)) {
      id = generateId();
      window.localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    // localStorage blocked (e.g. strict privacy mode): fall back to a per-tab id.
    if (!memoryId) memoryId = generateId();
    return memoryId;
  }
}

// Only http(s) links from model/web output are ever rendered as clickable hrefs
// (blocks javascript:, data:, etc.). Returns null for anything else.
export function safeHref(url) {
  if (typeof url !== 'string') return null;
  try {
    const parsed = new URL(url.trim());
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}

export function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers);
  headers.set('X-Client-Id', getClientId());
  return fetch(url, { ...options, headers });
}

// Downloads go through fetch (not window.open) so the X-Client-Id header is sent.
export async function apiDownload(url, fallbackName) {
  const res = await apiFetch(url);
  if (!res.ok) throw new Error('Download failed.');
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const blobUrl = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = match ? match[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}
