import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api.js';
import { inr, LANGS, num, pct, time, titleCase, VPA_RE } from '../format.js';
import { usePoll } from '../hooks.js';
import { useAccount } from '../session.jsx';
import { Card, ChipInput, Empty, ErrorNote, Field, Icon, PageHead, Pill, Progress, Spinner, Tabs, Toggle } from '../components/ui.jsx';
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

const RENTAL_COLOR = '#00BAF2'; // paytm-cyan
const EARN_COLOR = '#00B06F'; // success-green
const shortDate = (d) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });

function DailyChart({ daily }) {
  const max = Math.max(1, ...daily.map((d) => d.earnings_paise + d.rental_paise));
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-4 text-body-sm text-on-surface">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: EARN_COLOR }} /> Your ad earnings
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: RENTAL_COLOR }} /> Paid towards Soundbox rental
        </span>
      </div>
      <div className="flex h-40 items-end gap-[2px] border-b border-outline-variant" role="img" aria-label="Daily ad money over the last 30 days">
        {daily.map((d) => {
          const tot = d.earnings_paise + d.rental_paise;
          return (
            <div
              key={d.date}
              className="relative flex h-full min-w-0 flex-1 flex-col justify-end rounded-t hover:bg-slate-100"
              title={`${shortDate(d.date)}: earnings ${inr(d.earnings_paise)}, rental ${inr(d.rental_paise)}, ${d.plays} ad play${d.plays === 1 ? '' : 's'}`}
            >
              {tot > 0 && (
                <div className="flex flex-col gap-[2px] overflow-hidden rounded-t" style={{ height: `${Math.max(3, (tot / max) * 100)}%` }}>
                  {d.earnings_paise > 0 && <div style={{ flexGrow: d.earnings_paise, background: EARN_COLOR }} />}
                  {d.rental_paise > 0 && <div style={{ flexGrow: d.rental_paise, background: RENTAL_COLOR }} />}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-label-sm text-on-surface-variant">
        <span>{daily.length ? shortDate(daily[0].date) : ''}</span>
        <span>Tallest day {inr(max)}</span>
        <span>Today</span>
      </div>
      <details className="mt-3 rounded-lg border border-outline-variant">
        <summary className="cursor-pointer px-3 py-2 text-label-md text-paytm-navy">Show as table</summary>
        <div className="max-h-64 overflow-auto border-t border-outline-variant">
          <table className="tbl">
            <thead>
              <tr>
                <th>Day</th>
                <th className="text-right">Ad plays</th>
                <th className="text-right">Rental</th>
                <th className="text-right">Earnings</th>
              </tr>
            </thead>
            <tbody>
              {[...daily]
                .reverse()
                .filter((d) => d.plays || d.earnings_paise || d.rental_paise)
                .map((d) => (
                  <tr key={d.date}>
                    <td>{shortDate(d.date)}</td>
                    <td className="tnum text-right">{num(d.plays)}</td>
                    <td className="text-right font-mono">{inr(d.rental_paise)}</td>
                    <td className="text-right font-mono">{inr(d.earnings_paise)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function Earnings({ merchant }) {
  const { data: t, error } = usePoll(() => api.earnings(merchant.id, 30), 10000, [merchant.id]);
  if (!t) {
    return error ? (
      <ErrorNote error={error} title="Could not load your earnings" />
    ) : (
      <div className="flex items-center gap-2 text-on-surface-variant">
        <Spinner /> Loading earnings…
      </div>
    );
  }
  const tot = t.totals || {};
  const r = t.rental || {};
  const fee = r.monthly_fee_paise ?? 0;
  const paid = Math.min(r.paid_this_month_paise ?? 0, fee);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <Kpi label="Today" icon="today" value={inr(tot.today_paise)} sub="Ad earnings" />
        <Kpi label="Last 7 days" icon="date_range" value={inr(tot.week_paise)} sub="Ad earnings" />
        <Kpi label="This month" icon="calendar_month" value={inr(tot.month_paise)} sub={`${num(tot.plays_month)} ad plays`} />
        <Kpi label="Lifetime earnings" icon="account_balance_wallet" value={inr(tot.lifetime_paise)} sub={`${num(tot.plays_lifetime)} ad plays`} highlight />
      </div>

      <Card icon="speaker" title="Soundbox rental" subtitle="Ad money pays your Soundbox rental first each month. After that, everything is your earnings.">
        <div className="grid items-center gap-6 md:grid-cols-2">
          <div className="flex items-center gap-4">
            <div>
              <div className="text-label-sm text-on-surface-variant">Monthly rental</div>
              <div className="tnum text-headline-md text-paytm-navy">{inr(fee)}</div>
            </div>
            <Icon name="arrow_forward" className="text-[24px] text-paytm-cyan" />
            <div>
              <div className="text-label-sm text-on-surface-variant">Still to pay this month</div>
              <div className={`tnum text-headline-lg ${r.due_paise === 0 ? 'text-success-green' : 'text-paytm-navy'}`}>{inr(r.due_paise ?? fee)}</div>
            </div>
          </div>
          <div className="space-y-3">
            <div>
              <div className="mb-1 flex justify-between text-body-sm">
                <span>Paid by ads this month: {inr(paid)}</span>
                <span className="text-on-surface-variant">{pct(fee ? (paid / fee) * 100 : 0, 0)}</span>
              </div>
              <Progress value={paid} max={fee || 1} tone="good" label="Rental paid by ads" />
            </div>
            <div className="text-body-sm text-on-surface-variant">
              {r.due_paise === 0
                ? 'Rental fully paid by ads this month. Every new ad play is earnings.'
                : r.plays_to_cover != null
                  ? `About ${num(r.plays_to_cover)} more ad plays clear this month's rental.`
                  : 'Rental is paid as ads play at your counter.'}
            </div>
          </div>
        </div>
      </Card>

      <Card icon="bar_chart" title="Last 30 days" subtitle={`Ad money from your counter, day by day. Paytm keeps ${pct(t.platform_share_pct ?? 25, 0)}; the rest is yours.`}>
        {tot.plays_lifetime ? (
          <DailyChart daily={t.daily || []} />
        ) : (
          <Empty icon="campaign" title="No ad plays yet">
            When a nearby business's ad plays while a customer pays at your counter, the money shows up here.
          </Empty>
        )}
      </Card>

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <Card icon="storefront" title="Who paid you" subtitle="Advertisers whose ads played at your counter">
          {(t.by_advertiser || []).length === 0 ? (
            <p className="text-body-sm text-on-surface-variant">No advertisers yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Advertiser</th>
                    <th className="text-right">Full ads</th>
                    <th className="text-right">Sponsor lines</th>
                    <th className="text-right">Ad money</th>
                  </tr>
                </thead>
                <tbody>
                  {t.by_advertiser.map((a) => (
                    <tr key={a.advertiser_id}>
                      <td>{a.name}</td>
                      <td className="tnum text-right">{num(a.plays)}</td>
                      <td className="tnum text-right">{num(a.tags)}</td>
                      <td className="text-right font-mono">{inr(a.ad_revenue_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card icon="receipt_long" title="Recent bills with ads" subtitle="What each paid bill's ad earned you">
          {(t.recent || []).length === 0 ? (
            <p className="text-body-sm text-on-surface-variant">No settled bills yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Bill</th>
                    <th>When</th>
                    <th className="text-right">Ad money</th>
                    <th className="text-right">Rental</th>
                    <th className="text-right">Earned</th>
                  </tr>
                </thead>
                <tbody>
                  {t.recent.map((o) => (
                    <tr key={o.order_id}>
                      <td>
                        <div className="font-mono text-[12px]">{o.order_id}</div>
                        <div className="text-label-sm text-on-surface-variant">
                          {inr(o.bill_paise)}
                          {o.advertisers?.length ? ` · ${o.advertisers.join(', ')}` : ''}
                        </div>
                      </td>
                      <td className="whitespace-nowrap">{time(o.settled_at)}</td>
                      <td className="text-right font-mono">{inr(o.ad_revenue_paise)}</td>
                      <td className="text-right font-mono">{inr(o.rental_paid_paise)}</td>
                      <td className="text-right font-mono font-semibold text-success-green">{inr(o.earnings_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
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
          Bills you create on the terminal show up here with their payment status and ad earnings.
        </Empty>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-outline">
          <table className="tbl">
            <thead>
              <tr>
                <th>Order</th>
                <th>Created</th>
                <th>Status</th>
                <th className="text-right">Total</th>
                <th className="text-right">Ad earnings</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="cursor-pointer hover:bg-surface-subtle" onClick={() => onOpen(o.id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen(o.id)}>
                  <td className="font-mono font-semibold">{o.id}</td>
                  <td className="whitespace-nowrap">{time(o.created_at)}</td>
                  <td>
                    <Pill status={o.status} dot />
                  </td>
                  <td className="text-right font-mono">{inr(o.total_paise)}</td>
                  <td className="text-right">{o.settlement?.status === 'settled' ? inr(o.settlement.earnings_paise ?? 0) : '—'}</td>
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
    { value: 'earnings', label: 'Earnings', icon: 'account_balance_wallet' },
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
                <button type="button" className="text-left" onClick={() => setParam({ tab: 'earnings', order: '' })} title="Open your earnings tracker">
                  <div className="text-label-sm text-on-surface-variant">Ad earnings</div>
                  <div className={`tnum text-headline-sm ${merchant.stats.earnings_lifetime_paise ? 'text-success-green' : 'text-paytm-navy'}`}>
                    {inr(merchant.stats.earnings_lifetime_paise ?? 0)}
                  </div>
                </button>
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
      {(tab === 'earnings' || tab === 'savings') && <Earnings merchant={merchant} />}
      {tab === 'settings' && <Settings merchant={merchant} onSaved={(m) => setAccount((cur) => ({ ...cur, ...m }))} />}
    </div>
  );
}
