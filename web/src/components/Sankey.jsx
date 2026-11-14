import { useEffect, useMemo, useRef, useState } from 'react';
import { sankey, sankeyLinkHorizontal, sankeyJustify } from 'd3-sankey';
import { inr } from '../format.js';
import { Empty } from './ui.jsx';

// Node colour follows the entity's role (never its rank), using the admin mockup's legend.
export const ROLES = [
  { key: 'customer', label: 'Customer', color: '#002970', test: /customer|payer|buyer/i },
  { key: 'merchant', label: 'Merchant', color: '#00BAF2', test: /merchant|store|shop/i },
  { key: 'acquirer', label: 'Acquirer / network', color: '#EA580C', test: /acquir|network|mdr|bank/i },
  { key: 'pool', label: 'Sponsor pool', color: '#00B06F', test: /pool|rebate/i },
  { key: 'advertiser', label: 'Advertisers', color: '#E53935', test: /advertis|sponsor|wallet|brand|campaign|subvention/i },
  { key: 'funding', label: 'Wallet top-ups', color: '#7DD3FC', test: /funding|top-?up/i },
  { key: 'rental', label: 'Rental credit', color: '#F5A623', test: /rental/i },
  { key: 'platform', label: 'Paytm platform', color: '#0F4A8A', test: /paytm|platform|revenue|spread/i },
  { key: 'gst', label: 'GST', color: '#94A3B8', test: /gst|tax/i },
];
const COLOR = Object.fromEntries(ROLES.map((r) => [r.key, r.color]));
COLOR.other = '#64748B';

// Known ledger account ids map straight to a role; anything else falls back to regex.
const ID_ROLES = { customer: 'customer', acquirer: 'acquirer', sponsor_pool: 'pool', platform: 'platform', funding: 'funding' };

function roleOf(node) {
  const id = String(node.id);
  if (ID_ROLES[id]) return ID_ROLES[id];
  if (id.startsWith('merchant:')) return 'merchant';
  if (id.startsWith('adv:') || id.startsWith('advertiser')) return 'advertiser';
  if (id.startsWith('soundbox_rental') || id.startsWith('rental')) return 'rental';
  const s = `${node.id} ${node.label || ''}`;
  if (/funding|top-?up/i.test(s)) return 'funding';
  for (const k of ['rental', 'pool', 'platform', 'acquirer', 'customer', 'advertiser', 'merchant', 'gst']) {
    const r = ROLES.find((x) => x.key === k);
    if (r.test.test(s)) return r.key;
  }
  return 'other';
}

function useWidth(ref) {
  const [w, setW] = useState(900);
  useEffect(() => {
    if (!ref.current) return undefined;
    setW(Math.max(0, (ref.current.clientWidth || 916) - 16));
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect?.width;
      if (cw) setW(Math.round(cw));
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

/** Money-flow Sankey from GET /api/ledger/flows. Scrolls inside its own card below 680 px. */
export default function Sankey({ data, compressed = true, height: hProp }) {
  const wrapRef = useRef(null);
  const outer = useWidth(wrapRef);
  const width = Math.max(680, outer);
  const [hover, setHover] = useState(null);
  const [hi, setHi] = useState(null);
  const narrow = width < 820;
  const height = hProp || (narrow ? 360 : 400);

  const layout = useMemo(() => {
    if (!data || !Array.isArray(data.links)) return { empty: true };
    const links = data.links
      .filter((l) => l && l.source !== l.target && Number(l.amount_paise) > 0)
      .map((l) => ({
        source: String(l.source),
        target: String(l.target),
        amount: Number(l.amount_paise),
        value: compressed ? Math.sqrt(Number(l.amount_paise)) : Number(l.amount_paise),
      }));
    if (!links.length) return { empty: true };
    const used = new Set(links.flatMap((l) => [l.source, l.target]));
    const nodeMap = new Map((data.nodes || []).map((n) => [String(n.id), n]));
    const nodes = Array.from(used).map((id) => {
      const n = nodeMap.get(id) || { id, label: id };
      return { id, label: n.label || id, role: roleOf({ id, label: n.label }) };
    });
    try {
      const gen = sankey()
        .nodeId((d) => d.id)
        .nodeAlign(sankeyJustify)
        .nodeWidth(10)
        .nodePadding(narrow ? 18 : 26)
        .extent([
          [4, 12],
          [width - 4, height - 12],
        ]);
      const g = gen({ nodes: nodes.map((d) => ({ ...d })), links: links.map((d) => ({ ...d })) });
      g.nodes.forEach((n) => {
        const inAmt = n.targetLinks.reduce((s, l) => s + l.amount, 0);
        const outAmt = n.sourceLinks.reduce((s, l) => s + l.amount, 0);
        n.amount = Math.max(inAmt, outAmt);
      });
      return { g };
    } catch (e) {
      return { error: String(e.message || e), links };
    }
  }, [data, compressed, width, height, narrow]);

  const rolesPresent = useMemo(() => {
    if (!layout.g) return [];
    const s = new Set(layout.g.nodes.map((n) => n.role));
    return [...ROLES.filter((r) => s.has(r.key)), ...(s.has('other') ? [{ key: 'other', label: 'Other', color: COLOR.other }] : [])];
  }, [layout]);

  if (layout.empty) {
    return (
      <div ref={wrapRef}>
        <Empty icon="account_tree" title="No money has moved yet">
          Flows appear here once a merchant's order is paid and settled, or an advertiser tops up their wallet.
        </Empty>
      </div>
    );
  }
  if (layout.error) {
    return (
      <div ref={wrapRef} className="space-y-2">
        <div className="note note-warn">Could not lay out the Sankey ({layout.error}). Showing the flows as a table.</div>
        <FlowTable links={layout.links} nodes={data.nodes} />
      </div>
    );
  }

  const path = sankeyLinkHorizontal();
  const { g } = layout;
  const linkActive = (l, i) => hi === null || hi === i || hi === l.source.id || hi === l.target.id;
  const showTip = (e, title, amt) => {
    const box = wrapRef.current.getBoundingClientRect();
    setHover({ x: e.clientX - box.left + wrapRef.current.scrollLeft, y: e.clientY - box.top, title, amt });
  };

  return (
    <div>
      <div
        ref={wrapRef}
        className="relative overflow-x-auto rounded-xl border border-outline-variant bg-surface-subtle p-2 shadow-inner"
        onMouseLeave={() => {
          setHover(null);
          setHi(null);
        }}
      >
        <svg width={width} height={height} role="img" aria-label="Money flow Sankey diagram" className="block">
          <defs>
            {g.links.map((l, i) => (
              <linearGradient key={i} id={`skg-${i}`} gradientUnits="userSpaceOnUse" x1={l.source.x1} x2={l.target.x0}>
                <stop offset="0%" stopColor={COLOR[l.source.role]} />
                <stop offset="100%" stopColor={COLOR[l.target.role]} />
              </linearGradient>
            ))}
          </defs>
          <g fill="none">
            {g.links.map((l, i) => (
              <path
                key={i}
                d={path(l)}
                stroke={`url(#skg-${i})`}
                strokeOpacity={linkActive(l, i) ? 0.42 : 0.1}
                strokeWidth={Math.max(1.5, l.width)}
                className="cursor-pointer transition-[stroke-opacity]"
                onMouseMove={(e) => {
                  setHi(i);
                  showTip(e, `${l.source.label} → ${l.target.label}`, inr(l.amount));
                }}
                onMouseLeave={() => setHi(null)}
              />
            ))}
          </g>
          <g>
            {g.nodes.map((n) => {
              const left = n.x0 < width / 2;
              const h = Math.max(2, n.y1 - n.y0);
              const cy = (n.y0 + n.y1) / 2;
              const tx = left ? n.x1 + 8 : n.x0 - 8;
              return (
                <g
                  key={n.id}
                  className="cursor-pointer"
                  onMouseMove={(e) => {
                    setHi(n.id);
                    showTip(e, n.label, inr(n.amount));
                  }}
                  onMouseLeave={() => setHi(null)}
                >
                  <rect x={n.x0} y={n.y0} width={n.x1 - n.x0} height={h} rx="3" fill={COLOR[n.role]} />
                  <rect x={n.x0 - 6} y={n.y0 - 4} width={n.x1 - n.x0 + 12} height={h + 8} fill="transparent" />
                  <text x={tx} y={cy - 3} textAnchor={left ? 'start' : 'end'} fontSize="12" fontWeight="700" fill="#002970" style={{ paintOrder: 'stroke', stroke: 'rgba(255,255,255,0.9)', strokeWidth: 3, strokeLinejoin: 'round' }}>
                    {n.label}
                  </text>
                  <text x={tx} y={cy + 12} textAnchor={left ? 'start' : 'end'} fontSize="11" fontWeight="600" fill={n.role === 'customer' ? '#0099cc' : COLOR[n.role]} style={{ paintOrder: 'stroke', stroke: 'rgba(255,255,255,0.9)', strokeWidth: 3, strokeLinejoin: 'round', fontVariantNumeric: 'tabular-nums' }}>
                    {inr(n.amount)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
        {hover && (
          <div className="pointer-events-none absolute z-10 rounded-lg border border-outline bg-white px-2.5 py-1.5 text-body-sm shadow-ambient" style={{ left: Math.min(hover.x + 12, width - 220), top: hover.y + 12 }}>
            <div className="text-on-surface-variant">{hover.title}</div>
            <b className="tnum text-paytm-navy">{hover.amt}</b>
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-body-sm font-medium text-on-surface-variant">
        {rolesPresent.map((r) => (
          <span key={r.key} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: r.color }} />
            {r.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function FlowTable({ links, nodes }) {
  const label = (id) => (nodes || []).find((n) => String(n.id) === String(id))?.label || id;
  if (!links?.length) {
    return <Empty icon="table_rows" title="No flows yet" />;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-outline">
      <table className="tbl">
        <thead>
          <tr>
            <th>From</th>
            <th>To</th>
            <th className="text-right">Amount</th>
          </tr>
        </thead>
        <tbody>
          {links.map((l, i) => (
            <tr key={i} className="hover:bg-surface-subtle">
              <td className="font-semibold">{label(l.source)}</td>
              <td>{label(l.target)}</td>
              <td className="text-right font-mono font-bold">{inr(l.amount ?? l.amount_paise)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
