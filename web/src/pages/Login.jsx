import { useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { normalizePhone, PHONE_RE } from '../format.js';
import { HOME_BY_ROLE, useSession } from '../session.jsx';
import { ErrorNote, Field, Icon, Spinner } from '../components/ui.jsx';

/** Only same-app paths for the user's own area; never protocol-relative or backslash tricks. */
export function safeNext(next, role) {
  const home = HOME_BY_ROLE[role] || '/';
  if (!next || typeof next !== 'string') return home;
  if (!next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return home;
  return next === home || next.startsWith(`${home}/`) || next.startsWith(`${home}?`) || next.startsWith(`${home}#`) ? next : home;
}

export function AuthFrame({ children, title, subtitle }) {
  return (
    <div className="shell grid flex-1 items-start gap-6 py-8 lg:grid-cols-12 lg:py-12">
      <aside className="relative hidden overflow-hidden rounded-2xl bg-gradient-to-br from-paytm-navy to-navy-deep p-8 text-white shadow-md lg:col-span-5 lg:block">
        <div className="pointer-events-none absolute -bottom-10 -right-10 h-48 w-48 rounded-full bg-paytm-cyan/20 blur-2xl" />
        <div className="eyebrow">Paytm SoundShare</div>
        <h2 className="mt-3 text-headline-lg">Merchants keep 100% of the bill.</h2>
        <p className="mt-3 text-body-lg text-white/80">
          Short local ads play on the Soundbox after each payment. Ad spend and brand subvention bids pay the merchant's MDR, and AI
          splits bills into legal GST legs so less MDR is charged in the first place.
        </p>
        <ul className="mt-6 space-y-3 text-body-md text-white/90">
          {[
            ['point_of_sale', 'Merchants: AI bill splitting, Soundbox QR, live settlement'],
            ['campaign', 'Advertisers: create an audio ad in seconds, pay per verified play'],
            ['account_balance', 'Double-entry ledger: every rupee accounted for'],
          ].map(([ic, t]) => (
            <li key={t} className="flex items-start gap-3">
              <Icon name={ic} className="text-[20px] text-paytm-cyan" />
              {t}
            </li>
          ))}
        </ul>
      </aside>
      <div className="mx-auto w-full max-w-xl lg:col-span-7">
        <div className="card relative overflow-hidden sm:p-8">
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-paytm-cyan via-sky-400 to-paytm-navy" />
          <h1 className="text-headline-lg text-paytm-navy">{title}</h1>
          {subtitle && <p className="mt-1 text-body-md text-on-surface-variant">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  );
}

export default function Login() {
  const { user, status, login, expired } = useSession();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  if (status === 'authed' && user) return <Navigate to={safeNext(params.get('next'), user.role)} replace />;

  const p = normalizePhone(phone);
  const phoneErr = touched && !PHONE_RE.test(p) ? 'Enter a 10-digit Indian mobile number starting with 6–9.' : null;

  const submit = async (e) => {
    e.preventDefault();
    setTouched(true);
    if (!PHONE_RE.test(p) || !password) return;
    setBusy(true);
    setError(null);
    try {
      const u = await login(p, password);
      navigate(safeNext(params.get('next'), u.role), { replace: true });
    } catch (ex) {
      setError(ex.status === 401 ? Object.assign(new Error('Wrong phone number or password.'), { status: 401 }) : ex);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame title="Log in" subtitle="Merchants, advertisers and admins use the same login.">
      {expired && <div className="note note-info mb-4">Your session ended. Log in again to continue.</div>}
      <form className="space-y-4" onSubmit={submit} noValidate>
        <Field label="Mobile number" error={phoneErr}>
          <div className="flex">
            <span className="inline-flex items-center rounded-l-lg border border-r-0 border-input-border bg-surface-ice px-3 text-body-md text-on-surface-variant">+91</span>
            <input
              className={`input input-lg rounded-l-none ${phoneErr ? 'input-error' : ''}`}
              inputMode="tel"
              autoComplete="tel-national"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onBlur={() => setTouched(true)}
              placeholder="10-digit mobile"
              required
            />
          </div>
        </Field>
        <Field label="Password">
          <input className="input input-lg" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <ErrorNote error={error} title="Login failed" />
        <button className="btn btn-navy btn-lg w-full" disabled={busy}>
          {busy ? <Spinner /> : <Icon name="login" className="text-[18px] text-paytm-cyan" />}
          Log in
        </button>
      </form>
      <div className="mt-6 grid gap-2 border-t border-outline-variant pt-4 text-body-md sm:grid-cols-2">
        <Link to="/register?as=merchant" className="btn btn-outline">
          <Icon name="storefront" className="text-[18px] text-paytm-cyan-dark" />
          New merchant? Sign up
        </Link>
        <Link to="/register?as=advertiser" className="btn btn-outline">
          <Icon name="campaign" className="text-[18px] text-paytm-cyan-dark" />
          New advertiser? Sign up
        </Link>
      </div>
    </AuthFrame>
  );
}
