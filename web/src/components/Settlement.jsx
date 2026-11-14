import { inr } from '../format.js';
import { Icon, Pill } from './ui.jsx';

const KIND = { audio: 'ad heard while paying', tag: 'sponsor line (busy hour)' };

/** What this bill's counter ad earned the merchant: full payment received, then where the ad money went. */
export default function Settlement({ order }) {
  const s = order.settlement || {};
  const pending = s.status === 'pending_ack';
  const ads = (s.sponsors || []).filter((x) => x.kind === 'audio' || x.kind === 'tag');
  const adRevenue = s.ad_revenue_paise ?? 0;
  const rows = [
    ['Paytm share', s.platform_paise ?? 0, 'bg-slate-400'],
    ['Paid towards your Soundbox rental', s.rental_paid_paise ?? 0, 'bg-paytm-cyan'],
    ['Your ad earnings', s.earnings_paise ?? 0, 'bg-success-green'],
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border border-paytm-cyan/20 bg-gradient-to-br from-paytm-cyan-light/70 to-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">You received</div>
          <div className="tnum text-currency-display text-paytm-navy">{inr(s.merchant_receives_paise ?? order.total_paise)}</div>
          <div className="text-body-sm text-on-surface-variant">The full bill, paid with one QR.</div>
        </div>
        <div className="sm:text-right">
          <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Ad earnings from this bill</div>
          <div className={`tnum text-headline-lg ${s.earnings_paise > 0 ? 'text-success-green' : 'text-paytm-navy'}`}>
            {pending ? '…' : inr(s.earnings_paise ?? 0)}
          </div>
          <Pill status={s.status} dot>
            {pending ? 'waiting for the Soundbox to confirm the ad played' : 'settled'}
          </Pill>
        </div>
      </div>

      <div className="card-inset space-y-2 p-3">
        <h4 className="text-label-lg text-paytm-navy">Ad played at your counter</h4>
        {ads.length === 0 ? (
          <p className="text-body-sm text-on-surface-variant">No ad played for this bill (no eligible advertiser nearby, or the Soundbox was offline).</p>
        ) : (
          <ul className="space-y-1 text-body-sm">
            {ads.map((a, i) => (
              <li key={(a.advertiser_id || a.name) + i} className="flex flex-wrap items-center gap-2">
                <Icon name="campaign" className="text-[16px] text-paytm-cyan-dark" />
                <span className="min-w-0 flex-1 truncate">
                  {a.name} <span className="text-on-surface-variant">{KIND[a.kind] || a.kind}</span>
                </span>
                <b className="tnum">{inr(a.amount_paise)}</b>
                <Pill status={a.status}>
                  {a.status === 'released' ? `not charged${a.release_reason ? ` (${a.release_reason.replace(/_/g, ' ')})` : ''}` : a.status}
                </Pill>
              </li>
            ))}
          </ul>
        )}
      </div>

      {!pending && adRevenue > 0 && (
        <div className="card-inset space-y-2 p-3">
          <div className="flex justify-between text-body-sm">
            <h4 className="text-label-lg text-paytm-navy">Where the ad money went</h4>
            <b className="tnum text-paytm-navy">{inr(adRevenue)}</b>
          </div>
          <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
            {rows.map(([label, v, cls]) => (v > 0 ? <div key={label} className={cls} style={{ flexGrow: v }} title={`${label}: ${inr(v)}`} /> : null))}
          </div>
          <ul className="space-y-1 text-body-sm">
            {rows.map(([label, v, cls]) => (
              <li key={label} className="flex items-center gap-2">
                <span className={`h-2.5 w-2.5 rounded-sm ${cls}`} />
                <span className="flex-1">{label}</span>
                <b className="tnum">{inr(v)}</b>
              </li>
            ))}
          </ul>
          {s.rental_due_after_paise > 0 && (
            <p className="text-body-sm text-on-surface-variant">
              {inr(s.rental_due_after_paise)} of this month's Soundbox rental is still to be paid by ads. After that, ad money is all earnings.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
