import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import { codeLabel, inr, pct, railLabel, reasonText, supplyOf, toPaise, toRupeeInput, titleCase } from '../format.js';
import { AiWarning, Card, Empty, ErrorNote, Icon, Pill, SourceBadge, Spinner, Toggle } from './ui.jsx';
import OrderView from './OrderView.jsx';

let rowSeq = 1;
const newRow = (it = {}) => ({
  key: rowSeq++,
  name: it.name || '',
  qty: String(it.qty ?? 1),
  price: it.unit_price !== undefined && it.unit_price !== null ? toRupeeInput(it.unit_price) : '',
  hsn_sac: it.hsn_sac || '',
  category: it.category || '',
  brand: it.brand || '',
  supplier_gstin: it.supplier_gstin || '',
  catalog_item_id: it.catalog_item_id || (it.id && String(it.id).startsWith('C-') ? it.id : ''),
  open: false,
});

const MAX_IMAGE = 8 * 1024 * 1024;
const qtyOf = (r) => Math.max(0, parseInt(r.qty, 10) || 0);
const rowAmount = (r) => qtyOf(r) * toPaise(r.price);

function rowToItem(r) {
  const it = { name: r.name.trim(), qty: qtyOf(r) || 1, unit_price: toPaise(r.price) };
  if (r.hsn_sac.trim()) it.hsn_sac = r.hsn_sac.trim();
  if (r.category.trim()) it.category = r.category.trim().toLowerCase();
  if (r.brand.trim()) it.brand = r.brand.trim().toLowerCase();
  if (r.supplier_gstin.trim()) it.supplier_gstin = r.supplier_gstin.trim().toUpperCase();
  if (r.catalog_item_id) it.catalog_item_id = r.catalog_item_id;
  return it;
}

function CodeChip({ item }) {
  const label = codeLabel(item);
  if (!label) return <span className="text-body-sm text-on-surface-variant">—</span>;
  return <span className={`code-chip ${supplyOf(item) === 'services' ? 'code-services' : 'code-goods'}`}>{label}</span>;
}

function SentinelVerdict({ sentinel }) {
  if (!sentinel) return null;
  const tone = sentinel.decision === 'allow' ? 'good' : sentinel.decision === 'flag' ? 'warn' : 'bad';
  const box = { good: 'border-emerald-200 bg-emerald-50', warn: 'border-amber-200 bg-amber-50', bad: 'border-rose-200 bg-rose-50' }[tone];
  const icon = { good: 'verified_user', warn: 'flag', bad: 'gpp_bad' }[tone];
  const text = { good: 'Sentinel allows this split', warn: 'Sentinel flagged this split', bad: 'Sentinel blocks this split' }[tone];
  return (
    <div className={`rounded-xl border p-3 ${box}`}>
      <div className="flex items-center gap-2 text-label-lg text-paytm-navy">
        <Icon name={icon} className={`text-[20px] ${tone === 'good' ? 'text-success-green' : tone === 'warn' ? 'text-amber-600' : 'text-error-red'}`} />
        {text}
        <Pill status={sentinel.decision} />
      </div>
      {sentinel.reasons?.length > 0 && (
        <ul className="mt-1.5 list-disc pl-8 text-body-sm text-on-surface">
          {sentinel.reasons.map((r, i) => (
            <li key={i}>{reasonText(r)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PlanView({ plan, stale, deviceReady, creating, onCreate, onDiscard, createErr }) {
  const est = plan.estimate || {};
  const max = Math.max(est.mdr_single_paise || 0, est.mdr_split_paise || 0, 1);
  const blocked = plan.sentinel?.decision === 'block';
  return (
    <Card
      accent
      icon="call_split"
      title="AI bill plan"
      subtitle="Classified items, proposed GST legs and the fee estimate. Review, then create the order."
      actions={<SourceBadge label="Split" source={plan.source} model={plan.model} reason={plan.fallback_reason} />}
    >
      <div className="space-y-4">
        {plan.classification && plan.classification.source !== 'none' && (
          <div className="flex flex-wrap items-center gap-2 text-body-sm text-on-surface-variant">
            HSN/SAC classification
            <SourceBadge source={plan.classification.source} model={plan.model} reason={plan.classification.fallback_reason} />
          </div>
        )}
        {stale && (
          <div className="note note-warn flex items-start gap-2">
            <Icon name="update" className="text-[18px]" />
            The bill changed after this plan was made. Split again before creating the order.
          </div>
        )}

        <div>
          <h4 className="mb-1.5 text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">Classified items</h4>
          <div className="overflow-x-auto rounded-xl border border-outline-variant">
            <table className="tbl">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Item</th>
                  <th>Code</th>
                  <th>Category / brand</th>
                  <th className="text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {(plan.items || []).map((it, i) => (
                  <tr key={i}>
                    <td className="text-on-surface-variant">{i + 1}</td>
                    <td className="min-w-[140px]">
                      <div className="font-semibold">{it.name}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1">
                        {it.qty > 1 && <span className="text-on-surface-variant">× {it.qty}</span>}
                        {it.classification_source && <SourceBadge source={it.classification_source} model={it.classification_source === 'ai' ? plan.model : null} />}
                      </div>
                    </td>
                    <td>
                      <CodeChip item={it} />
                    </td>
                    <td className="text-on-surface-variant">
                      {titleCase(it.category) || '—'}
                      {it.brand ? ` · ${titleCase(it.brand)}` : ''}
                      {it.supplier_gstin && <div className="font-mono text-[10px]">GSTIN {it.supplier_gstin}</div>}
                    </td>
                    <td className="text-right font-mono">{inr(Math.round((it.qty || 1) * (it.unit_price || 0)))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h4 className="mb-1.5 text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">
            Proposed legs ({plan.legs?.length || 0} QR{plan.legs?.length === 1 ? '' : 's'})
          </h4>
          <div className="grid gap-2 sm:grid-cols-2">
            {(plan.legs || []).map((l, i) => (
              <div key={i} className="min-w-0 rounded-xl border border-outline-variant bg-surface-subtle p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">Leg {i + 1}</span>
                  <span className={`code-chip ${l.supply_type === 'services' ? 'code-services' : 'code-goods'}`}>{l.supply_type}</span>
                </div>
                <div className="mt-1 break-words text-label-lg text-paytm-navy">{l.label}</div>
                <div className="tnum text-headline-sm font-extrabold text-paytm-navy">{inr(l.amount_paise)}</div>
                <div className="mt-1 text-body-sm text-on-surface-variant">Items {(l.item_indexes || []).map((x) => x + 1).join(', ')}</div>
                {l.reason && <p className="mt-1.5 border-l-2 border-paytm-cyan pl-2 text-body-sm italic text-on-surface">{l.reason}</p>}
              </div>
            ))}
          </div>
        </div>

        {plan.rationale && (
          <div className="rounded-xl border border-paytm-cyan/30 bg-paytm-cyan-light/60 p-3 text-body-sm">
            <div className="mb-0.5 flex items-center gap-1.5 text-label-md text-paytm-navy">
              <Icon name="psychology" className="text-[18px] text-paytm-cyan-dark" />
              Why this split
            </div>
            <p className="text-on-surface">{plan.rationale}</p>
          </div>
        )}

        {plan.estimate && (
          <div className="card-inset space-y-2 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-label-lg text-paytm-navy">MDR by payment method</h4>
              <span className="text-body-sm text-on-surface-variant">charged at the rate of the method the customer uses</span>
            </div>
            {Array.isArray(est.by_rail) && est.by_rail.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[360px] text-body-sm">
                  <thead>
                    <tr className="text-left text-label-sm uppercase text-on-surface-variant">
                      <th className="py-1 pr-2 font-semibold">Customer pays with</th>
                      <th className="py-1 pr-2 text-right font-semibold">Single QR</th>
                      <th className="py-1 pr-2 text-right font-semibold">With split</th>
                      <th className="py-1 text-right font-semibold">Saves</th>
                    </tr>
                  </thead>
                  <tbody>
                    {est.by_rail.map((r) => (
                      <tr key={r.rail} className="border-t border-slate-100">
                        <td className="py-1.5 pr-2 text-on-surface">{railLabel(r.rail)}</td>
                        <td className="tnum py-1.5 pr-2 text-right font-mono">{inr(r.mdr_single_paise)}</td>
                        <td className="tnum py-1.5 pr-2 text-right font-mono font-bold text-paytm-navy">{inr(r.mdr_split_paise)}</td>
                        <td className={`tnum py-1.5 text-right font-mono font-semibold ${r.saving_paise > 0 ? 'text-success-green' : 'text-on-surface-variant'}`}>
                          {r.saving_paise > 0 ? inr(r.saving_paise) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              [
                ['Single QR', est.mdr_single_paise, 'bg-slate-300'],
                ['With split', est.mdr_split_paise, 'bg-gradient-to-r from-paytm-cyan to-paytm-navy'],
              ].map(([label, v, cls]) => (
                <div key={label} className="grid grid-cols-[76px_1fr_auto] items-center gap-3 text-body-sm">
                  <span className="text-on-surface-variant">{label}</span>
                  <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                    <div className={`h-full rounded-full ${cls}`} style={{ width: `${Math.max(2, ((v || 0) / max) * 100)}%` }} />
                  </div>
                  <span className="tnum font-mono font-bold text-paytm-navy">{inr(v)}</span>
                </div>
              ))
            )}
            <div className={`text-body-sm font-semibold ${est.saving_paise > 0 ? 'text-success-green' : 'text-on-surface-variant'}`}>
              {est.saving_paise > 0
                ? `Up to ${inr(est.saving_paise)} (${pct((est.saving_paise / Math.max(1, est.mdr_single_paise)) * 100)}) saved if the customer pays by ${railLabel(est.worst_case_rail)}`
                : 'No MDR saving from splitting this bill.'}
            </div>
          </div>
        )}

        <SentinelVerdict sentinel={plan.sentinel} />
        <ErrorNote error={createErr} title="Could not create order" />

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn btn-soft" onClick={onDiscard}>
            Discard plan
          </button>
          <button type="button" className="btn btn-navy btn-lg" disabled={stale || blocked || creating || !deviceReady} onClick={onCreate}>
            {creating ? <Spinner /> : <Icon name="qr_code_2" className="text-[18px] text-paytm-cyan" />}
            Create order from plan
          </button>
        </div>
        {!deviceReady && <div className="text-right text-body-sm text-amber-700">Pick a Soundbox for this bill first.</div>}
      </div>
    </Card>
  );
}

function BlockedPanel({ blocked, onClose }) {
  return (
    <div className="rounded-xl border-2 border-error-red/40 bg-rose-50 p-4" role="alert">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-error-red">
          <Icon name="gpp_bad" className="text-[24px]" />
        </span>
        <div className="min-w-0">
          <div className="text-headline-sm font-bold text-rose-800">Blocked by Sentinel</div>
          <div className="text-body-sm text-rose-800/80">This split is not along a real supply boundary. No QR was created and nothing was charged.</div>
        </div>
      </div>
      {blocked.reasons?.length > 0 ? (
        <ul className="mt-3 list-disc space-y-0.5 pl-6 text-body-sm text-rose-900">
          {blocked.reasons.map((r, i) => (
            <li key={i}>{reasonText(r)}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-body-sm text-rose-900">{blocked.detail || 'No reason given.'}</p>
      )}
      <button type="button" className="btn btn-outline btn-sm mt-3" onClick={onClose}>
        Dismiss
      </button>
    </div>
  );
}

/**
 * Merchant terminal: build a bill (catalog, manual rows, pasted text, bill photo), ask the AI for a
 * GST split plan, create the order, then watch it live on the right.
 */
export default function BillBuilder({ merchant, catalog, devices, orderId, onOrder, onCloseOrder, goTab }) {
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState('');
  const [showPaste, setShowPaste] = useState(false);
  const [rawText, setRawText] = useState('');
  const [parsing, setParsing] = useState(null); // 'text' | 'image'
  const [parseErr, setParseErr] = useState(null);
  const [parseMeta, setParseMeta] = useState(null);
  const [factorize, setFactorize] = useState(merchant?.factorization_enabled ?? true);
  const [deviceId, setDeviceId] = useState('');
  const [plan, setPlan] = useState(null); // {data, key}
  const [planning, setPlanning] = useState(false);
  const [planErr, setPlanErr] = useState(null);
  const [manual, setManual] = useState(false);
  const [legCount, setLegCount] = useState(2);
  const [assign, setAssign] = useState({});
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState(null);
  const [blocked, setBlocked] = useState(null);
  const fileRef = useRef(null);
  const rightRef = useRef(null);

  useEffect(() => {
    setFactorize(merchant?.factorization_enabled ?? true);
  }, [merchant?.id, merchant?.factorization_enabled]);

  const myDevices = devices || [];
  useEffect(() => {
    if (!myDevices.find((d) => d.id === deviceId)) {
      const online = myDevices.find((d) => d.online);
      setDeviceId((online || myDevices[0])?.id || '');
    }
  }, [myDevices, deviceId]);

  const items = useMemo(() => rows.map(rowToItem), [rows]);
  const itemsKey = JSON.stringify([items, factorize]);
  const total = rows.reduce((s, r) => s + rowAmount(r), 0);
  const invalid = rows.length === 0 || rows.some((r) => !r.name.trim() || rowAmount(r) <= 0);

  const update = (key, patch) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const remove = (key) => setRows((rs) => rs.filter((r) => r.key !== key));
  const addItems = (list) => {
    setRows((rs) => [...rs, ...list.map(newRow)]);
    setBlocked(null);
    setCreateErr(null);
  };
  const addCatalogItem = (c) => {
    const existing = rows.find((r) => r.catalog_item_id === c.id);
    if (existing) update(existing.key, { qty: String(qtyOf(existing) + 1) });
    else addItems([{ ...c, catalog_item_id: c.id, qty: 1 }]);
  };

  const runParse = async (kind, arg) => {
    setParsing(kind);
    setParseErr(null);
    setParseMeta(null);
    try {
      const res = kind === 'text' ? await api.parseBillText(arg) : await api.parseBillImage(arg);
      const found = res?.items || [];
      setParseMeta({ kind, count: found.length, source: res?.source, model: res?.model, reason: res?.fallback_reason });
      if (found.length) {
        addItems(found);
        if (kind === 'text') {
          setRawText('');
          setShowPaste(false);
        }
      }
    } catch (e) {
      setParseErr(e);
    } finally {
      setParsing(null);
    }
  };

  const onFile = (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) {
      setParseErr(Object.assign(new Error('Use a JPEG, PNG or WebP photo of the bill.'), {}));
      return;
    }
    if (f.size > MAX_IMAGE) {
      setParseErr(Object.assign(new Error(`That photo is ${(f.size / 1048576).toFixed(1)} MB; the limit is 8 MB.`), {}));
      return;
    }
    runParse('image', f);
  };

  const makePlan = async () => {
    setPlanning(true);
    setPlanErr(null);
    setBlocked(null);
    setCreateErr(null);
    try {
      const data = await api.planBill(items, factorize);
      setPlan({ data, key: itemsKey });
      if (orderId) onCloseOrder();
      setTimeout(() => rightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
    } catch (e) {
      setPlanErr(e);
    } finally {
      setPlanning(false);
    }
  };

  const finishOrder = (order) => {
    setRows([]);
    setAssign({});
    setManual(false);
    setPlan(null);
    setParseMeta(null);
    onOrder(order);
    setTimeout(() => rightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  };

  const create = async (body) => {
    setCreating(true);
    setCreateErr(null);
    setBlocked(null);
    try {
      finishOrder(await api.createOrder({ device_id: deviceId, factorize, ...body }));
    } catch (e) {
      if (e.status === 422 && (e.error === 'sentinel_blocked' || e.reasons)) {
        setBlocked({ reasons: e.reasons || [], detail: e.message });
      } else setCreateErr(e);
    } finally {
      setCreating(false);
    }
  };

  const createFromPlan = () => {
    const p = plan.data;
    // The contract accepts Plan.items and Plan.legs passed straight through.
    create({
      items: p.items || [],
      legs: p.legs || [],
      plan_source: p.source,
      ...(p.rationale ? { rationale: p.rationale } : {}),
      ...(p.fallback_reason ? { fallback_reason: p.fallback_reason } : {}),
    });
  };

  // Manual split: each row can be ticked into one or more legs (the Sentinel rejects illegal ones).
  const legsOf = (r, i) => assign[r.key] ?? [Math.min(i, legCount - 1)];
  const toggleLeg = (r, i, leg) => {
    const cur = legsOf(r, i);
    setAssign((a) => ({ ...a, [r.key]: cur.includes(leg) ? cur.filter((x) => x !== leg) : [...cur, leg].sort() }));
  };
  const manualLegs = useMemo(() => {
    const legs = Array.from({ length: legCount }, () => []);
    rows.forEach((r, i) => legsOf(r, i).forEach((l) => l < legCount && legs[l].push(i)));
    return legs.filter((l) => l.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [legCount, rows, assign]);
  const unassigned = rows.filter((r, i) => legsOf(r, i).filter((l) => l < legCount).length === 0).length;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = q ? (catalog || []).filter((c) => `${c.name} ${c.brand || ''} ${c.category || ''} ${c.hsn_sac || ''}`.toLowerCase().includes(q)) : catalog || [];
    return list.slice(0, 24);
  }, [catalog, search]);

  const stale = plan && plan.key !== itemsKey;
  const deviceReady = !!deviceId;

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
      <div className="min-w-0 space-y-6 xl:col-span-7">
        <Card
          accent
          icon="receipt_long"
          title="New bill"
          subtitle="Add items from your catalog, type rows, paste bill text or upload a photo. AI classifies HSN/SAC codes and splits the bill into legal GST legs."
        >
          <AiWarning className="mb-4" what="Bill parsing and splitting" />

          {/* Catalog quick-add */}
          <div className="card-inset p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-label-lg text-paytm-navy">
                <Icon name="inventory_2" className="text-[18px] text-paytm-cyan-dark" />
                Catalog
              </span>
              {catalog?.length > 0 && (
                <div className="relative w-full sm:w-56">
                  <Icon name="search" className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[18px] text-slate-400" />
                  <input className="input input-sm pl-8" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search catalog" aria-label="Search catalog" />
                </div>
              )}
            </div>
            {!catalog ? (
              <div className="flex items-center gap-2 text-body-sm text-on-surface-variant">
                <Spinner /> Loading catalog…
              </div>
            ) : catalog.length === 0 ? (
              <div className="flex flex-wrap items-center justify-between gap-2 text-body-sm text-on-surface-variant">
                <span>Your catalog is empty. Add products once and AI fills in HSN/SAC codes.</span>
                <button type="button" className="btn btn-outline btn-sm" onClick={() => goTab('catalog')}>
                  <Icon name="add" className="text-[16px]" />
                  Add catalog items
                </button>
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-body-sm text-on-surface-variant">No catalog item matches "{search}".</div>
            ) : (
              <div className="grid max-h-56 grid-cols-1 gap-2 overflow-y-auto pr-1 min-[420px]:grid-cols-2 lg:grid-cols-3">
                {filtered.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => addCatalogItem(c)}
                    className="flex min-w-0 flex-col items-start gap-1 rounded-lg border border-outline-variant bg-white p-2 text-left transition-colors hover:border-primary hover:bg-surface-ice"
                  >
                    <span className="w-full truncate text-label-md text-paytm-navy">{c.name}</span>
                    <span className="flex w-full items-center justify-between gap-1">
                      <CodeChip item={c} />
                      <b className="tnum text-label-md text-paytm-navy">{inr(c.unit_price)}</b>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Paste / photo */}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className={`btn btn-sm ${showPaste ? 'btn-navy' : 'btn-outline'}`} onClick={() => setShowPaste((s) => !s)}>
              <Icon name="content_paste" className="text-[16px]" />
              Paste bill text
            </button>
            <button type="button" className="btn btn-outline btn-sm" disabled={!!parsing} onClick={() => fileRef.current?.click()}>
              {parsing === 'image' ? <Spinner /> : <Icon name="photo_camera" className="text-[16px]" />}
              Upload bill photo
            </button>
            <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={onFile} />
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => addItems([{}])}>
              <Icon name="add" className="text-[16px]" />
              Add row
            </button>
          </div>
          {showPaste && (
            <div className="mt-3 space-y-2">
              <textarea className="input min-h-[110px] font-mono text-body-sm" value={rawText} onChange={(e) => setRawText(e.target.value)} placeholder="Paste the bill text: one line per item with quantity and price" aria-label="Bill text" />
              <button type="button" className="btn btn-navy btn-sm" disabled={!!parsing || !rawText.trim()} onClick={() => runParse('text', rawText)}>
                {parsing === 'text' ? <Spinner /> : <Icon name="auto_awesome" className="text-[16px] text-paytm-cyan" />}
                Extract line items
              </button>
            </div>
          )}
          {parseMeta && (
            <div className={`mt-3 flex flex-wrap items-center gap-2 text-body-sm ${parseMeta.count ? 'text-on-surface-variant' : 'text-amber-800'}`}>
              {parseMeta.count ? `Added ${parseMeta.count} item${parseMeta.count === 1 ? '' : 's'} from the ${parseMeta.kind === 'image' ? 'photo' : 'text'}.` : `No line items found in that ${parseMeta.kind === 'image' ? 'photo' : 'text'}.`}
              <SourceBadge source={parseMeta.source} model={parseMeta.model} reason={parseMeta.reason} />
            </div>
          )}
          <ErrorNote error={parseErr} title="Could not read the bill" className="mt-3" />

          {/* Rows */}
          <div className="mt-4">
            {rows.length === 0 ? (
              <Empty icon="shopping_cart" title="The bill is empty">
                Tap catalog items, add a row, paste bill text or upload a photo.
              </Empty>
            ) : (
              <div className="space-y-2">
                <div className="hidden grid-cols-12 gap-2 px-1 text-[11px] font-bold uppercase tracking-wide text-on-surface-variant sm:grid">
                  <span className="col-span-5">Item</span>
                  <span className="col-span-1">Qty</span>
                  <span className="col-span-2">Unit ₹</span>
                  <span className="col-span-2">HSN/SAC</span>
                  <span className="col-span-2 text-right">Amount</span>
                </div>
                {rows.map((r, i) => (
                  <div key={r.key} className="rounded-xl border border-outline-variant bg-white p-2">
                    <div className="grid grid-cols-6 items-center gap-2 sm:grid-cols-12">
                      <input className="input input-sm col-span-6 sm:col-span-5" value={r.name} placeholder={`Item ${i + 1} name`} onChange={(e) => update(r.key, { name: e.target.value })} aria-label="Item name" />
                      <input className="input input-sm col-span-1 px-1.5 text-center sm:col-span-1" inputMode="numeric" value={r.qty} onChange={(e) => update(r.key, { qty: e.target.value.replace(/[^0-9]/g, '') })} aria-label="Quantity (whole units)" />
                      <input className="input input-sm tnum col-span-2 sm:col-span-2" inputMode="decimal" value={r.price} placeholder="Price" onChange={(e) => update(r.key, { price: e.target.value })} aria-label="Unit price in rupees" />
                      <input className="input input-sm col-span-3 font-mono sm:col-span-2" value={r.hsn_sac} placeholder="AI fills" onChange={(e) => update(r.key, { hsn_sac: e.target.value })} aria-label="HSN or SAC code (optional)" />
                      <span className="tnum col-span-4 text-right font-mono text-label-md text-paytm-navy sm:col-span-1 sm:text-[12px]">{inr(rowAmount(r))}</span>
                      <span className="col-span-2 flex justify-end sm:col-span-1">
                        <button type="button" className="btn-icon" title="More fields" aria-expanded={r.open} onClick={() => update(r.key, { open: !r.open })}>
                          <Icon name={r.open ? 'expand_less' : 'tune'} className="text-[18px]" />
                        </button>
                        <button type="button" className="btn-icon hover:text-error-red" title="Remove row" aria-label="Remove row" onClick={() => remove(r.key)}>
                          <Icon name="delete" className="text-[18px]" />
                        </button>
                      </span>
                    </div>
                    {r.open && (
                      <div className="mt-2 grid gap-2 sm:grid-cols-3">
                        <input className="input input-sm" value={r.category} placeholder="Category (optional)" onChange={(e) => update(r.key, { category: e.target.value })} aria-label="Category" />
                        <input className="input input-sm" value={r.brand} placeholder="Brand (optional)" onChange={(e) => update(r.key, { brand: e.target.value })} aria-label="Brand" />
                        <input className="input input-sm font-mono uppercase" value={r.supplier_gstin} placeholder="Supplier GSTIN (optional)" onChange={(e) => update(r.key, { supplier_gstin: e.target.value })} aria-label="Supplier GSTIN" />
                      </div>
                    )}
                  </div>
                ))}
                <div className="flex items-center justify-between rounded-xl bg-surface-high px-3 py-2">
                  <span className="text-label-md text-on-surface-variant">Bill total</span>
                  <strong className="tnum text-headline-md text-paytm-navy">{inr(total)}</strong>
                </div>
              </div>
            )}
          </div>

          {/* Options */}
          <div className="mt-4 grid gap-4 border-t border-outline-variant pt-4 md:grid-cols-2">
            <Toggle checked={factorize} onChange={setFactorize} label="Split along GST supply boundaries" hint="Goods (HSN) and services (SAC), or different supplier GSTINs, become separate QRs. Lines are never split." />
            <div>
              <span className="field-label">Soundbox for this bill</span>
              {myDevices.length === 0 ? (
                <div className="flex flex-wrap items-center gap-2 text-body-sm text-amber-800">
                  No Soundbox paired yet.
                  <button type="button" className="btn btn-outline btn-sm" onClick={() => goTab('devices')}>
                    Pair a Soundbox
                  </button>
                </div>
              ) : (
                <select className="input" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
                  {myDevices.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name && d.name !== d.id ? `${d.name} (${d.id})` : d.id} · {d.online ? 'online' : 'offline'}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          <ErrorNote error={planErr} title="AI split failed" className="mt-4" />

          <div className="mt-4 flex flex-col gap-3 border-t border-outline-variant pt-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-label-sm text-on-surface-variant">Customer pays</div>
              <div className="tnum text-headline-lg text-paytm-navy">{inr(total)}</div>
            </div>
            <button type="button" className="btn btn-cyan btn-lg" disabled={invalid || planning} onClick={makePlan}>
              {planning ? <Spinner /> : <Icon name="auto_awesome" className="text-[18px]" />}
              {planning ? 'Splitting…' : 'Split with AI'}
            </button>
          </div>

          {/* Advanced manual split */}
          <details className="mt-4 rounded-xl border border-outline-variant" open={manual} onToggle={(e) => setManual(e.currentTarget.open)}>
            <summary className="flex cursor-pointer items-center gap-2 px-3 py-2.5 text-label-md text-paytm-navy">
              <Icon name="tune" className="text-[18px] text-paytm-cyan-dark" />
              Advanced: manual split
              {manual && <Pill tone="warn">plan_source: manual</Pill>}
            </summary>
            <div className="space-y-3 border-t border-outline-variant p-3">
              <p className="text-body-sm text-on-surface-variant">
                Assign each line to a leg yourself. The Sentinel validates the split before any QR is created and rejects splits that are not along a real supply boundary.
              </p>
              <label className="flex items-center gap-2 text-body-sm">
                <span className="text-on-surface-variant">Legs</span>
                <select className="input input-sm w-20" value={legCount} onChange={(e) => setLegCount(Number(e.target.value))}>
                  {[1, 2, 3, 4].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              {rows.length === 0 ? (
                <div className="text-body-sm text-on-surface-variant">Add items to the bill first.</div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-outline-variant">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Item</th>
                        {Array.from({ length: legCount }, (_, l) => (
                          <th key={l} className="text-center">
                            Leg {l + 1}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={r.key}>
                          <td className="min-w-[160px]">
                            {i + 1}. {r.name || '(unnamed)'} <span className="text-on-surface-variant">{inr(rowAmount(r))}</span>
                          </td>
                          {Array.from({ length: legCount }, (_, l) => (
                            <td key={l} className="text-center">
                              <input type="checkbox" className="h-5 w-5" checked={legsOf(r, i).includes(l)} onChange={() => toggleLeg(r, i, l)} aria-label={`Item ${i + 1} in leg ${l + 1}`} />
                            </td>
                          ))}
                        </tr>
                      ))}
                      <tr className="bg-surface-subtle">
                        <td className="font-semibold">Leg totals</td>
                        {Array.from({ length: legCount }, (_, l) => (
                          <td key={l} className="text-center font-mono">
                            {inr(rows.reduce((s, r, i) => s + (legsOf(r, i).includes(l) ? rowAmount(r) : 0), 0))}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}
              {unassigned > 0 && <div className="note note-warn">{unassigned} item(s) are not in any leg.</div>}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <code className="break-all font-mono text-[11px] text-on-surface-variant">legs = {JSON.stringify(manualLegs)}</code>
                <button
                  type="button"
                  className="btn btn-navy"
                  disabled={invalid || creating || !deviceReady || manualLegs.length === 0}
                  onClick={() => create({ items, legs: manualLegs, plan_source: 'manual' })}
                >
                  {creating ? <Spinner /> : <Icon name="qr_code_2" className="text-[18px] text-paytm-cyan" />}
                  Create order (manual split)
                </button>
              </div>
            </div>
          </details>
          {blocked && (
            <div className="mt-4">
              <BlockedPanel blocked={blocked} onClose={() => setBlocked(null)} />
            </div>
          )}
          {!plan && <ErrorNote error={createErr} title="Could not create order" className="mt-4" />}
        </Card>
      </div>

      <div ref={rightRef} className={`min-w-0 scroll-mt-20 space-y-6 xl:col-span-5 ${orderId || plan ? 'order-first xl:order-none' : ''}`}>
        {orderId ? (
          <OrderView key={orderId} orderId={orderId} onClose={onCloseOrder} />
        ) : plan ? (
          <PlanView plan={plan.data} stale={stale} deviceReady={deviceReady} creating={creating} createErr={createErr} onCreate={createFromPlan} onDiscard={() => setPlan(null)} />
        ) : (
          <Card icon="qr_code_2" title="Live order">
            <Empty icon="call_split" title="No bill in progress">
              Build a bill and press "Split with AI". You'll see the classified items, the proposed GST legs with the AI's reasons, the MDR estimate and the Sentinel's verdict here. Create the order to show
              the QR codes and watch payment and settlement live.
            </Empty>
          </Card>
        )}
      </div>
    </div>
  );
}
