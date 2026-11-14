import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import { inr, ms, titleCase } from '../format.js';
import { usePoll } from '../hooks.js';
import { HOME_BY_ROLE, useAccount, useConfig, useSession } from '../session.jsx';
import { Icon } from './ui.jsx';

const NAV = {
  merchant: { to: '/merchant', label: 'Merchant Terminal', icon: 'point_of_sale' },
  advertiser: { to: '/advertiser', label: 'Advertiser Portal', icon: 'campaign' },
  admin: { to: '/admin', label: 'Admin & Ledger', icon: 'account_balance' },
};

const ROLE_ICON = { merchant: 'storefront', advertiser: 'campaign', admin: 'admin_panel_settings' };

function Brand() {
  return (
    <Link to="/" className="flex shrink-0 select-none items-center gap-2" aria-label="Paytm SoundShare home">
      <span className="text-[20px] font-extrabold tracking-tight text-white sm:text-2xl">
        Paytm<span className="ml-0.5 font-bold text-paytm-cyan">SoundShare</span>
      </span>
    </Link>
  );
}

/** Real provider state: /api/config (everyone) plus /api/system/status health (admin only). */
function ProviderPill({ system }) {
  const { config, online } = useConfig();
  let tone = 'bg-slate-400';
  let text = 'Connecting…';
  let title = '';
  if (online === false) {
    tone = 'bg-error-red';
    text = 'Backend offline';
  } else if (config) {
    const name = config.provider === 'mock' ? 'Mock payments' : titleCase(config.provider);
    const mode = config.provider_mode === 'live' ? 'live' : 'test mode';
    text = `${name} · ${mode}`;
    tone = config.provider_mode === 'live' ? 'bg-success-green' : 'bg-alert-amber';
    if (system?.provider) {
      if (system.provider.ok === false) {
        tone = 'bg-error-red';
        text = `${name} · error`;
      }
      title = system.provider.detail || '';
    }
  }
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-full border border-white/10 bg-white/5 px-2.5 py-1" title={title}>
      <span className="relative flex h-2 w-2 shrink-0">
        {tone === 'bg-success-green' && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${tone}`} />}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${tone}`} />
      </span>
      <span className="truncate font-mono text-[11px] font-medium text-white/80">{text}</span>
    </div>
  );
}

function WalletPill({ account }) {
  const navigate = useNavigate();
  const goTopUp = () => {
    navigate('/advertiser');
    setTimeout(() => {
      const el = document.getElementById('wallet');
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      document.getElementById('topup-amount')?.focus({ preventScroll: true });
    }, 50);
  };
  return (
    <div className="flex items-center gap-2 rounded-full border border-white/15 bg-white/10 py-1 pl-3 pr-1">
      <span className="hidden text-[11px] uppercase text-white/70 md:inline">Wallet</span>
      <span className="tnum font-mono text-xs font-bold text-paytm-cyan">{account ? inr(account.wallet?.balance_paise ?? account.balance_paise) : '…'}</span>
      <button type="button" onClick={goTopUp} className="rounded-full bg-paytm-cyan px-2.5 py-1 text-[11px] font-extrabold text-paytm-navy transition-colors hover:bg-white active:scale-95">
        + Top Up
      </button>
    </div>
  );
}

function AccountMenu({ user, account }) {
  const { logout } = useSession();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const esc = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  const name = account?.name || user.name;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-white transition-all hover:border-paytm-cyan/40 hover:bg-white/10 sm:px-3"
      >
        <Icon name={ROLE_ICON[user.role] || 'person'} className="text-[18px] text-paytm-cyan" />
        <span className="hidden min-w-0 flex-col text-left sm:flex">
          <span className="max-w-[160px] truncate text-xs font-medium leading-none">{name}</span>
          <span className="mt-0.5 font-mono text-[10px] capitalize text-white/60">{user.role}</span>
        </span>
        <Icon name="expand_more" className="text-[16px] text-white/60" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-50 mt-2 w-64 rounded-xl border border-outline bg-white p-2 text-paytm-navy shadow-ambient">
          <div className="border-b border-outline-variant px-2 pb-2">
            <div className="truncate text-label-lg font-bold">{name}</div>
            <div className="text-body-sm capitalize text-on-surface-variant">{user.role} account</div>
            <div className="mt-1 font-mono text-[11px] text-on-surface-variant">{user.phone}</div>
            <div className="font-mono text-[11px] text-on-surface-variant">{user.merchant_id || user.advertiser_id || user.id}</div>
          </div>
          <button
            type="button"
            role="menuitem"
            className="mt-1 flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-label-md hover:bg-surface-tint"
            onClick={async () => {
              setOpen(false);
              await logout();
              navigate('/login', { replace: true });
            }}
          >
            <Icon name="logout" className="text-[18px]" />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

export function Header() {
  const { user } = useSession();
  const { account } = useAccount();
  const isAdmin = user?.role === 'admin';
  const system = usePoll(() => api.systemStatus(), 20000, [isAdmin], isAdmin);
  const nav = user ? NAV[user.role] : null;
  return (
    <header className="sticky top-0 z-[1100] border-b border-white/10 bg-navy-deep text-white shadow-md">
      <div className="shell flex h-16 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3 lg:gap-4">
          <Brand />
          <span className="hidden h-5 w-px bg-white/10 md:inline-block" />
          <div className="hidden min-w-0 md:block">
            <ProviderPill system={isAdmin ? system.data : null} />
          </div>
        </div>
        {nav && (
          <nav className="hidden items-center gap-1 rounded-xl border border-white/10 bg-white/5 p-1 lg:flex" aria-label="Main">
            <NavLink
              to={nav.to}
              className={({ isActive }) =>
                `flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs transition-colors ${isActive ? 'bg-paytm-cyan font-bold text-paytm-navy shadow' : 'font-medium text-white/70 hover:bg-white/10 hover:text-white'}`
              }
            >
              <Icon name={nav.icon} className="text-[16px]" />
              {nav.label}
            </NavLink>
          </nav>
        )}
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          {user?.role === 'advertiser' && <WalletPill account={account} />}
          {user ? (
            <AccountMenu user={user} account={account} />
          ) : (
            <div className="md:hidden">
              <ProviderPill />
            </div>
          )}
        </div>
      </div>
      {user && (
        <div className="border-t border-white/10 px-4 py-1.5 md:hidden">
          <ProviderPill system={isAdmin ? system.data : null} />
        </div>
      )}
    </header>
  );
}

export function OfflineBanner() {
  const { online, recheck } = useConfig();
  if (online !== false) return null;
  return (
    <div className="border-b border-rose-200 bg-rose-50 text-rose-800" role="alert">
      <div className="shell flex flex-wrap items-center justify-between gap-2 py-2 text-body-sm">
        <span className="flex items-center gap-2">
          <Icon name="cloud_off" className="text-[18px]" />
          <strong>Backend not reachable.</strong> Data on this page may be stale; retrying automatically.
        </span>
        <button type="button" className="btn btn-danger btn-sm" onClick={recheck}>
          Retry now
        </button>
      </div>
    </div>
  );
}

export function Footer() {
  const { user } = useSession();
  const { config, online, aiConfigured, textModel } = useConfig();
  const isAdmin = user?.role === 'admin';
  const stats = usePoll(() => api.adminStats(), 30000, [isAdmin], isAdmin);
  const lat = stats.data?.latency;
  return (
    <footer className="mt-auto border-t border-outline bg-white">
      <div className="shell flex flex-col items-center justify-between gap-2 py-3 text-label-sm md:flex-row">
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
          <span className="font-semibold text-on-surface-variant">Paytm SoundShare</span>
          {config && (
            <span className="flex items-center gap-1.5 text-on-surface-variant">
              <span className={`h-1.5 w-1.5 rounded-full ${config.provider_mode === 'live' ? 'bg-success-green' : 'bg-alert-amber'}`} />
              Payments: {config.provider === 'mock' ? 'mock provider (test mode)' : `${titleCase(config.provider)} (${config.provider_mode})`}
            </span>
          )}
          {aiConfigured === true && <span className="text-on-surface-variant">AI: {textModel || 'configured'}</span>}
          {aiConfigured === false && <span className="font-semibold text-amber-700">AI: not configured (fallback mode)</span>}
          {online === false && <span className="font-semibold text-error-red">Backend offline</span>}
        </div>
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
          {isAdmin && lat && lat.samples > 0 && (
            <span className="tnum text-on-surface-variant">
              Webhook→audio p50 {ms(lat.p50_ms)} · p95 {ms(lat.p95_ms)}
            </span>
          )}
          {isAdmin && (
            <Link
              to="/admin#system"
              onClick={() => setTimeout(() => document.getElementById('system')?.scrollIntoView({ behavior: 'smooth' }), 50)}
              className="font-semibold text-paytm-navy hover:text-paytm-cyan-dark hover:underline"
            >
              System Status
            </Link>
          )}
        </div>
      </div>
    </footer>
  );
}

export function homeFor(user) {
  return (user && HOME_BY_ROLE[user.role]) || '/login';
}
