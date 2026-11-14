// One module for every REST call in docs/API_CONTRACT.md (v2). Money is integer paise.
// In dev, Vite proxies /api, /ws, /media and /sim to the backend, so the base is ''.
// Set VITE_API_BASE (e.g. http://192.168.1.10:8000) to talk to a backend directly.
export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

const TOKEN_KEY = 'zeromdr.token';
let memoryToken = null;

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || memoryToken;
  } catch {
    return memoryToken;
  }
}

export function setToken(token) {
  memoryToken = token || null;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: keep it in memory for this tab */
  }
}

/** Called on any 401 from an authenticated request (session expired or revoked). */
let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn || (() => {});
}

function validationMessage(detail) {
  // FastAPI 422 validation errors: [{loc:[...], msg, type}]
  const first = detail[0];
  if (!first || typeof first !== 'object') return null;
  const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== 'body').join('.') : '';
  const msg = String(first.msg || '').replace(/^Value error, /, '');
  return field ? `${field}: ${msg}` : msg;
}

export class ApiError extends Error {
  constructor(status, body, fallback) {
    const b = body || {};
    let message = null;
    if (typeof b.detail === 'string') message = b.detail;
    else if (Array.isArray(b.detail)) message = validationMessage(b.detail);
    if (!message && typeof b.error === 'string') message = b.error.replace(/_/g, ' ');
    if (!message) message = fallback || defaultMessage(status);
    super(message);
    this.status = status;
    this.body = b;
    this.error = b.error || null;
    this.reasons = Array.isArray(b.reasons) ? b.reasons : null;
    this.validation = Array.isArray(b.detail) ? b.detail : null;
    this.network = status === 0;
  }
}

function defaultMessage(status) {
  if (status === 401) return 'Please log in again.';
  if (status === 403) return "Your account isn't allowed to do that.";
  if (status === 404) return 'Not found.';
  if (status === 409) return 'Conflict: the request is not allowed in the current state.';
  if (status === 413) return 'File is too large.';
  if (status === 429) return 'Too many attempts. Wait a minute and try again.';
  if (status === 502) return 'The AI service failed to answer.';
  if (status >= 500) return `Server error (HTTP ${status}).`;
  return `HTTP ${status}`;
}

/** Make a backend-relative path (e.g. "/media/audio/x.mp3") absolute against API_BASE. */
export function absUrl(path) {
  if (!path) return path;
  if (/^(https?:|data:|blob:)/.test(path)) return path;
  return `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
}

export function wsUrl(path) {
  const base = API_BASE || window.location.origin;
  return base.replace(/^http/, 'ws') + path;
}

export function qrSrc(data, scale = 8) {
  return `${API_BASE}/api/qr.svg?data=${encodeURIComponent(data)}&scale=${scale}`;
}

function qs(params) {
  const p = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return p.length ? '?' + new URLSearchParams(p).toString() : '';
}

async function request(method, path, body, { auth = true, form = false } = {}) {
  const headers = {};
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = body;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, null, 'Backend not reachable');
  }
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    // The Vite dev proxy answers with an empty 5xx when the backend is down.
    if (res.status >= 500 && res.status !== 502 && !text) throw new ApiError(0, null, 'Backend not reachable');
    // FastAPI's HTTPException may wrap our error object inside "detail".
    const err =
      data && data.detail && typeof data.detail === 'object' && !Array.isArray(data.detail)
        ? { ...data.detail, ...(data.error ? { error: data.error } : {}) }
        : data;
    const e = new ApiError(res.status, err, text && !data ? text.slice(0, 200) : undefined);
    if (res.status === 401 && auth && token) onUnauthorized(e);
    throw e;
  }
  return data;
}

const get = (p) => request('GET', p);
const post = (p, b = {}) => request('POST', p, b);
const patch = (p, b) => request('PATCH', p, b);
const del = (p) => request('DELETE', p);
const enc = encodeURIComponent;

export const api = {
  // auth
  login: (phone, password) => request('POST', '/api/auth/login', { phone, password }, { auth: false }),
  registerMerchant: (body) => request('POST', '/api/auth/register/merchant', body, { auth: false }),
  registerAdvertiser: (body) => request('POST', '/api/auth/register/advertiser', body, { auth: false }),
  me: () => get('/api/auth/me'),
  logout: () => post('/api/auth/logout'),

  // public + system
  config: () => request('GET', '/api/config', undefined, { auth: false }),
  systemStatus: () => get('/api/system/status'),

  // merchants + catalog
  merchants: () => get('/api/merchants'),
  merchant: (id) => get(`/api/merchants/${enc(id)}`),
  updateMerchant: (id, body) => patch(`/api/merchants/${enc(id)}`, body),
  catalog: (id) => get(`/api/merchants/${enc(id)}/catalog`),
  addCatalogItem: (id, body) => post(`/api/merchants/${enc(id)}/catalog`, body),
  updateCatalogItem: (id, itemId, body) => patch(`/api/merchants/${enc(id)}/catalog/${enc(itemId)}`, body),
  deleteCatalogItem: (id, itemId) => del(`/api/merchants/${enc(id)}/catalog/${enc(itemId)}`),

  // bills + orders
  parseBillText: (text) => post('/api/bills/parse', { text }),
  parseBillImage: (file) => {
    const fd = new FormData();
    fd.append('image', file);
    return request('POST', '/api/bills/parse', fd, { form: true });
  },
  planBill: (items, factorize) => post('/api/bills/plan', { items, factorize }),
  createOrder: (body) => post('/api/orders', body),
  orders: (params) => get(`/api/orders${qs(params)}`),
  order: (id) => get(`/api/orders/${enc(id)}`),
  cancelOrder: (id) => post(`/api/orders/${enc(id)}/cancel`),
  refreshOrder: (id) => post(`/api/orders/${enc(id)}/refresh`),
  mockPay: (leg_id, rail, payer) => post('/api/mock/pay', { leg_id, rail, ...(payer ? { payer } : {}) }),

  // devices
  devices: () => get('/api/devices'),
  createDevice: (name) => post('/api/devices', { name }),
  rotateDeviceToken: (id) => post(`/api/devices/${enc(id)}/rotate-token`),
  deleteDevice: (id) => del(`/api/devices/${enc(id)}`),

  // advertisers, wallet, campaigns
  advertisers: () => get('/api/advertisers'),
  advertiser: (id) => get(`/api/advertisers/${enc(id)}`),
  updateAdvertiser: (id, body) => patch(`/api/advertisers/${enc(id)}`, body),
  topup: (id, amount_paise) => post(`/api/advertisers/${enc(id)}/topup`, { amount_paise }),
  topupStatus: (id) => get(`/api/topups/${enc(id)}`),
  topups: (id) => get(`/api/advertisers/${enc(id)}/topups`),
  transcribe: (blob, lang) => {
    const fd = new FormData();
    const ext = /ogg/.test(blob.type) ? 'ogg' : /wav/.test(blob.type) ? 'wav' : /mp(3|eg)/.test(blob.type) ? 'mp3' : 'webm';
    fd.append('audio', blob, `speech.${ext}`);
    fd.append('lang', lang);
    return request('POST', '/api/ai/transcribe', fd, { form: true });
  },
  geoSoundboxes: (lat, lng, radius_m) => get(`/api/geo/soundboxes${qs({ lat, lng, radius_m })}`),
  campaigns: () => get('/api/campaigns'),
  campaign: (id) => get(`/api/campaigns/${enc(id)}`),
  createCampaign: (body) => post('/api/campaigns', body),
  updateCampaign: (id, body) => patch(`/api/campaigns/${enc(id)}`, body),
  regenerateCampaign: (id, body = {}) => post(`/api/campaigns/${enc(id)}/regenerate`, body),

  // ledger, sentinel, admin
  balances: () => get('/api/ledger/balances'),
  entries: (params) => get(`/api/ledger/entries${qs(params)}`),
  flows: (order_id) => get(`/api/ledger/flows${qs({ order_id })}`),
  flags: (limit = 50) => get(`/api/sentinel/flags${qs({ limit })}`),
  adminStats: () => get('/api/admin/stats'),
};
