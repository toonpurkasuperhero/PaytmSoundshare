import { useState } from 'react';
import { reasonText } from '../format.js';
import { useConfig } from '../session.jsx';

export function Icon({ name, className = '', fill = false, title }) {
  return (
    <span className={`icon ${fill ? 'icon-fill' : ''} ${className}`} aria-hidden={title ? undefined : 'true'} title={title}>
      {name}
    </span>
  );
}

export function Spinner({ className = '' }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent align-[-2px] ${className}`}
      role="status"
      aria-label="Loading"
    />
  );
}

const STATUS_TONE = {
  created: 'neutral',
  pending: 'neutral',
  awaiting_payment: 'info',
  active: 'info',
  partially_paid: 'warn',
  paid: 'good',
  settled: 'good',
  pending_ack: 'warn',
  failed: 'bad',
  expired: 'bad',
  cancelled: 'muted',
  generating: 'info',
  draft: 'neutral',
  pending_kyc: 'warn',
  verified: 'good',
  rejected: 'bad',
  paused: 'muted',
  exhausted: 'warn',
  allow: 'good',
  flag: 'warn',
  block: 'bad',
  online: 'good',
  offline: 'muted',
  committed: 'good',
  reserved: 'warn',
  released: 'muted',
};

export function Pill({ status, children, tone, dot = false, className = '' }) {
  const t = tone || STATUS_TONE[status] || 'neutral';
  const label = children ?? String(status ?? '—').replace(/_/g, ' ');
  const dotColor = { good: 'bg-emerald-500', info: 'bg-sky-500', warn: 'bg-amber-500', bad: 'bg-rose-500', muted: 'bg-slate-400', neutral: 'bg-paytm-navy' }[t];
  return (
    <span className={`pill pill-${t} ${className}`}>
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${dotColor} ${t === 'info' && status === 'generating' ? 'animate-pulse' : ''}`} />}
      {label}
    </span>
  );
}

export function Card({ title, icon, subtitle, actions, children, className = '', id, accent = false, bodyClass = '' }) {
  return (
    <section id={id} className={`card relative min-w-0 ${accent ? 'overflow-hidden' : ''} ${className}`}>
      {accent && <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-paytm-cyan via-sky-400 to-paytm-navy" />}
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
          <div className="min-w-0">
            {title && (
              <h3 className="card-title flex items-center gap-2">
                {icon && <Icon name={icon} className="text-[20px] text-paytm-cyan-dark" />}
                <span className="min-w-0">{title}</span>
              </h3>
            )}
            {subtitle && <p className="card-sub mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function ErrorNote({ error, title, className = '' }) {
  if (!error) return null;
  const reasons = error.reasons;
  const msg = error.network ? 'The backend is not reachable. Retrying automatically.' : error.message;
  return (
    <div className={`note note-bad ${className}`} role="alert">
      <div className="flex items-start gap-2">
        <Icon name="error" className="mt-px text-[18px] text-rose-600" />
        <div className="min-w-0">
          <strong className="font-semibold">{title || 'Request failed'}</strong>
          <span className="break-words"> {msg}</span>
          {Array.isArray(reasons) && reasons.length > 0 && (
            <ul className="mt-1 list-disc pl-5">
              {reasons.map((r, i) => (
                <li key={i}>{reasonText(r)}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export function Empty({ icon = 'inbox', title, children, action, className = '' }) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-outline bg-surface-subtle px-4 py-8 text-center ${className}`}>
      <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-outline-variant bg-white text-paytm-cyan-dark">
        <Icon name={icon} className="text-[24px]" />
      </span>
      {title && <div className="text-label-lg font-bold text-paytm-navy">{title}</div>}
      {children && <div className="max-w-md text-body-sm text-on-surface-variant">{children}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/**
 * Where an AI-produced value came from: "AI · model", amber "Fallback: reason", or manual/catalog.
 */
export function SourceBadge({ source, model, reason, label, className = '' }) {
  if (!source) return null;
  const prefix = label ? `${label}: ` : '';
  if (source === 'ai') {
    return (
      <span className={`pill border-paytm-cyan/30 bg-paytm-cyan-light text-paytm-navy ${className}`} title={model ? `Produced by ${model}` : 'Produced by AI'}>
        <Icon name="auto_awesome" className="text-[13px] text-paytm-cyan-dark" />
        {prefix}AI{model ? ` · ${model}` : ''}
      </span>
    );
  }
  if (source === 'fallback') {
    return (
      <span className={`pill pill-warn max-w-full ${className}`} title={reason || 'AI call failed; deterministic fallback used'}>
        <Icon name="warning" className="text-[13px]" />
        <span className="truncate">
          {prefix}Fallback{reason ? `: ${reason}` : ''}
        </span>
      </span>
    );
  }
  if (source === 'single') {
    return (
      <span className={`pill pill-neutral ${className}`} title="One QR for the full bill">
        <Icon name="receipt" className="text-[13px]" />
        {prefix}Single invoice
      </span>
    );
  }
  if (source === 'none') return null;
  return (
    <span className={`pill pill-muted ${className}`}>
      {prefix}
      {source === 'catalog' ? 'Catalog' : source === 'manual' ? 'Manual' : source}
    </span>
  );
}

/** Banner shown wherever AI is the primary path but /api/config says it isn't configured. */
export function AiWarning({ className = '', what = 'AI features' }) {
  const { aiConfigured } = useConfig();
  if (aiConfigured !== false) return null;
  return (
    <div className={`note note-warn flex items-start gap-2 ${className}`} role="status">
      <Icon name="warning" className="mt-px text-[18px] text-amber-600" />
      <div>
        <strong className="font-semibold">AI is not configured on this server.</strong> {what} will use the deterministic
        fallback until an administrator sets the Gemini API key.
      </div>
    </div>
  );
}

export function TestModeBadge({ className = '' }) {
  return (
    <span className={`pill pill-warn ${className}`} title="Mock payment provider: no real money moves">
      <Icon name="science" className="text-[13px]" />
      Test mode
    </span>
  );
}

export function Toggle({ checked, onChange, label, hint, disabled }) {
  return (
    <label className={`flex cursor-pointer items-start gap-3 ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input type="checkbox" className="peer sr-only" checked={!!checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
        <span className="h-6 w-10 rounded-full bg-slate-300 transition-colors peer-checked:bg-primary peer-focus-visible:shadow-focus" />
        <span className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-4" />
      </span>
      <span className="min-w-0">
        <span className="block text-label-lg text-paytm-navy">{label}</span>
        {hint && <span className="block text-body-sm text-on-surface-variant">{hint}</span>}
      </span>
    </label>
  );
}

export function Segmented({ value, onChange, options, className = '' }) {
  return (
    <div className={`inline-flex items-center rounded-lg border border-outline bg-surface p-1 ${className}`} role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          className={`rounded-md px-3 py-1 text-label-md transition-colors ${value === o.value ? 'bg-paytm-navy font-bold text-white shadow-sm' : 'text-on-surface-variant hover:text-paytm-navy'}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs({ value, onChange, tabs }) {
  return (
    <div className="tabbar" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} type="button" role="tab" aria-selected={value === t.value} className={`tab ${value === t.value ? 'tab-on' : ''}`} onClick={() => onChange(t.value)}>
          {t.icon && <Icon name={t.icon} className="text-[17px]" />}
          {t.label}
          {t.badge !== undefined && t.badge !== null && (
            <span className={`rounded-full px-1.5 text-[10px] font-bold ${value === t.value ? 'bg-white/20' : 'bg-surface-high'}`}>{t.badge}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Progress({ value, max = 100, tone = 'brand', label, className = '' }) {
  const p = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const fill = {
    brand: 'bg-gradient-to-r from-paytm-cyan to-paytm-navy',
    good: 'bg-success-green',
    warn: 'bg-alert-amber',
    bad: 'bg-error-red',
  }[tone];
  return (
    <div
      className={`h-2.5 w-full overflow-hidden rounded-full border border-slate-200 bg-slate-100 p-0.5 ${className}`}
      role="progressbar"
      aria-valuenow={Math.round(p)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className={`h-full rounded-full transition-all duration-700 ${fill}`} style={{ width: `${p}%` }} />
    </div>
  );
}

export function Field({ label, hint, error, children, className = '' }) {
  return (
    <label className={`block min-w-0 ${className}`}>
      {label && <span className="field-label">{label}</span>}
      {children}
      {error ? <span className="mt-1 block text-body-sm text-error-red">{error}</span> : hint ? <span className="mt-1 block text-body-sm text-on-surface-variant">{hint}</span> : null}
    </label>
  );
}

export function ChipInput({ values, onChange, suggestions = [], placeholder, ariaLabel }) {
  const add = (v) => {
    const s = v.trim().toLowerCase();
    if (s && !values.includes(s)) onChange([...values, s]);
  };
  const rest = suggestions.filter((s) => !values.includes(s));
  return (
    <div>
      <div className="flex min-h-[44px] flex-wrap items-center gap-1.5 rounded-lg border border-input-border bg-white px-2 py-1.5 focus-within:border-primary focus-within:shadow-focus">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full bg-paytm-navy py-0.5 pl-2.5 pr-1 text-label-sm text-white">
            {v}
            <button type="button" className="flex h-4 w-4 items-center justify-center rounded-full hover:bg-white/20" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>
              <Icon name="close" className="text-[12px]" />
            </button>
          </span>
        ))}
        <input
          className="min-w-[120px] flex-1 border-0 bg-transparent p-1 text-body-md focus:outline-none focus:ring-0"
          placeholder={placeholder}
          aria-label={ariaLabel || placeholder}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault();
              add(e.currentTarget.value);
              e.currentTarget.value = '';
            } else if (e.key === 'Backspace' && !e.currentTarget.value && values.length) {
              onChange(values.slice(0, -1));
            }
          }}
          onBlur={(e) => {
            if (e.currentTarget.value) {
              add(e.currentTarget.value);
              e.currentTarget.value = '';
            }
          }}
        />
      </div>
      {rest.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {rest.map((s) => (
            <button type="button" key={s} className="rounded-full border border-outline bg-surface-ice px-2.5 py-0.5 text-label-sm text-paytm-navy hover:border-primary" onClick={() => add(s)}>
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      window.prompt('Copy this value', text);
    }
  };
  return (
    <button type="button" className="btn btn-outline btn-sm" onClick={copy} aria-label={`${label}: ${text}`}>
      <Icon name={done ? 'check' : 'content_copy'} className="text-[15px]" />
      {done ? 'Copied' : label}
    </button>
  );
}

export function Stat({ label, value, sub, tone }) {
  return (
    <div className="min-w-0">
      <div className="text-label-sm text-on-surface-variant">{label}</div>
      <div className={`tnum truncate text-headline-sm font-bold ${tone === 'cyan' ? 'text-paytm-cyan-dark' : 'text-paytm-navy'}`}>{value}</div>
      {sub && <div className="text-body-sm text-on-surface-variant">{sub}</div>}
    </div>
  );
}

export function PageHead({ crumbs = [], title, chips, right }) {
  return (
    <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div className="min-w-0">
        {crumbs.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-label-sm font-bold uppercase tracking-wider text-paytm-navy">
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-2">
                {i > 0 && <span className="font-normal text-slate-400">/</span>}
                <span className={i === crumbs.length - 1 && crumbs.length > 1 ? 'text-paytm-cyan-dark' : ''}>{c}</span>
              </span>
            ))}
          </div>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-2 sm:gap-3">
          <h1 className="min-w-0 break-words text-headline-lg tracking-tight text-paytm-navy lg:text-headline-xl">{title}</h1>
          {chips}
        </div>
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}
