import { useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { GSTIN_RE, LANGS, normalizePhone, PHONE_RE, VPA_RE } from '../format.js';
import { HOME_BY_ROLE, useSession } from '../session.jsx';
import { ErrorNote, Field, Icon, Spinner } from '../components/ui.jsx';
import LocationPicker from '../components/LocationPicker.jsx';
import { AuthFrame } from './Login.jsx';

// Suggestions only (datalist); any category text is accepted.
export const MERCHANT_CATEGORIES = ['electronics', 'appliance', 'mobile', 'grocery', 'pharmacy', 'restaurant', 'apparel', 'footwear', 'salon', 'stationery', 'hardware', 'jewellery', 'bakery'];
export const ADVERTISER_CATEGORIES = ['fitness', 'education', 'healthcare', 'dental', 'restaurant', 'fmcg', 'appliance', 'electronics', 'automobile', 'real_estate', 'finance', 'retail'];

const blank = {
  phone: '',
  password: '',
  confirm: '',
  name: '',
  category: '',
  gstin: '',
  vpa: '',
  lat: null,
  lng: null,
  address: '',
  lang: 'en',
  type: 'local',
};

export default function Register() {
  const { user, status, registerMerchant, registerAdvertiser } = useSession();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const role = params.get('as') === 'advertiser' ? 'advertiser' : 'merchant';
  const [f, setF] = useState(blank);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (status === 'authed' && user) return <Navigate to={HOME_BY_ROLE[user.role] || '/'} replace />;

  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e?.target ? e.target.value : e }));
  const phone = normalizePhone(f.phone);
  const gstin = f.gstin.trim().toUpperCase();
  const locRequired = role === 'merchant' || f.type === 'local';
  const errs = {
    phone: !PHONE_RE.test(phone) && 'Enter a 10-digit Indian mobile number starting with 6–9.',
    password: f.password.length < 8 && 'At least 8 characters.',
    confirm: f.confirm !== f.password && 'Passwords do not match.',
    name: !f.name.trim() && 'Required.',
    category: !f.category.trim() && 'Required.',
    gstin: role === 'merchant' && !GSTIN_RE.test(gstin) && 'GSTIN is 15 characters, e.g. 29ABCDE1234F1Z5.',
    vpa: role === 'merchant' && !VPA_RE.test(f.vpa.trim()) && 'UPI ID looks like name@bank.',
    location: locRequired && (f.lat === null || f.lng === null) && 'Pick your shop location on the map.',
  };
  const show = (k) => (touched ? errs[k] || null : null);
  const valid = !Object.values(errs).some(Boolean);

  const submit = async (e) => {
    e.preventDefault();
    setTouched(true);
    if (!valid) return;
    setBusy(true);
    setError(null);
    const common = {
      phone,
      password: f.password,
      name: f.name.trim(),
      category: f.category.trim().toLowerCase().replace(/\s+/g, '_'),
      ...(f.address.trim() ? { address: f.address.trim() } : {}),
    };
    try {
      let u;
      if (role === 'merchant') {
        u = await registerMerchant({ ...common, gstin, vpa: f.vpa.trim(), lat: f.lat, lng: f.lng, lang: f.lang });
      } else {
        u = await registerAdvertiser({ ...common, type: f.type, ...(f.lat !== null ? { lat: f.lat, lng: f.lng } : {}) });
      }
      navigate(HOME_BY_ROLE[u.role] || '/', { replace: true });
    } catch (ex) {
      setError(ex);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame title="Create your account" subtitle="Each account owns one business profile.">
      <div className="mb-6 grid grid-cols-2 gap-2 rounded-xl border border-slate-200/80 bg-slate-100 p-1.5" role="tablist">
        {[
          ['merchant', 'storefront', 'Merchant'],
          ['advertiser', 'campaign', 'Advertiser'],
        ].map(([v, ic, label]) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={role === v}
            onClick={() => {
              setParams({ as: v }, { replace: true });
              setTouched(false);
              setError(null);
            }}
            className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-label-md transition-all ${role === v ? 'border border-slate-200/60 bg-white font-bold text-paytm-navy shadow-sm' : 'text-slate-600 hover:text-paytm-navy'}`}
          >
            <Icon name={ic} className={`text-[18px] ${role === v ? 'text-paytm-cyan-dark' : ''}`} />
            {label}
          </button>
        ))}
      </div>

      <form className="space-y-5" onSubmit={submit} noValidate>
        <fieldset className="space-y-4">
          <legend className="mb-2 text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">Login</legend>
          <Field label="Mobile number" error={show('phone')}>
            <div className="flex">
              <span className="inline-flex items-center rounded-l-lg border border-r-0 border-input-border bg-surface-ice px-3 text-on-surface-variant">+91</span>
              <input className="input input-lg rounded-l-none" inputMode="tel" autoComplete="tel-national" value={f.phone} onChange={set('phone')} placeholder="10-digit mobile" />
            </div>
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Password" error={show('password')} hint="At least 8 characters">
              <input className="input input-lg" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} />
            </Field>
            <Field label="Confirm password" error={show('confirm')}>
              <input className="input input-lg" type="password" autoComplete="new-password" value={f.confirm} onChange={set('confirm')} />
            </Field>
          </div>
        </fieldset>

        <hr className="border-outline-variant" />
        <fieldset className="space-y-4">
          <legend className="mb-2 text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">
            {role === 'merchant' ? 'Shop' : 'Business'}
          </legend>
          {role === 'advertiser' && (
            <div className="grid grid-cols-2 gap-2">
              {[
                ['local', 'Local business', 'A shop, gym or clinic near merchants'],
                ['brand', 'Brand', 'Subvention on your products, any region'],
              ].map(([v, label, hint]) => (
                <label key={v} className={`cursor-pointer rounded-xl border p-3 transition-colors ${f.type === v ? 'border-primary bg-surface-tint' : 'border-outline bg-white hover:border-primary/50'}`}>
                  <input type="radio" name="adv-type" className="sr-only" checked={f.type === v} onChange={() => setF((s) => ({ ...s, type: v }))} />
                  <span className="block text-label-lg text-paytm-navy">{label}</span>
                  <span className="block text-body-sm text-on-surface-variant">{hint}</span>
                </label>
              ))}
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={role === 'merchant' ? 'Shop name' : 'Business or brand name'} error={show('name')}>
              <input className="input input-lg" value={f.name} onChange={set('name')} autoComplete="organization" />
            </Field>
            <Field label="Category" error={show('category')}>
              <input className="input input-lg" list={`cats-${role}`} value={f.category} onChange={set('category')} placeholder={role === 'merchant' ? 'e.g. electronics' : 'e.g. fitness'} />
              <datalist id={`cats-${role}`}>
                {(role === 'merchant' ? MERCHANT_CATEGORIES : ADVERTISER_CATEGORIES).map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </Field>
          </div>
          {role === 'merchant' && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="GSTIN" error={show('gstin')}>
                <input className="input input-lg font-mono uppercase" maxLength={15} value={f.gstin} onChange={set('gstin')} placeholder="15 characters" />
              </Field>
              <Field label="UPI ID (VPA) for settlement" error={show('vpa')}>
                <input className="input input-lg font-mono" value={f.vpa} onChange={set('vpa')} placeholder="name@bank" autoCapitalize="off" />
              </Field>
            </div>
          )}
          <div>
            <span className="field-label">
              Location {role === 'advertiser' && f.type === 'brand' ? '(optional for brands)' : ''}
            </span>
            <LocationPicker lat={f.lat} lng={f.lng} onChange={({ lat, lng }) => setF((s) => ({ ...s, lat, lng }))} required={locRequired} />
            {show('location') && <span className="mt-1 block text-body-sm text-error-red">{errs.location}</span>}
          </div>
          <Field label="Address (optional)">
            <input className="input" value={f.address} onChange={set('address')} autoComplete="street-address" />
          </Field>
          {role === 'merchant' && (
            <Field label="Soundbox language" hint="Payment announcements and ads play in this language.">
              <select className="input" value={f.lang} onChange={set('lang')}>
                {LANGS.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </fieldset>

        <ErrorNote error={error} title="Could not create account" />
        {touched && !valid && <div className="note note-warn">Fix the highlighted fields to continue.</div>}
        <button className="btn btn-navy btn-lg w-full" disabled={busy}>
          {busy ? <Spinner /> : <Icon name="person_add" className="text-[18px] text-paytm-cyan" />}
          Create {role} account
        </button>
        <p className="text-center text-body-md text-on-surface-variant">
          Already have an account?{' '}
          <Link to="/login" className="font-semibold text-paytm-navy underline-offset-2 hover:underline">
            Log in
          </Link>
        </p>
      </form>
    </AuthFrame>
  );
}
