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

/**
 * Merchant terminal: build a bill (catalog, manual rows, pasted text, bill photo), then
 * create the bill, then watch the payment live on the right.
 */
export default function BillBuilder({ merchant, catalog, devices, orderId, onOrder, onCloseOrder, goTab }) {
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState('');
  const [showPaste, setShowPaste] = useState(false);
  const [rawText, setRawText] = useState('');
  const [parsing, setParsing] = useState(null); // 'text' | 'image'
  const [parseErr, setParseErr] = useState(null);
  const [parseMeta, setParseMeta] = useState(null);
  const [deviceId, setDeviceId] = useState('');
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState(null);
  const fileRef = useRef(null);
  const rightRef = useRef(null);

  const myDevices = devices || [];
  useEffect(() => {
    if (!myDevices.find((d) => d.id === deviceId)) {
      const online = myDevices.find((d) => d.online);
      setDeviceId((online || myDevices[0])?.id || '');
    }
  }, [myDevices, deviceId]);

  const items = useMemo(() => rows.map(rowToItem), [rows]);
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

  const finishOrder = (order) => {
    setRows([]);
    setParseMeta(null);
    onOrder(order);
    setTimeout(() => rightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  };

  const create = async (body) => {
    setCreating(true);
    setCreateErr(null);
    try {
      finishOrder(await api.createOrder({ device_id: deviceId, ...body }));
    } catch (e) {
      setCreateErr(e);
    } finally {
      setCreating(false);
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = q ? (catalog || []).filter((c) => `${c.name} ${c.brand || ''} ${c.category || ''} ${c.hsn_sac || ''}`.toLowerCase().includes(q)) : catalog || [];
    return list.slice(0, 24);
  }, [catalog, search]);

  const deviceReady = !!deviceId;

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
      <div className="min-w-0 space-y-6 xl:col-span-7">
        <Card
          accent
          icon="receipt_long"
          title="New bill"
          subtitle="Add items from your catalog, type rows, paste bill text or upload a photo. The customer pays the full amount with one QR, and right after the payment message the Soundbox plays a short ad from a nearby business."
        >
          <AiWarning className="mb-4" what="Bill text and photo reading" />

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
                <span>Your catalog is empty. Add your products once to bill them with a tap.</span>
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
                      <input className="input input-sm col-span-3 font-mono sm:col-span-2" value={r.hsn_sac} placeholder="Optional" onChange={(e) => update(r.key, { hsn_sac: e.target.value })} aria-label="HSN or SAC code (optional)" />
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


          <div className="mt-4 flex flex-col gap-3 border-t border-outline-variant pt-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-label-sm text-on-surface-variant">Customer pays</div>
              <div className="tnum text-headline-lg text-paytm-navy">{inr(total)}</div>
            </div>
            <button type="button" className="btn btn-cyan btn-lg" disabled={invalid || creating || !deviceReady} onClick={() => create({ items })}>
              {creating ? <Spinner /> : <Icon name="qr_code_2" className="text-[18px]" />}
              {creating ? 'Creating…' : 'Create bill & show QR'}
            </button>
          </div>

          <ErrorNote error={createErr} title="Could not create the bill" className="mt-4" />
        </Card>
      </div>

      <div ref={rightRef} className={`min-w-0 scroll-mt-20 space-y-6 xl:col-span-5 ${orderId ? 'order-first xl:order-none' : ''}`}>
        {orderId ? (
          <OrderView key={orderId} orderId={orderId} onClose={onCloseOrder} />
        ) : (
          <Card icon="qr_code_2" title="Live order">
            <Empty icon="qr_code_2" title="No bill in progress">
              Build a bill and press "Create bill & show QR". The QR appears on the Soundbox, the customer pays, the Soundbox announces the payment and then plays a nearby business's ad, and your ad earnings show here once the payment lands.
            </Empty>
          </Card>
        )}
      </div>
    </div>
  );
}
