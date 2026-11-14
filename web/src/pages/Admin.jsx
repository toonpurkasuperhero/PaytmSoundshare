import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { ago, inr, ms, num, pct, time, titleCase } from '../format.js';
import { usePoll, useNow, useSocket } from '../hooks.js';
import { AiWarning, Card, Empty, ErrorNote, Icon, PageHead, Pill, Segmented } from '../components/ui.jsx';
import Sankey, { FlowTable } from '../components/Sankey.jsx';

const REFRESH_MS = 5000;
const LATENCY_TARGET = 300;

function Tile({ label, icon, children, highlight }) {
  if (highlight) {
    return (
      <div className="relative flex min-w-0 flex-col justify-between overflow-hidden rounded-xl bg-gradient-to-br from-paytm-navy to-navy-deep p-3.5 text-white shadow-md">
        <div className="pointer-events-none absolute -bottom-3 -right-3 h-16 w-16 rounded-full bg-paytm-cyan/20 blur-xl" />
        <div className="flex items-center justify-between gap-1">
          <span className="text-[11px] font-extrabold uppercase tracking-wider text-paytm-cyan">{label}</span>
          <Icon name={icon} className="text-[18px] text-paytm-cyan" />
        </div>
        <div className="mt-2.5">{children}</div>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-col justify-between rounded-xl border border-outline-variant bg-white p-3.5 shadow-sm">
      <div className="flex items-center justify-between gap-1">
        <span className="min-w-0 text-[11px] font-bold uppercase leading-tight tracking-wider text-on-surface-variant">{label}</span>
        <Icon name={icon} className="shrink-0 text-[18px] text-paytm-cyan" />
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

const Big = ({ children, light }) => <div className={`tnum truncate text-2xl font-black ${light ? 'text-white' : 'text-paytm-navy'}`}>{children}</div>;
const Sub = ({ children, tone }) => <div className={`mt-0.5 text-[11px] font-medium leading-snug ${tone || 'text-on-surface-variant'}`}>{children}</div>;

function Kpis({ s }) {
  const lat = s.latency || {};
  const latTone = (v) => (v === null || v === undefined ? 'text-on-surface-variant' : v <= LATENCY_TARGET ? 'text-paytm-navy' : 'text-amber-700');
  return (
    <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-4 xl:grid-cols-8">
      <Tile label="Orders" icon="receipt_long">
        <Big>{num(s.orders ?? 0)}</Big>
        <Sub>{num(s.settled_orders ?? 0)} settled</Sub>
      </Tile>
      <Tile label="Gross collected" icon="payments">
        <Big>{inr(s.gross_paise ?? 0, { decimals: 0 })}</Big>
        <Sub>{s.avg_ticket_paise ? `Avg ticket ${inr(s.avg_ticket_paise, { decimals: 0 })}` : 'No settled orders'}</Sub>
      </Tile>
      <Tile label="Ad revenue" icon="campaign">
        <Big>{inr(s.ad_revenue_paise ?? 0)}</Big>
        <Sub>{num(s.plays ?? 0)} full ads · {num(s.tag_plays ?? 0)} sponsor lines</Sub>
      </Tile>
      <Tile label="Merchant ad earnings" icon="account_balance_wallet" highlight>
        <Big light>{inr(s.merchant_earnings_paise ?? 0)}</Big>
        <div className="mt-1 inline-flex rounded-full border border-paytm-cyan/40 bg-paytm-cyan/20 px-2 py-0.5 text-[10px] font-bold text-paytm-cyan">
          + {inr(s.rental_paid_by_ads_paise ?? 0)} Soundbox rental paid by ads
        </div>
      </Tile>
      <Tile label="Paytm share" icon="hub">
        <Big>{inr(s.platform_paise ?? 0)}</Big>
        <Sub tone="font-mono font-semibold text-paytm-cyan-dark">{s.ad_revenue_paise ? `${pct(((s.platform_paise ?? 0) / s.ad_revenue_paise) * 100, 0)} of ad revenue` : '—'}</Sub>
      </Tile>
      <Tile label="Verified plays" icon="volume_up">
        <Big>{num(s.plays ?? 0)}</Big>
        <Sub tone="font-mono text-on-surface-variant">
          {s.play_verification_pct !== null && s.play_verification_pct !== undefined ? `${pct(s.play_verification_pct)} verified · ${num(s.plays_released ?? 0)} released` : 'No plays yet'}
        </Sub>
      </Tile>
      <Tile label="Soundboxes" icon="speaker">
        <div className="flex items-baseline gap-1">
          <Big>{num(s.devices_online ?? 0)}</Big>
          <span className="text-xs font-medium text-on-surface-variant">of {num(s.devices_total ?? 0)}</span>
        </div>
        <Sub tone={s.devices_total && !s.devices_online ? 'font-semibold text-rose-600' : undefined}>{s.devices_total ? (s.devices_online ? 'online now' : 'all offline') : 'none paired'}</Sub>
      </Tile>
      <Tile label="Latency" icon="speed">
        <div className="space-y-0.5 font-mono text-[11px]">
          {[
            ['P50', lat.p50_ms],
            ['P95', lat.p95_ms],
            ['LAST', lat.last_ms],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between text-on-surface-variant">
              <span>{k}</span>
              <span className={`font-bold ${latTone(v)}`}>{ms(v)}</span>
            </div>
          ))}
        </div>
        <div className="mt-1 font-mono text-[10px] font-bold leading-snug text-on-surface-variant">{lat.samples ? `${num(lat.samples)} samples · target < ${LATENCY_TARGET} ms` : 'webhook → audio, no samples yet'}</div>
      </Tile>
    </div>
  );
}

function Balances({ balances, invariant, error }) {
  return (
    <Card className="lg:col-span-4" title="Ledger balances" subtitle="Double-entry; every transaction sums to zero" actions={<Icon name="balance" className="text-[20px] text-paytm-cyan" />}>
      <ErrorNote error={error} title="Could not load balances" className="mb-2" />
      <div className="overflow-hidden rounded-xl border border-outline-variant bg-surface-subtle">
        <div className="flex items-center justify-between border-b border-outline-variant bg-surface-high px-3.5 py-2 text-[11px] font-bold uppercase text-on-surface-variant">
          <span>Account</span>
          <span>Balance</span>
        </div>
        {!balances?.length ? (
          <div className="px-3.5 py-6 text-center text-body-sm text-on-surface-variant">No ledger postings yet.</div>
        ) : (
          <div className="max-h-[380px] divide-y divide-outline-variant overflow-y-auto font-mono text-xs">
            {balances.map((b) => {
              const merchant = String(b.account).startsWith('merchant:');
              return (
                <div key={b.account} className={`flex items-center justify-between gap-2 px-3.5 py-2 ${merchant ? 'bg-sky-50/80' : 'hover:bg-white'}`}>
                  <div className="min-w-0">
                    <div className={`truncate text-paytm-navy ${merchant ? 'font-bold' : 'font-semibold'}`}>{b.label || b.account}</div>
                    <div className={`truncate text-[10px] ${merchant ? 'font-semibold text-paytm-cyan-dark' : 'text-on-surface-variant'}`}>{b.account}</div>
                  </div>
                  <div className={`tnum shrink-0 font-bold ${b.balance_paise < 0 ? 'text-rose-600' : merchant ? 'text-paytm-cyan-dark' : 'text-paytm-navy'}`}>{inr(b.balance_paise)}</div>
                </div>
              );
            })}
          </div>
        )}
        <div className="flex items-center justify-between border-t border-outline-variant bg-surface-high p-3 font-mono text-[11px]">
          <span className="font-medium text-on-surface-variant">Net invariant check Σ:</span>
          {invariant === null || invariant === undefined ? (
            <span className="text-on-surface-variant">—</span>
          ) : invariant === 0 ? (
            <span className="font-black text-success-green">{inr(0)} (exact zero)</span>
          ) : (
            <span className="font-black text-error-red">{inr(invariant)} (IMBALANCED)</span>
          )}
        </div>
      </div>
    </Card>
  );
}

function Entries({ entries, error, filter }) {
  // Group postings into transactions so each card shows one money movement.
  const groups = [];
  (entries || []).forEach((e) => {
    const g = groups[groups.length - 1];
    if (g && g.txn_id === e.txn_id) g.rows.push(e);
    else groups.push({ txn_id: e.txn_id, memo: e.memo, ts: e.ts, ref: e.ref, rows: [e] });
  });
  return (
    <Card className="lg:col-span-5" title="Latest ledger entries" subtitle={filter ? `Filtered to order ${filter}` : 'Most recent postings, grouped by transaction'}>
      <ErrorNote error={error} title="Could not load entries" className="mb-2" />
      <div className="rounded-xl border border-outline-variant bg-surface-subtle p-2">
        <div className="grid grid-cols-12 border-b border-outline-variant px-2 py-1.5 text-[11px] font-bold uppercase text-on-surface-variant">
          <span className="col-span-3 sm:col-span-2">Time</span>
          <span className="col-span-6 sm:col-span-7">Memo / account</span>
          <span className="col-span-3 text-right">Amount</span>
        </div>
        {groups.length === 0 ? (
          <div className="py-6 text-center text-body-sm text-on-surface-variant">No entries yet.</div>
        ) : (
          <div className="mt-2 flex max-h-[380px] flex-col gap-2 overflow-y-auto pr-1">
            {groups.map((g) => (
              <div key={g.txn_id} className="grid grid-cols-12 items-center rounded-lg border border-outline-variant bg-white px-2.5 py-2 font-mono text-xs shadow-sm transition-colors hover:border-primary">
                <span className="col-span-3 text-[11px] text-on-surface-variant sm:col-span-2">{time(g.ts)}</span>
                <div className="col-span-6 flex min-w-0 flex-col pr-2 sm:col-span-7">
                  <span className="truncate font-bold text-paytm-navy" title={g.memo}>
                    {g.memo}
                  </span>
                  {g.rows.map((r, i) => (
                    <span key={i} className="truncate text-[10px] text-on-surface-variant">
                      {r.label && r.label !== r.account ? `${r.label} · ` : ''}
                      {r.account}
                    </span>
                  ))}
                </div>
                <div className="col-span-3 flex flex-col items-end">
                  {g.rows.map((r, i) => (
                    <span key={i} className={`tnum ${i === 0 ? 'font-black' : 'text-[10px]'} ${r.amount_paise < 0 ? 'text-rose-600' : 'text-paytm-cyan-dark'}`}>
                      {inr(r.amount_paise, { sign: true })}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

function sevTone(s) {
  const v = String(s || '').toLowerCase();
  if (['high', 'critical', 'block', 'error'].includes(v)) return 'bad';
  if (['medium', 'warn', 'warning', 'flag'].includes(v)) return 'warn';
  return 'neutral';
}

// Advertiser verification queue: the stand-in for Paytm's KYC pipeline until it's connected.
function KycQueue() {
  const q = usePoll(() => api.kycQueue('pending'), 10000, []);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState(null);
  const decide = async (a, action) => {
    let note = null;
    if (action === 'reject') {
      note = window.prompt(`Reason for rejecting ${a.name} (shown to the advertiser):`, 'GSTIN not active / name does not match');
      if (!note) return;
    }
    setBusy(a.id + action);
    setErr(null);
    try {
      await api.kycDecide(a.id, action, note);
      q.reload?.();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy('');
    }
  };
  const list = q.data || [];
  return (
    <Card title="Advertiser verification" actions={<span className="text-xs font-bold text-on-surface-variant">{list.length} pending</span>}>
      <p className="mb-2 text-body-sm text-on-surface-variant">
        Ads go live only after GST verification and a ₹200 deposit. Check the GSTIN on the GST portal (active status, legal name matches), then approve.
      </p>
      <ErrorNote error={q.error || err} title="Verification" className="mb-2" />
      {!list.length ? (
        <div className="py-3 text-center text-xs font-bold text-paytm-navy">No advertisers waiting</div>
      ) : (
        <ul className="space-y-2">
          {list.map((a) => (
            <li key={a.id} className="rounded-lg border border-outline p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-label-lg text-paytm-navy">{a.name}</div>
                  <div className="font-mono text-xs text-on-surface-variant">{a.gstin} · {a.type} · {a.category}</div>
                  <div className="text-xs text-on-surface-variant">Deposit {inr(a.deposit_paise)} of {inr(a.min_deposit_paise)}</div>
                </div>
                <div className="flex gap-1.5">
                  <button type="button" className="btn btn-navy btn-sm" disabled={!!busy} onClick={() => decide(a, 'approve')}>Approve</button>
                  <button type="button" className="btn btn-outline btn-sm" disabled={!!busy} onClick={() => decide(a, 'reject')}>Reject</button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Flags({ flags, error }) {
  return (
    <Card title="Sentinel flags" actions={<span className="flex items-center gap-1.5 text-xs font-bold text-on-surface-variant">{flags ? `${flags.length} recent` : ''}</span>}>
      <p className="-mt-2 mb-3 text-xs text-on-surface-variant">Fraud checks on every payment and ad play</p>
      <ErrorNote error={error} title="Could not load flags" className="mb-2" />
      {!flags?.length ? (
        <div className="flex min-h-[110px] flex-col items-center justify-center gap-2 rounded-xl border border-outline-variant bg-surface-subtle p-4 text-center">
          <Icon name="verified_user" className="text-[32px] text-success-green" />
          <div className="text-xs font-bold text-paytm-navy">No flags raised</div>
          <p className="text-[11px] text-on-surface-variant">Self-payments and other suspicious activity appear here.</p>
        </div>
      ) : (
        <ul className="max-h-[320px] space-y-2 overflow-y-auto pr-1">
          {flags.map((f) => (
            <li key={f.id} className={`rounded-xl border p-2.5 text-xs ${sevTone(f.severity) === 'bad' ? 'border-rose-200 bg-rose-50/60' : sevTone(f.severity) === 'warn' ? 'border-amber-200 bg-amber-50/60' : 'border-outline-variant bg-surface-subtle'}`}>
              <div className="flex flex-wrap items-center justify-between gap-1">
                <b className="text-paytm-navy">{f.rule}</b>
                <span className="flex gap-1">
                  <Pill tone={sevTone(f.severity)}>{f.severity}</Pill>
                  {f.action && <Pill status={f.action} />}
                </span>
              </div>
              <div className="mt-1 break-words text-on-surface">{f.detail}</div>
              <div className="mt-1 font-mono text-[10px] text-on-surface-variant">
                {f.ref} · {time(f.ts)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Devices({ devices, error, now }) {
  return (
    <Card title="Paytm Soundboxes" actions={<span className="font-mono text-xs text-on-surface-variant">{devices ? `${devices.length} total` : ''}</span>}>
      <ErrorNote error={error} title="Could not load devices" className="mb-2" />
      {!devices?.length ? (
        <div className="rounded-xl border border-outline-variant bg-surface-subtle p-4 text-center text-xs text-on-surface-variant">No Soundboxes paired by any merchant yet.</div>
      ) : (
        <div className="flex max-h-[320px] flex-col gap-2 overflow-y-auto pr-1">
          {devices.map((d) => (
            <div key={d.id} className="flex items-center justify-between gap-2 rounded-xl border border-outline-variant bg-surface-subtle p-3">
              <div className="flex min-w-0 items-start gap-2.5">
                <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${d.online ? 'bg-success-green' : 'bg-rose-500'}`} title={d.online ? 'Online' : 'Offline'} />
                <div className="min-w-0">
                  <div className="truncate text-xs font-bold text-paytm-navy">{d.name || d.id}</div>
                  <div className="truncate font-mono text-[10px] text-on-surface-variant">
                    {d.id} · {d.merchant_name || d.merchant_id}
                    {d.fw ? ` · fw ${d.fw}` : ''}
                  </div>
                </div>
              </div>
              <div className="shrink-0 text-right font-mono text-[11px]">
                <div className={`font-semibold ${d.online ? 'text-success-green' : 'text-on-surface-variant'}`}>{d.online ? 'online' : 'offline'}</div>
                <div className="text-[10px] text-on-surface-variant">{ago(d.last_seen, now)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function summarize(msg) {
  if (!msg || typeof msg !== 'object') return '';
  const skip = new Set(['type', 'ts']);
  return Object.entries(msg)
    .filter(([k, v]) => !skip.has(k) && v !== null && typeof v !== 'object')
    .slice(0, 4)
    .map(([k, v]) => `${k}=${v}`)
    .join(' · ');
}

function LiveEvents({ events, wsState }) {
  return (
    <Card>
      <div className="mb-2 flex items-center justify-between font-mono text-xs">
        <span className="font-bold text-paytm-navy">Live events</span>
        <span className={`font-bold ${wsState === 'open' ? 'text-paytm-cyan-dark' : 'text-on-surface-variant'}`}>/ws/admin · {wsState}</span>
      </div>
      {!events.length ? (
        <div className="flex h-16 items-center justify-center rounded-xl border border-outline-variant bg-surface-subtle p-2 font-mono text-xs text-on-surface-variant">
          <span className="flex items-center gap-2">
            {wsState === 'open' && <span className="h-2 w-2 animate-ping rounded-full bg-paytm-cyan" />}
            {wsState === 'open' ? 'Waiting for events…' : 'Not connected; retrying.'}
          </span>
        </div>
      ) : (
        <ul className="max-h-[260px] space-y-1 overflow-y-auto rounded-xl border border-outline-variant bg-surface-subtle p-2 font-mono text-[11px]">
          {events.map((e, i) => (
            <li key={`${e.t}-${i}`} className="flex min-w-0 gap-2">
              <span className="shrink-0 text-on-surface-variant">{time(e.t)}</span>
              <span className="shrink-0 font-bold text-paytm-navy">{e.msg.type}</span>
              <span className="truncate text-on-surface-variant">{summarize(e.msg)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SystemPanel({ sys, error, now }) {
  const ai = sys?.ai || {};
  const models = ai.models && typeof ai.models === 'object' ? Object.entries(ai.models) : [];
  return (
    <Card id="system" className="scroll-mt-24" icon="monitor_heart" title="System status" subtitle="Payment provider, AI health, devices and database">
      <ErrorNote error={error} title="Could not load system status" className="mb-3" />
      {!sys ? (
        !error && <div className="text-body-sm text-on-surface-variant">Loading…</div>
      ) : (
        <div className="grid gap-3 md:grid-cols-3">
          <div className="card-inset space-y-1.5 p-3 text-body-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-label-lg text-paytm-navy">Payment provider</span>
              <Pill tone={sys.provider?.ok ? 'good' : 'bad'} dot>
                {sys.provider?.ok ? 'ok' : 'error'}
              </Pill>
            </div>
            <div>
              {titleCase(sys.provider?.name)} · <b>{sys.provider?.mode}</b> mode
            </div>
            {sys.provider?.detail && <div className="break-words text-on-surface-variant">{sys.provider.detail}</div>}
            {sys.base_url && <div className="break-all font-mono text-[11px] text-on-surface-variant">base_url {sys.base_url}</div>}
          </div>
          <div className="card-inset space-y-1.5 p-3 text-body-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-label-lg text-paytm-navy">AI (Gemini)</span>
              <Pill tone={!ai.configured ? 'warn' : ai.last_error && (!ai.last_ok_at || new Date(ai.last_error_at) > new Date(ai.last_ok_at)) ? 'bad' : 'good'} dot>
                {!ai.configured ? 'not configured' : 'configured'}
              </Pill>
            </div>
            <div className="font-mono text-[11px]">
              text {ai.text_model || '—'} · tts {ai.tts_model || '—'}
            </div>
            <div>
              {num(ai.calls ?? 0)} calls · <span className={ai.failures ? 'font-semibold text-amber-700' : ''}>{num(ai.failures ?? 0)} failures</span>
            </div>
            <div className="text-on-surface-variant">Last success: {ai.last_ok_at ? ago(ai.last_ok_at, now) : 'never'}</div>
            {ai.last_error && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-2 text-rose-800">
                <b>Last error</b> {ai.last_error_at ? `(${ago(ai.last_error_at, now)})` : ''}: <span className="break-words">{ai.last_error}</span>
              </div>
            )}
            {models.length > 0 && (
              <ul className="space-y-0.5 border-t border-outline-variant pt-1.5">
                {models.map(([id, st]) => (
                  <li key={id} className="flex items-start justify-between gap-2 font-mono text-[11px]">
                    <span className="truncate">{id}</span>
                    <span className={`break-words text-right ${st === 'ok' ? 'font-bold text-success-green' : 'text-error-red'}`}>{String(st)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="card-inset space-y-1.5 p-3 text-body-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-label-lg text-paytm-navy">Devices & database</span>
              <Pill tone={sys.db === 'ok' ? 'good' : 'bad'} dot>
                db {sys.db === 'ok' ? 'ok' : 'error'}
              </Pill>
            </div>
            <div>
              {num(sys.devices?.online ?? 0)} of {num(sys.devices?.total ?? 0)} Soundboxes online
            </div>
            {sys.db !== 'ok' && <div className="break-words text-error-red">{sys.db}</div>}
          </div>
        </div>
      )}
    </Card>
  );
}

function Accounts({ merchants, advertisers, now }) {
  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
      <Card icon="storefront" title="Merchants" subtitle={merchants.data ? `${merchants.data.length} registered` : undefined}>
        <ErrorNote error={merchants.error} title="Could not load merchants" className="mb-2" />
        {!merchants.data?.length ? (
          <Empty icon="storefront" title="No merchants yet">Merchants appear here when they sign up.</Empty>
        ) : (
          <div className="max-h-[360px] overflow-auto rounded-xl border border-outline">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Merchant</th>
                  <th>GSTIN</th>
                  <th>Soundboxes</th>
                  <th className="text-right">Ad earnings</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {merchants.data.map((m) => (
                  <tr key={m.id}>
                    <td className="min-w-[160px]">
                      <div className="font-semibold">{m.name}</div>
                      <div className="font-mono text-[10px] text-on-surface-variant">
                        {m.id} · {titleCase(m.category)}
                      </div>
                    </td>
                    <td className="font-mono text-[11px]">{m.gstin}</td>
                    <td>{m.device_ids?.length ?? 0}</td>
                    <td className="text-right font-mono">{inr(m.stats?.earnings_lifetime_paise ?? 0)}</td>
                    <td className="whitespace-nowrap text-on-surface-variant">{m.created_at ? ago(m.created_at, now) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card icon="campaign" title="Advertisers" subtitle={advertisers.data ? `${advertisers.data.length} registered` : undefined}>
        <ErrorNote error={advertisers.error} title="Could not load advertisers" className="mb-2" />
        {!advertisers.data?.length ? (
          <Empty icon="campaign" title="No advertisers yet">Advertisers appear here when they sign up.</Empty>
        ) : (
          <div className="max-h-[360px] overflow-auto rounded-xl border border-outline">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Advertiser</th>
                  <th>Type</th>
                  <th className="text-right">Balance</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                {advertisers.data.map((a) => (
                  <tr key={a.id}>
                    <td className="min-w-[160px]">
                      <div className="font-semibold">{a.name}</div>
                      <div className="font-mono text-[10px] text-on-surface-variant">
                        {a.id} · {titleCase(a.category)}
                      </div>
                    </td>
                    <td>{a.type === 'brand' ? 'Brand' : 'Local'}</td>
                    <td className="text-right font-mono">{inr(a.balance_paise)}</td>
                    <td className="whitespace-nowrap text-on-surface-variant">{a.created_at ? ago(a.created_at, now) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Guarantee({ s }) {
  const settled = s.settled_orders ?? 0;
  const gross = s.gross_paise ?? 0;
  const toMerchants = (s.merchant_earnings_paise ?? 0) + (s.rental_paid_by_ads_paise ?? 0);
  return (
    <div className="flex flex-col items-center justify-between gap-4 rounded-xl border border-outline bg-surface-high p-4 shadow-sm md:flex-row">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-outline bg-white shadow-sm">
          <Icon name="verified" className="text-[24px] text-paytm-cyan" />
        </div>
        <div>
          <div className="text-sm font-extrabold text-paytm-navy">
            {settled === 0
              ? 'No paid bills yet'
              : `Merchants received the full ${inr(gross)} across ${num(settled)} paid bill${settled === 1 ? '' : 's'}`}
          </div>
          <div className="text-xs text-on-surface-variant">
            {settled === 0
              ? 'Once bills are paid, this shows what counter ads earned merchants.'
              : `Counter ads added ${inr(toMerchants)} for merchants: ${inr(s.rental_paid_by_ads_paise ?? 0)} towards Soundbox rental and ${inr(s.merchant_earnings_paise ?? 0)} as earnings.`}
          </div>
        </div>
      </div>
      {settled > 0 && (
        <div className="shrink-0 rounded-lg border border-paytm-cyan/30 bg-white px-3.5 py-1.5 font-mono text-xs font-bold text-paytm-navy shadow-sm">
          {s.play_verification_pct != null ? `${pct(s.play_verification_pct)} of ads verified played` : 'No ad plays yet'}
        </div>
      )}
    </div>
  );
}

export default function Admin() {
  const now = useNow(5000);
  const [orderFilter, setOrderFilter] = useState('');
  const [compressed, setCompressed] = useState(true);
  const [view, setView] = useState('chart');
  const [events, setEvents] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);

  const stats = usePoll(() => api.adminStats(), REFRESH_MS, []);
  const flows = usePoll(() => api.flows(orderFilter || undefined), REFRESH_MS * 2, [orderFilter]);
  const balances = usePoll(() => api.balances(), REFRESH_MS * 2, []);
  const entries = usePoll(() => api.entries({ ref: orderFilter ? `order:${orderFilter}` : undefined, limit: 60 }), REFRESH_MS * 2, [orderFilter]);
  const flags = usePoll(() => api.flags(30), REFRESH_MS * 2, []);
  const devices = usePoll(() => api.devices(), REFRESH_MS * 2, []);
  const orders = usePoll(() => api.orders({ limit: 50 }), REFRESH_MS * 3, []);
  const system = usePoll(() => api.systemStatus(), 15000, []);
  const merchants = usePoll(() => api.merchants(), 30000, []);
  const advertisers = usePoll(() => api.advertisers(), 30000, []);

  useEffect(() => {
    if (stats.data) setLastUpdate(Date.now());
  }, [stats.data]);

  const sysLoaded = !!system.data;
  useEffect(() => {
    if (sysLoaded && window.location.hash === '#system') document.getElementById('system')?.scrollIntoView({ behavior: 'smooth' });
  }, [sysLoaded]);

  const live = [stats, flows, balances, entries, flags, devices, orders];
  const liveRef = useRef(live);
  liveRef.current = live;
  const debounce = useRef(null);
  const refreshAll = useCallback(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => liveRef.current.forEach((p) => p.reload()), 250);
  }, []);

  const wsState = useSocket('/ws/admin', (msg) => {
    setEvents((ev) => [{ t: Date.now(), msg }, ...ev].slice(0, 40));
    refreshAll();
  });

  const s = stats.data || {};
  const orderList = orders.data || [];

  return (
    <div className="shell space-y-6 py-6">
      <PageHead
        crumbs={['Admin', 'Money flow & ledger']}
        title="Every rupee, live"
        chips={
          <div className="flex items-center gap-2 rounded-full border border-outline bg-white px-3 py-1 shadow-sm">
            <span className="relative flex h-2 w-2">
              {wsState === 'open' && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success-green opacity-75" />}
              <span className={`relative inline-flex h-2 w-2 rounded-full ${wsState === 'open' ? 'bg-success-green' : wsState === 'connecting' ? 'bg-alert-amber' : 'bg-error-red'}`} />
            </span>
            <span className={`text-xs font-semibold ${wsState === 'open' ? 'text-success-green' : 'text-on-surface-variant'}`}>
              {wsState === 'open' ? 'Live events connected' : wsState === 'connecting' ? 'Connecting…' : 'Live events offline (polling)'}
            </span>
            {lastUpdate && (
              <>
                <span className="text-[10px] text-outline">·</span>
                <span className="font-mono text-xs text-on-surface-variant">updated {ago(lastUpdate, now)}</span>
              </>
            )}
          </div>
        }
      />
      <AiWarning what="Bill reading and ad creation" />
      <ErrorNote error={stats.error} title="Could not load stats" />

      <Kpis s={s} />

      <div className="flex flex-col gap-4 rounded-2xl border border-outline bg-white p-4 shadow-sm sm:p-5">
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-outline bg-surface-high">
              <Icon name="account_tree" className="text-[22px] text-paytm-navy" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-bold text-paytm-navy">Money flow</h2>
                {orderFilter && <span className="rounded-full border border-outline bg-surface-high px-2.5 py-0.5 font-mono text-xs font-semibold text-paytm-navy">{orderFilter}</span>}
              </div>
              <p className="text-xs text-on-surface-variant">Customer payments, advertiser top-ups and ad money to merchants, from the double-entry ledger</p>
            </div>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            <select className="input input-sm min-w-0 flex-1 bg-surface sm:w-64 sm:flex-none" value={orderFilter} onChange={(e) => setOrderFilter(e.target.value)} aria-label="Filter money flow by order">
              <option value="">All orders{s.gross_paise ? ` (${inr(s.gross_paise)})` : ''}</option>
              {orderList.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.id} · {inr(o.total_paise, { decimals: 0 })} · {o.status}
                </option>
              ))}
            </select>
            <Segmented
              value={view}
              onChange={setView}
              options={[
                { value: 'chart', label: 'Chart' },
                { value: 'table', label: 'Table' },
              ]}
            />
          </div>
        </div>
        <ErrorNote error={flows.error} title="Could not load flows" />
        {view === 'chart' ? <Sankey data={flows.data} compressed={compressed} /> : <FlowTable links={flows.data?.links} nodes={flows.data?.nodes} />}
        {view === 'chart' && flows.data?.links?.length > 0 && (
          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-outline-variant pt-2 text-xs text-on-surface-variant">
            {compressed && <span className="hidden font-mono text-[11px] md:inline">Band widths compressed (√) so small flows stay visible; labels show exact amounts</span>}
            <label className="flex cursor-pointer select-none items-center gap-2 text-xs font-semibold text-paytm-navy">
              <input type="checkbox" className="h-3.5 w-3.5" checked={!compressed} onChange={(e) => setCompressed(!e.target.checked)} />
              True-scale band widths
            </label>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12">
        <Balances balances={balances.data} invariant={s.ledger_invariant_paise} error={balances.error} />
        <Entries entries={entries.data} error={entries.error} filter={orderFilter} />
        <div className="flex min-w-0 flex-col gap-6 lg:col-span-3">
          <KycQueue />
          <Flags flags={flags.data} error={flags.error} />
          <Devices devices={devices.data} error={devices.error} now={now} />
          <LiveEvents events={events} wsState={wsState} />
        </div>
      </div>

      <SystemPanel sys={system.data} error={system.error} now={now} />
      <Accounts merchants={merchants} advertisers={advertisers} now={now} />
      <Guarantee s={s} />
    </div>
  );
}
