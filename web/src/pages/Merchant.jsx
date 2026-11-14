import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api.js';
import { inr, LANGS, num, pct, time, titleCase, VPA_RE } from '../format.js';
import { usePoll } from '../hooks.js';
import { useAccount } from '../session.jsx';
import { Card, ChipInput, Empty, ErrorNote, Field, Icon, PageHead, Pill, Progress, SourceBadge, Spinner, Tabs, Toggle } from '../components/ui.jsx';
import BillBuilder from '../components/BillBuilder.jsx';
import CatalogManager from '../components/CatalogManager.jsx';
import DeviceManager from '../components/DeviceManager.jsx';
import LocationPicker from '../components/LocationPicker.jsx';

const BLOCK_SUGGESTIONS = ['alcohol', 'tobacco', 'gambling', 'dating', 'crypto', 'fast_food'];

function Kpi({ label, value, sub, icon, highlight }) {
  if (highlight) {
    return (
      <div className="relative overflow-hidden rounded-xl bg-gradient-to-br from-paytm-navy to-navy-deep p-3.5 text-white shadow-md">
        <div className="pointer-events-none absolute -bottom-3 -right-3 h-16 w-16 rounded-full bg-paytm-cyan/20 blur-xl" />
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-extrabold uppercase tracking-wider text-paytm-cyan">{label}</span>
          <Icon name={icon} className="text-[18px] text-paytm-cyan" />
        </div>
        <div className="tnum mt-3 text-2xl font-black">{value}</div>
        {sub && <div className="mt-1 inline-flex rounded-full border border-paytm-cyan/40 bg-paytm-cyan/20 px-2 py-0.5 text-[10px] font-bold text-paytm-cyan">{sub}</div>}
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-outline-variant bg-white p-3.5 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">{label}</span>
        <Icon name={icon} className="text-[18px] text-paytm-cyan" />
      </div>
      <div className="tnum mt-3 text-2xl font-black text-paytm-navy">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] font-medium text-on-surface-variant">{sub}</div>}
    </div>
  );
}

function SharedCard({ st }) {
  const sh = st.shared;
  if (!sh) return null;
  return (
    <Card icon="diversity_3" title="SoundShare pool"
      subtitle="Once your own fee and Soundbox rental are covered, leftover ad money from your counter joins a shared pool that pays other shops' fees, and theirs helps you when your own ads fall short.">
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <Kpi label="You contributed" icon="volunteer_activism" value={inr(sh.contributed_paise)} sub="Your ad surplus shared with nearby shops" />
        <Kpi label="Pool paid your fees" icon="verified" value={inr(sh.received_for_fees_paise)} sub={`Up to ${inr(sh.daily_cap_paise)} per day`} highlight />
        <Kpi label="Pool paid your rental" icon="speaker" value={inr(sh.received_for_rental_paise)} sub="When your own ads weren't enough" />
        <Kpi label="Network pool now" icon="account_balance_wallet" value={inr(sh.network_pool_balance_paise)} sub="Available to all SoundShare shops" />
      </div>
      <div className="mt-3 text-body-sm text-on-surface-variant">
        {st.ad_income_per_play_paise != null ? `Average verified ad at your counter: ${inr(st.ad_income_per_play_paise)}. ` : ''}
        Paytm keeps {pct(st.platform_take_pct ?? 25, 0)} of ad surplus; the rest stays with merchants.
      </div>
    </Card>
  );
}

function Savings({ merchant }) {
  const st = merchant?.stats;
  if (!st) return <div className="flex items-center gap-2 text-on-surface-variant"><Spinner /> Loading stats…</div>;
  const r = st.rental || {};
  const fee = r.monthly_fee_paise ?? 0;
  const paid = Math.min(r.paid_this_month_paise ?? 0, fee);
  const net = Math.max(0, fee - paid);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-5">
        <Kpi label="Payments settled" icon="receipt_long" value={num(st.tx_count)} sub={`${inr(st.gross_paise)} collected`} />
        <Kpi label="MDR charged" icon="credit_card" value={inr(st.mdr_paise)} sub="Paid in full to the acquirer" />
        <Kpi label="Covered for you" icon="verified" value={inr(st.covered_paise)} sub={st.tx_count ? `${pct(st.coverage_pct)} of MDR, by ads and the pool` : 'No payments yet'} highlight />
        <Kpi label="Saved by GST split" icon="call_split" value={inr(st.saved_by_factorization_paise)} sub="Less MDR charged" />
        <Kpi label="You paid in fees" icon="savings" value={inr(Math.max(0, (st.mdr_paise ?? 0) - (st.covered_paise ?? 0)))} sub="MDR not covered" />
      </div>
      {st.tx_count === 0 && (
        <Empty icon="savings" title="No settled payments yet">
          Your savings appear here after your first bill is paid and settled.
        </Empty>
      )}
      <Card icon="speaker" title="Soundbox rental" subtitle="Ad money left after your own fees pays your Soundbox rental for the month, before anything is shared.">
        <div className="grid items-center gap-6 md:grid-cols-2">
          <div className="flex items-center gap-4">
            <div>
              <div className="text-label-sm text-on-surface-variant">Monthly rental</div>
              <div className="tnum text-headline-md text-slate-400 line-through decoration-2">{inr(fee)}</div>
            </div>
            <Icon name="arrow_forward" className="text-[24px] text-paytm-cyan" />
            <div>
              <div className="text-label-sm text-on-surface-variant">You pay this month</div>
              <div className={`tnum text-headline-lg ${net === 0 ? 'text-success-green' : 'text-paytm-navy'}`}>{inr(net)}</div>
            </div>
          </div>
          <div className="space-y-3">
            <div>
              <div className="mb-1 flex justify-between text-body-sm">
                <span>Paid by ads this month {inr(paid)}</span>
                <span className="text-on-surface-variant">{pct(fee ? (paid / fee) * 100 : 0, 0)}</span>
              </div>
              <Progress value={paid} max={fee || 1} tone="good" label="Rental paid by ads" />
            </div>
            <div className="text-body-sm text-on-surface-variant">
              {net === 0
                ? 'Rental fully paid by ads this month.'
                : r.plays_to_cover != null
                  ? `About ${num(r.plays_to_cover)} more verified ad plays on fee-free sales clear this month's rental.`
                  : 'Rental is paid as ads play at your counter.'}
            </div>
          </div>
        </div>
      </Card>
      <SharedCard st={st} />
    </div>
  );
}

function Orders({ onOpen }) {
  const { data: orders, error } = usePoll(() => api.orders({ limit: 50 }), 8000, []);
  return (
    <Card icon="history" title="Order history" subtitle="Your 50 most recent bills">
      <ErrorNote error={error} title="Could not load orders" className="mb-3" />
      {!orders ? (
        !error && <div className="flex items-center gap-2 text-on-surface-variant"><Spinner /> Loading…</div>
      ) : orders.length === 0 ? (
        <Empty icon="receipt_long" title="No orders yet">
          Bills you create on the terminal show up here with their payment status and settlement.
        </Empty>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-outline">
          <table className="tbl">
            <thead>
              <tr>
                <th>Order</th>
                <th>Created</th>
                <th>Legs</th>
                <th>Division</th>
                <th>Status</th>
                <th className="text-right">Total</th>
                <th className="text-right">Fee covered</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="cursor-pointer hover:bg-surface-subtle" onClick={() => onOpen(o.id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen(o.id)}>
                  <td className="font-mono font-semibold">{o.id}</td>
                  <td className="whitespace-nowrap">{time(o.created_at)}</td>
                  <td>{o.legs?.length ?? '—'}</td>
                  <td>{o.division?.source ? <SourceBadge source={o.division.source} model={o.division.model} reason={o.division.fallback_reason} /> : '—'}</td>
                  <td>
                    <Pill status={o.status} dot />
                  </td>
                  <td className="text-right font-mono">{inr(o.total_paise)}</td>
                  <td className="text-right">{o.settlement ? pct(o.settlement.coverage_pct) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Settings({ merchant, onSaved }) {
  const init = (m) => ({
    name: m.name || '',
    blocked: m.blocked_categories || [],
    factorize: !!m.factorization_enabled,
    lang: m.lang || 'en',
    vpa: m.vpa || '',
    lat: m.lat ?? null,
    lng: m.lng ?? null,
    address: m.address || '',
  });
  const [f, setF] = useState(() => init(merchant));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(false);
  useEffect(() => setF(init(merchant)), [merchant.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const vpaBad = !VPA_RE.test(f.vpa.trim());
  const save = async () => {
    setBusy(true);
    setErr(null);
    setOk(false);
    try {
      const m = await api.updateMerchant(merchant.id, {
        name: f.name.trim(),
        blocked_categories: f.blocked,
        factorization_enabled: f.factorize,
        lang: f.lang,
        vpa: f.vpa.trim(),
        lat: f.lat,
        lng: f.lng,
        address: f.address.trim() || null,
      });
      onSaved(m);
      setOk(true);
      setTimeout(() => setOk(false), 2500);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
      <div className="space-y-6">
        <Card icon="block" title="Ad controls" subtitle="Ads in these categories never play on your Soundbox.">
          <ChipInput values={f.blocked} onChange={(blocked) => setF((s) => ({ ...s, blocked }))} suggestions={BLOCK_SUGGESTIONS} placeholder="Type a category, press Enter" />
          <p className="mt-2 text-body-sm text-on-surface-variant">Competitor ads in your own category ({titleCase(merchant.category)}) are excluded automatically.</p>
        </Card>
        <Card icon="call_split" title="Billing">
          <Toggle
            checked={f.factorize}
            onChange={(factorize) => setF((s) => ({ ...s, factorize }))}
            label="Split bills along GST supply boundaries by default"
            hint="Off: every bill is a single QR, and sponsors cover the whole fee."
          />
        </Card>
        <Card icon="storefront" title="Shop details">
          <div className="space-y-3">
            <Field label="Shop name">
              <input className="input" value={f.name} onChange={(e) => setF((s) => ({ ...s, name: e.target.value }))} />
            </Field>
            <Field label="Settlement UPI ID (VPA)" error={vpaBad ? 'UPI ID looks like name@bank.' : null}>
              <input className="input font-mono" value={f.vpa} onChange={(e) => setF((s) => ({ ...s, vpa: e.target.value }))} />
            </Field>
            <Field label="Soundbox language">
              <select className="input" value={f.lang} onChange={(e) => setF((s) => ({ ...s, lang: e.target.value }))}>
                {LANGS.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3 text-body-sm">
              <div>
                <div className="field-label">GSTIN</div>
                <div className="font-mono text-paytm-navy">{merchant.gstin}</div>
              </div>
              <div>
                <div className="field-label">Category</div>
                <div className="text-paytm-navy">{titleCase(merchant.category)}</div>
              </div>
            </div>
          </div>
        </Card>
      </div>
      <div className="space-y-6">
        <Card icon="location_on" title="Location" subtitle="Advertisers target Soundboxes near them, so keep this accurate.">
          <LocationPicker lat={f.lat} lng={f.lng} onChange={({ lat, lng }) => setF((s) => ({ ...s, lat, lng }))} required height={300} />
          <Field label="Address" className="mt-3">
            <input className="input" value={f.address} onChange={(e) => setF((s) => ({ ...s, address: e.target.value }))} />
          </Field>
        </Card>
        <ErrorNote error={err} title="Could not save settings" />
        <div className="flex items-center justify-end gap-3">
          {ok && (
            <span className="flex items-center gap-1 text-label-md text-success-green">
              <Icon name="check_circle" className="text-[18px]" /> Saved
            </span>
          )}
          <button type="button" className="btn btn-navy btn-lg" disabled={busy || vpaBad || !f.name.trim()} onClick={save}>
            {busy ? <Spinner /> : <Icon name="save" className="text-[18px] text-paytm-cyan" />}
            Save settings
          </button>
        </div>
      </div>
    </div>
  );
}

// Busy hour: the Soundbox plays only the payment message + a 1-second sponsor tag, never a full ad,
// so back-to-back payments are never held up.
function BusyHourSwitch({ merchant, onChange }) {
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  const on = !!merchant.busy_mode;
  const toggle = async () => {
    setSaving(true);
    setErr(null);
    try {
      const m = await api.updateMerchant(merchant.id, { busy_mode: !on });
      onChange?.((prev) => ({ ...(prev || {}), ...m }));
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        onClick={toggle}
        disabled={saving}
        title={on ? 'Busy hour ON: only a short sponsor line after each payment, no full ads' : 'Turn on during rush: no full ads, only a short sponsor line'}
        className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-label-lg shadow-sm transition-colors ${on ? 'border-amber-400 bg-amber-50 text-amber-900' : 'border-outline bg-white text-paytm-navy hover:border-paytm-cyan'}`}
      >
        <Icon name={on ? 'bolt' : 'schedule'} className="text-[20px]" />
        Busy hour
        <span className={`relative inline-block h-5 w-9 rounded-full transition-colors ${on ? 'bg-amber-500' : 'bg-slate-300'}`}>
          <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${on ? 'left-[18px]' : 'left-0.5'}`} />
        </span>
        <span className="text-label-sm font-bold">{saving ? '…' : on ? 'ON' : 'OFF'}</span>
      </button>
      {on && <span className="text-label-sm text-amber-800">Only the sponsor line plays after each payment</span>}
      {err && <span className="text-label-sm text-error-red">Couldn't switch: {err.message}</span>}
    </div>
  );
}

export default function Merchant() {
  const { account: merchant, error, reload, setAccount } = useAccount();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') || 'terminal';
  const orderId = params.get('order') || '';
  const [catalog, setCatalog] = useState(null);
  const [catErr, setCatErr] = useState(null);
  const devices = usePoll(() => api.devices(), 5000, []);

  const setParam = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if (!merchant?.id) return;
    api
      .catalog(merchant.id)
      .then((c) => {
        setCatalog(c);
        setCatErr(null);
      })
      .catch(setCatErr);
  }, [merchant?.id]);

  if (!merchant) {
    return (
      <div className="shell py-6">
        {error ? <ErrorNote error={error} title="Could not load your shop" /> : <div className="flex items-center gap-2 text-on-surface-variant"><Spinner /> Loading your shop…</div>}
      </div>
    );
  }

  const devList = devices.data || [];
  const tabs = [
    { value: 'terminal', label: 'Terminal', icon: 'point_of_sale' },
    { value: 'orders', label: 'Orders', icon: 'history' },
    { value: 'catalog', label: 'Catalog', icon: 'inventory_2', badge: catalog ? catalog.length : null },
    { value: 'devices', label: 'Soundboxes', icon: 'speaker', badge: devices.data ? devList.length : null },
    { value: 'savings', label: 'Savings', icon: 'savings' },
    { value: 'settings', label: 'Settings', icon: 'settings' },
  ];

  return (
    <div className="shell space-y-6 py-6">
      <PageHead
        crumbs={['Merchant', 'SoundShare Terminal']}
        title={merchant.name}
        chips={
          <span className="rounded-full border border-paytm-cyan/30 bg-paytm-cyan-light px-2.5 py-0.5 text-label-sm text-paytm-navy">
            {titleCase(merchant.category)} · GSTIN <span className="font-mono">{merchant.gstin}</span>
          </span>
        }
        right={
          merchant.stats && (
            <div className="flex flex-wrap items-center gap-3">
            <BusyHourSwitch merchant={merchant} onChange={setAccount} />
            <div className="flex items-center gap-4 rounded-xl border border-outline bg-white px-4 py-2 shadow-sm">
              <div>
                <div className="text-label-sm text-on-surface-variant">MDR covered</div>
                <div className={`tnum text-headline-sm ${merchant.stats.tx_count ? 'text-success-green' : 'text-on-surface-variant'}`} title={merchant.stats.tx_count ? undefined : 'No settled payments yet'}>
                  {merchant.stats.tx_count ? pct(merchant.stats.coverage_pct) : '—'}
                </div>
              </div>
              <span className="h-8 w-px bg-outline-variant" />
              <div>
                <div className="text-label-sm text-on-surface-variant">Soundboxes online</div>
                <div className="tnum text-headline-sm text-paytm-navy">
                  {devList.filter((d) => d.online).length}/{devList.length}
                </div>
              </div>
            </div>
            </div>
          )
        }
      />
      <Tabs value={tab} onChange={(t) => setParam({ tab: t === 'terminal' ? '' : t })} tabs={tabs} />

      {tab === 'terminal' && (
        <BillBuilder
          merchant={merchant}
          catalog={catErr ? [] : catalog}
          devices={devList}
          orderId={orderId}
          onOrder={(o) => setParam({ order: o.id })}
          onCloseOrder={() => {
            setParam({ order: '' });
            reload();
          }}
          goTab={(t) => setParam({ tab: t })}
        />
      )}
      {tab === 'orders' && <Orders onOpen={(id) => setParam({ tab: '', order: id })} />}
      {tab === 'catalog' && <CatalogManager merchantId={merchant.id} catalog={catalog} setCatalog={setCatalog} error={catErr} />}
      {tab === 'devices' && <DeviceManager devices={devices.data} error={devices.error} reload={devices.reload} />}
      {tab === 'savings' && <Savings merchant={merchant} />}
      {tab === 'settings' && <Settings merchant={merchant} onSaved={(m) => setAccount((cur) => ({ ...cur, ...m }))} />}
    </div>
  );
}
