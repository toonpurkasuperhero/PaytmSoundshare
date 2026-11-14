// Money is integer paise everywhere. Format as ₹ with Indian digit grouping.
function groupIndian(intStr) {
  if (intStr.length <= 3) return intStr;
  const last3 = intStr.slice(-3);
  let rest = intStr.slice(0, -3);
  const parts = [];
  while (rest.length > 2) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  if (rest) parts.unshift(rest);
  return parts.join(',') + ',' + last3;
}

/** 650000 -> "₹6,500.00"; 12345678 -> "₹1,23,456.78" */
export function inr(paise, { decimals = 2, sign = false } = {}) {
  if (paise === null || paise === undefined || paise === '' || Number.isNaN(Number(paise))) return '—';
  const n = Math.round(Number(paise));
  const abs = Math.abs(n);
  let rupees = Math.floor(abs / 100);
  const frac = abs % 100;
  let out;
  if (decimals === 0) {
    if (frac >= 50) rupees += 1;
    out = '₹' + groupIndian(String(rupees));
  } else {
    out = '₹' + groupIndian(String(rupees)) + '.' + String(frac).padStart(2, '0');
  }
  if (n < 0) return '−' + out;
  if (sign && n > 0) return '+' + out;
  return out;
}

/** "4,700.50" / "4700.5" / "₹4,700" -> 470050 */
export function toPaise(rupees) {
  if (rupees === '' || rupees === null || rupees === undefined) return 0;
  const n = parseFloat(String(rupees).replace(/[₹,\s]/g, ''));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

/** 470000 -> "4700" (for editable inputs) */
export function toRupeeInput(paise) {
  if (paise === null || paise === undefined || paise === '') return '';
  const v = Number(paise) / 100;
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

export function pct(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return `${Number(v).toFixed(digits)}%`;
}

export function num(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Math.round(Number(v));
  return (n < 0 ? '−' : '') + groupIndian(String(Math.abs(n)));
}

function toDate(ts) {
  return new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
}

export function time(ts) {
  if (!ts) return '—';
  const d = toDate(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function ago(ts, now = Date.now()) {
  if (!ts) return 'never';
  const d = toDate(ts);
  const s = Math.round((now - d.getTime()) / 1000);
  if (Number.isNaN(s)) return String(ts);
  if (s < 5) return 'just now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return d.toLocaleDateString('en-IN');
}

/** Seconds until ts (ISO string or epoch seconds); null if unknown. */
export function secondsUntil(ts, now = Date.now()) {
  if (!ts) return null;
  const d = toDate(ts);
  if (Number.isNaN(d.getTime())) return null;
  return Math.round((d.getTime() - now) / 1000);
}

export const RAILS = ['UPI_BANK', 'UPI_RUPAY_CC', 'UPI_PPI', 'DEBIT_CARD', 'CREDIT_CARD', 'NET_BANKING', 'UNKNOWN'];

export const RAIL_LABELS = {
  UPI_BANK: 'UPI · bank account',
  UPI_RUPAY_CC: 'UPI · RuPay credit card',
  UPI_PPI: 'UPI · wallet (PPI)',
  DEBIT_CARD: 'Debit card',
  CREDIT_CARD: 'Credit card',
  NET_BANKING: 'Net banking',
  UNKNOWN: 'Unknown rail',
};
export const railLabel = (r) => (r ? RAIL_LABELS[r] || r : '—');

/** Sentinel reasons may be strings or objects; render them as text. */
export function reasonText(r) {
  if (r === null || r === undefined) return '';
  if (typeof r === 'string') return r;
  if (typeof r === 'object') {
    const head = r.rule || r.code || r.type || '';
    const body = r.detail || r.message || r.msg || r.reason || '';
    if (head && body) return `${head}: ${body}`;
    if (body || head) return body || head;
    return JSON.stringify(r);
  }
  return String(r);
}

/** "+91 98765 43210" -> "9876543210" */
export function normalizePhone(v) {
  let s = String(v || '').replace(/[\s\-()]/g, '');
  if (s.startsWith('+91')) s = s.slice(3);
  else if (s.length === 12 && s.startsWith('91')) s = s.slice(2);
  return s;
}

export const PHONE_RE = /^[6-9]\d{9}$/;
export const GSTIN_RE = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
export const VPA_RE = /^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$/;

/** HSN codes are goods; SAC codes (chapter 99) are services. */
export function supplyOf(item) {
  if (item?.supply_type) return item.supply_type;
  return /^99/.test(String(item?.hsn_sac || '').trim()) ? 'services' : 'goods';
}

export function codeLabel(item) {
  if (!item?.hsn_sac) return null;
  return `${supplyOf(item) === 'services' ? 'SAC' : 'HSN'} ${item.hsn_sac}`;
}

export function titleCase(s) {
  return String(s || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ms(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return `${Math.round(Number(v))} ms`;
}

// The 11 languages Sarvam voices support (backend: app/languages.py, also served at /api/config).
export const LANGS = [
  { value: 'en', label: 'English', bcp47: 'en-IN' },
  { value: 'hi', label: 'Hindi (हिन्दी)', bcp47: 'hi-IN' },
  { value: 'bn', label: 'Bengali (বাংলা)', bcp47: 'bn-IN' },
  { value: 'ta', label: 'Tamil (தமிழ்)', bcp47: 'ta-IN' },
  { value: 'te', label: 'Telugu (తెలుగు)', bcp47: 'te-IN' },
  { value: 'kn', label: 'Kannada (ಕನ್ನಡ)', bcp47: 'kn-IN' },
  { value: 'ml', label: 'Malayalam (മലയാളം)', bcp47: 'ml-IN' },
  { value: 'mr', label: 'Marathi (मराठी)', bcp47: 'mr-IN' },
  { value: 'gu', label: 'Gujarati (ગુજરાતી)', bcp47: 'gu-IN' },
  { value: 'pa', label: 'Punjabi (ਪੰਜਾਬੀ)', bcp47: 'pa-IN' },
  { value: 'od', label: 'Odia (ଓଡ଼ିଆ)', bcp47: 'or-IN' },
];
export const langLabel = (v) => LANGS.find((l) => l.value === v)?.label || v || '—';
