import { inr, pct, railLabel } from '../format.js';
import { Icon, Pill } from './ui.jsx';

const SPONSOR_COLORS = ['#E53935', '#0F4A8A', '#F5A623', '#7C3AED', '#0EA5E9', '#DB2777', '#65A30D', '#64748B'];

function Ring({ value }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const r = 42;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 100 100" className="h-28 w-28" role="img" aria-label={`Fee covered ${pct(v)}`}>
      <circle cx="50" cy="50" r={r} fill="none" stroke="#EBF2FA" strokeWidth="10" />
      {v > 0 && <circle cx="50" cy="50" r={r} fill="none" stroke="#00B06F" strokeWidth="10" strokeLinecap="round" strokeDasharray={`${(v / 100) * c} ${c}`} transform="rotate(-90 50 50)" />}
      <text x="50" y="50" textAnchor="middle" fontSize="18" fontWeight="800" fill="#002970">
        {v >= 99.95 ? '100' : v.toFixed(1)}%
      </text>
      <text x="50" y="65" textAnchor="middle" fontSize="9" fontWeight="600" fill="#4A628A">
        fee covered
      </text>
    </svg>
  );
}

function MdrBar({ label, value, max, tone }) {
  const w = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="grid grid-cols-[84px_1fr_auto] items-center gap-3 text-body-sm">
      <span className="text-on-surface-variant">{label}</span>
      <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${tone === 'brand' ? 'bg-gradient-to-r from-paytm-cyan to-paytm-navy' : 'bg-slate-300'}`} style={{ width: `${w}%` }} />
      </div>
      <span className="tnum font-mono font-bold text-paytm-navy">{inr(value)}</span>
    </div>
  );
}

function Tile({ k, label, value, sub, tone }) {
  const tones = {
    a: 'border-paytm-cyan/40 bg-paytm-cyan-light',
    b: 'border-orange-200 bg-orange-50',
    c: 'border-outline bg-surface-high',
    d: 'border-rose-200 bg-rose-50',
  };
  return (
    <div className={`relative min-w-0 rounded-xl border p-3 ${tones[tone]}`}>
      <span className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-md bg-white text-[10px] font-black text-paytm-navy">{k}</span>
      <div className="pr-6 text-label-sm uppercase tracking-wide text-on-surface-variant">{label}</div>
      <div className="tnum mt-1 text-headline-sm font-extrabold text-paytm-navy">{value}</div>
      <div className="mt-0.5 break-words text-body-sm text-on-surface-variant">{sub}</div>
    </div>
  );
}

/** Settlement breakdown for one order: who received what, and who paid the fee. */
export default function Settlement({ order }) {
  const s = order?.settlement;
  if (!s) return null;
  const total = order.total_paise ?? 0;
  const mdr = s.mdr_paise ?? 0;
  const unsplit = s.mdr_unsplit_paise ?? mdr;
  const saved = s.saved_by_factorization_paise ?? Math.max(0, unsplit - mdr);
  const liquidity = s.ad_liquidity_paise ?? (s.sponsors || []).reduce((a, x) => a + (x.amount_paise || 0), 0);
  const covered = s.covered_paise ?? 0;
  const uncovered = Math.max(0, mdr - covered);
  const coverage = s.coverage_pct ?? (mdr > 0 ? (covered / mdr) * 100 : 100);
  const receives = s.merchant_receives_paise ?? total - uncovered;
  const acquirer = s.acquirer_paise ?? mdr;
  const platform = s.platform_paise ?? Math.max(0, liquidity - covered);
  const sponsors = [...(s.sponsors || [])].sort((a, b) => (b.amount_paise || 0) - (a.amount_paise || 0));
  const receivesPct = total > 0 ? (receives / total) * 100 : 100;
  const fundMax = Math.max(liquidity, mdr, 1);
  const paidLegs = (order.legs || []).filter((l) => l.mdr_paise !== null && l.mdr_paise !== undefined);

  return (
    <div className="space-y-4">
      <div className="flex flex-col items-center gap-4 rounded-xl border border-paytm-cyan/20 bg-gradient-to-br from-paytm-cyan-light/70 to-slate-50 p-4 sm:flex-row sm:justify-between">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Merchant receives</div>
          <div className="tnum text-currency-display text-paytm-navy">{inr(receives)}</div>
          <div className="text-body-sm text-on-surface-variant">
            {receivesPct >= 99.995 ? (
              <>
                <b className="text-success-green">100%</b> of the {inr(total)} bill · zero fee to the merchant
              </>
            ) : (
              <>
                {pct(receivesPct, 2)} of the {inr(total)} bill · {inr(uncovered)} of the fee was not covered
              </>
            )}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Pill status={s.status} dot>
              {s.status === 'pending_ack' ? 'awaiting play_ack' : String(s.status || '').replace(/_/g, ' ')}
            </Pill>
            {s.status === 'pending_ack' && <span className="text-body-sm text-on-surface-variant">Sponsors commit once the Soundbox confirms the ad played.</span>}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-center">
          <Ring value={coverage} />
          <div className="tnum text-body-sm text-on-surface-variant">
            {inr(covered)} of {inr(mdr)} fee
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="card-inset space-y-2.5 p-3">
          <h4 className="text-label-lg text-paytm-navy">Payment fee (MDR incl. GST)</h4>
          <MdrBar label="Single QR" value={unsplit} max={Math.max(unsplit, mdr)} />
          <MdrBar label="With split" value={mdr} max={Math.max(unsplit, mdr)} tone="brand" />
          {saved > 0 ? (
            <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-2 text-body-sm text-emerald-800">
              <Icon name="trending_down" className="text-[18px]" />
              <div>
                <b>{inr(saved)} saved by the GST split.</b> The sponsor pool needed that much less for this sale.
              </div>
            </div>
          ) : (
            <div className="text-body-sm text-on-surface-variant">No split saving on this bill (single leg, or no rate benefit).</div>
          )}
        </div>

        <div className="card-inset space-y-2 p-3">
          <h4 className="text-label-lg text-paytm-navy">Who paid the fee</h4>
          <div className="flex justify-between text-body-sm text-on-surface-variant">
            <span>Ad liquidity</span>
            <b className="tnum text-paytm-navy">{inr(liquidity)}</b>
          </div>
          <div className="flex h-3 overflow-hidden rounded-full bg-slate-100" style={{ width: `${(liquidity / fundMax) * 100}%`, minWidth: liquidity > 0 ? 8 : 0 }}>
            {sponsors.map((sp, i) => (
              <div key={(sp.advertiser_id || sp.name) + i} style={{ flexGrow: Math.max(sp.amount_paise || 0, 1), background: SPONSOR_COLORS[i % SPONSOR_COLORS.length] }} title={`${sp.name}: ${inr(sp.amount_paise)}`} />
            ))}
          </div>
          <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
            <div className="bg-success-green" style={{ flexGrow: Math.max(covered, 1) }} title={`Covers MDR ${inr(covered)}`} />
            {platform > 0 && <div className="bg-tertiary" style={{ flexGrow: platform }} title={`Platform spread ${inr(platform)}`} />}
            {uncovered > 0 && <div className="bg-slate-300" style={{ flexGrow: uncovered }} title={`Not covered ${inr(uncovered)}`} />}
          </div>
          <ul className="space-y-1 text-body-sm">
            {sponsors.length === 0 && <li className="text-on-surface-variant">No sponsor matched this sale.</li>}
            {sponsors.map((sp, i) => (
              <li key={(sp.advertiser_id || sp.name) + i} className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: SPONSOR_COLORS[i % SPONSOR_COLORS.length] }} />
                <span className="min-w-0 flex-1 truncate">
                  {sp.name} <span className="text-on-surface-variant">{sp.kind === 'subvention' ? 'brand subvention' : sp.kind === 'audio' ? 'ad heard while paying' : sp.kind === 'tag' ? 'sponsor tag (busy hour)' : sp.kind}</span>
                </span>
                <b className="tnum">{inr(sp.amount_paise)}</b>
                {sp.status && <Pill status={sp.status} />}
              </li>
            ))}
            <li className="flex items-center gap-2 border-t border-outline-variant pt-1">
              <span className="h-2.5 w-2.5 rounded-sm bg-success-green" />
              <span className="flex-1">This sale's ads cover the MDR</span>
              <b className="tnum">{inr(s.covered_by_ads_paise ?? covered)}</b>
            </li>
            {(s.shared_drawn_paise ?? 0) > 0 && (
              <li className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm bg-emerald-300" />
                <span className="flex-1">Covered by the SoundShare pool</span>
                <b className="tnum">{inr(s.shared_drawn_paise)}</b>
              </li>
            )}
            {(s.rental_paid_paise ?? 0) > 0 && (
              <li className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm bg-paytm-navy" />
                <span className="flex-1">Paid towards your Soundbox rental</span>
                <b className="tnum">{inr(s.rental_paid_paise)}</b>
              </li>
            )}
            {(s.shared_contributed_paise ?? 0) > 0 && (
              <li className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm bg-paytm-cyan" />
                <span className="flex-1">Shared with the SoundShare pool</span>
                <b className="tnum">{inr(s.shared_contributed_paise)}</b>
              </li>
            )}
            <li className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-sm bg-tertiary" />
              <span className="flex-1">Platform spread</span>
              <b className="tnum">{inr(platform)}</b>
            </li>
            {uncovered > 0 && (
              <li className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm bg-slate-300" />
                <span className="flex-1">Not covered (merchant bears)</span>
                <b className="tnum">{inr(uncovered)}</b>
              </li>
            )}
          </ul>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-2">
        <Tile k="A" tone="a" label="Merchant receives" value={inr(receives)} sub={`Paytm settles ${inr(total - mdr)} + ${inr(covered)} rebate from the sponsor pool`} />
        <Tile k="B" tone="b" label="Acquirer / network" value={inr(acquirer)} sub="Its full MDR, nothing waived" />
        <Tile k="C" tone="c" label="Paytm platform spread" value={inr(platform)} sub="Ad liquidity minus the fee covered" />
        <Tile k="D" tone="d" label="Sponsors paid" value={inr(liquidity)} sub={sponsors.map((sp) => `${sp.name} ${inr(sp.amount_paise)}`).join(' · ') || 'No sponsors matched'} />
      </div>

      {paidLegs.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-outline">
          <table className="tbl">
            <thead>
              <tr>
                <th>Leg</th>
                <th>Invoice</th>
                <th>Rail</th>
                <th className="text-right">Amount</th>
                <th className="text-right">MDR</th>
              </tr>
            </thead>
            <tbody>
              {paidLegs.map((l) => (
                <tr key={l.id}>
                  <td>
                    {l.seq}/{l.of}
                  </td>
                  <td className="min-w-[140px]">{l.label}</td>
                  <td className="whitespace-nowrap">{railLabel(l.rail)}</td>
                  <td className="text-right font-mono">{inr(l.amount_paise)}</td>
                  <td className="text-right font-mono">{inr(l.mdr_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
