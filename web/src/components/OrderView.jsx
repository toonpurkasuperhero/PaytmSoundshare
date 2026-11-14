import { useState } from 'react';
import { api, qrSrc, absUrl } from '../api.js';
import { codeLabel, inr, railLabel, RAILS, reasonText, secondsUntil, supplyOf, time } from '../format.js';
import { usePoll, useNow } from '../hooks.js';
import { useConfig } from '../session.jsx';
import { Card, ErrorNote, Icon, Pill, SourceBadge, Spinner, TestModeBadge } from './ui.jsx';
import Settlement from './Settlement.jsx';

const TERMINAL = new Set(['settled', 'failed', 'cancelled']);
const isDone = (o) => !!o && (TERMINAL.has(o.status) || o.settlement?.status === 'settled');

function Countdown({ ts, now }) {
  const s = secondsUntil(ts, now);
  if (s === null) return null;
  if (s <= 0) return <span className="text-body-sm text-error-red">QR expired</span>;
  const m = Math.floor(s / 60);
  return (
    <span className={`tnum font-mono text-body-sm ${s < 60 ? 'font-bold text-amber-700' : 'text-on-surface-variant'}`}>
      expires in {m}:{String(s % 60).padStart(2, '0')}
    </span>
  );
}

function LegCard({ leg, isMock, rails, onPaid, current, now }) {
  const [rail, setRail] = useState('UPI_BANK');
  const [payer, setPayer] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const payable = leg.status === 'active';
  const qr = payable && (leg.qr_data ? qrSrc(leg.qr_data, 6) : leg.qr_image_url ? absUrl(leg.qr_image_url) : null);
  const services = supplyOf(leg) === 'services';
  const pay = async () => {
    setBusy(true);
    setErr(null);
    try {
      onPaid(await api.mockPay(leg.id, rail, payer.trim() || undefined));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={`flex min-w-0 flex-col gap-2 rounded-xl border p-3 ${current ? 'border-primary bg-white shadow-focus' : leg.status === 'paid' ? 'border-emerald-200 bg-emerald-50/50' : 'border-outline-variant bg-surface-subtle'}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">
          Payment QR
        </span>
        <Pill status={leg.status} dot />
      </div>
      <div className="tnum text-headline-md font-extrabold text-paytm-navy">{inr(leg.amount_paise)}</div>
      {qr && (
        <div className="flex flex-col items-center gap-1 rounded-lg border border-outline-variant bg-white p-2">
          <img src={qr} alt="UPI QR code for this bill" width="168" height="168" className="h-[168px] w-[168px]" />
          <Countdown ts={leg.expires_at} now={now} />
          {leg.checkout_url && (
            <a href={leg.checkout_url} target="_blank" rel="noreferrer" className="text-body-sm font-semibold text-paytm-navy underline">
              Open checkout
            </a>
          )}
        </div>
      )}
      {leg.status === 'paid' && (
        <div className="flex items-start gap-2 text-body-sm text-emerald-800">
          <Icon name="check_circle" fill className="text-[20px] text-success-green" />
          <div>
            <div className="font-semibold">Paid via {railLabel(leg.rail)}</div>
            {leg.paid_at && <div className="text-on-surface-variant">{time(leg.paid_at)}</div>}
          </div>
        </div>
      )}
      {isMock && payable && (
        <div className="space-y-1.5 rounded-lg border border-amber-200 bg-amber-50 p-2">
          <TestModeBadge />
          <div className="flex flex-col gap-1.5">
            <select className="input input-sm min-w-0 flex-1" value={rail} onChange={(e) => setRail(e.target.value)} aria-label="Payment rail to simulate">
              {rails.map((r) => (
                <option key={r} value={r}>
                  {railLabel(r)}
                </option>
              ))}
            </select>
            <input
              className="input input-sm min-w-0 flex-1 font-mono"
              value={payer}
              onChange={(e) => setPayer(e.target.value)}
              placeholder="Payer VPA (optional)"
              aria-label="Payer VPA, optional; used to test self-dealing detection"
              title="Optional. Set it to the merchant's own VPA to see the Sentinel's self-dealing check."
            />
            <button type="button" className="btn btn-navy btn-sm" disabled={busy} onClick={pay}>
              {busy ? <Spinner /> : <Icon name="bolt" className="text-[15px] text-paytm-cyan" />}
              Simulate payment
            </button>
          </div>
        </div>
      )}
      <ErrorNote error={err} title="Payment failed" />
    </div>
  );
}

/** Live order: polls GET /api/orders/{id} every 1.5 s until settled / failed / cancelled. */
export default function OrderView({ orderId, onClose, readOnly = false }) {
  const { config, isMock } = useConfig();
  const now = useNow(1000);
  const [done, setDone] = useState(false);
  const { data: order, error, setData, reload } = usePoll(
    async () => {
      const o = await api.order(orderId);
      setDone(isDone(o));
      return o;
    },
    done ? 0 : 1500,
    [orderId, done],
  );
  const [busy, setBusy] = useState(false);
  const [actErr, setActErr] = useState(null);

  const apply = (o) => {
    if (o && o.id) {
      setData(o);
      setDone(isDone(o));
    } else reload();
  };
  const act = async (fn) => {
    setBusy(true);
    setActErr(null);
    try {
      apply(await fn());
    } catch (e) {
      setActErr(e);
    } finally {
      setBusy(false);
    }
  };

  if (!order) {
    return (
      <Card title={`Order ${orderId}`} icon="receipt_long">
        {error ? <ErrorNote error={error} title="Could not load order" /> : (
          <div className="flex items-center gap-2 text-on-surface-variant">
            <Spinner /> Loading order…
          </div>
        )}
      </Card>
    );
  }

  const rails = config?.rails?.length ? config.rails : RAILS;
  const legs = order.legs || [];
  const currentLeg = legs.find((l) => l.status === 'active');
  const paid = legs.filter((l) => l.status === 'paid').reduce((s, l) => s + (l.amount_paise || 0), 0);
  const cancellable = !readOnly && ['created', 'awaiting_payment', 'partially_paid'].includes(order.status);

  return (
    <div className="space-y-4">
      <Card
        icon="receipt_long"
        title={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{order.id}</span>
            <Pill status={order.status} dot />
          </span>
        }
        subtitle={`Created ${time(order.created_at)} · Soundbox ${order.device_id || '—'}`}
        actions={
          <>
            {!done && !readOnly && (
              <button type="button" className="btn btn-outline btn-sm" disabled={busy} onClick={() => act(() => api.refreshOrder(order.id))} title="Ask the payment provider for the latest status">
                <Icon name="sync" className="text-[16px]" />
                Check status
              </button>
            )}
            {cancellable && (
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={busy}
                onClick={() => window.confirm('Cancel this order? Unpaid QR codes stop working.') && act(() => api.cancelOrder(order.id))}
              >
                Cancel
              </button>
            )}
            {onClose && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
                <Icon name="add" className="text-[16px]" />
                New bill
              </button>
            )}
          </>
        }
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <div className="text-label-sm text-on-surface-variant">Bill total</div>
            <div className="tnum text-headline-md font-extrabold text-paytm-navy">{inr(order.total_paise)}</div>
          </div>
          <div>
            <div className="text-label-sm text-on-surface-variant">Collected</div>
            <div className="tnum text-headline-md font-extrabold text-success-green">{inr(paid)}</div>
          </div>
        </div>
        <details className="mt-3 rounded-lg border border-outline-variant">
          <summary className="cursor-pointer px-3 py-2 text-label-md text-paytm-navy">
            {order.items?.length || 0} item{order.items?.length === 1 ? '' : 's'}
          </summary>
          <div className="overflow-x-auto border-t border-outline-variant">
            <table className="tbl">
              <tbody>
                {(order.items || []).map((it, i) => (
                  <tr key={it.id ?? i}>
                    <td className="min-w-[140px]">
                      {it.name}
                      {it.qty > 1 && <span className="text-on-surface-variant"> × {it.qty}</span>}
                    </td>
                    <td>
                      <div className="flex flex-wrap items-center gap-1">
                        {codeLabel(it) && <span className={`code-chip ${supplyOf(it) === 'services' ? 'code-services' : 'code-goods'}`}>{codeLabel(it)}</span>}
                      </div>
                    </td>
                    <td className="text-on-surface-variant">{it.brand || ''}</td>
                    <td className="text-right font-mono">{inr(it.amount_paise ?? it.unit_price * it.qty)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        <div className={`mt-3 grid gap-3 ${legs.length >= 3 ? 'sm:grid-cols-2 2xl:grid-cols-3' : legs.length === 2 ? 'sm:grid-cols-2' : ''}`}>
          {legs.map((l) => (
            <LegCard key={l.id} leg={l} isMock={isMock && !readOnly} rails={rails} now={now} current={currentLeg?.id === l.id} onPaid={apply} />
          ))}
        </div>
        {isMock && !done && !readOnly && (
          <p className="mt-2 text-body-sm text-on-surface-variant">
            Test mode: the mock provider moves no real money. Use "Simulate payment", or pay from a paired Soundbox simulator.
          </p>
        )}
        <ErrorNote error={actErr} className="mt-3" />
      </Card>

      {order.settlement && (
        <Card title="Payment & ad earnings" icon="account_balance_wallet" subtitle="Full payment received, plus what the counter ad earned you">
          <Settlement order={order} />
        </Card>
      )}
    </div>
  );
}
