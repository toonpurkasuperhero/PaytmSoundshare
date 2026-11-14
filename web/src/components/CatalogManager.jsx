import { useState } from 'react';
import { api } from '../api.js';
import { codeLabel, inr, supplyOf, titleCase, toPaise, toRupeeInput } from '../format.js';
import { useConfig } from '../session.jsx';
import { AiWarning, Card, Empty, ErrorNote, Field, Icon, SourceBadge, Spinner } from './ui.jsx';

const blank = { name: '', price: '', hsn_sac: '', category: '', brand: '' };

function toBody(f, partial = false) {
  const b = { name: f.name.trim(), unit_price: toPaise(f.price) };
  ['hsn_sac', 'category', 'brand'].forEach((k) => {
    const v = f[k].trim();
    if (v) b[k] = k === 'hsn_sac' ? v : v.toLowerCase();
    else if (partial) b[k] = null;
  });
  return b;
}

function EditRow({ item, merchantId, onSaved, onCancel }) {
  const [f, setF] = useState({
    name: item.name,
    price: toRupeeInput(item.unit_price),
    hsn_sac: item.hsn_sac || '',
    category: item.category || '',
    brand: item.brand || '',
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = toBody(f);
      onSaved(await api.updateCatalogItem(merchantId, item.id, body));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2 rounded-xl border-2 border-primary bg-white p-3">
      <div className="grid gap-2 sm:grid-cols-12">
        <input className="input input-sm sm:col-span-4" value={f.name} onChange={set('name')} aria-label="Name" />
        <input className="input input-sm sm:col-span-2" inputMode="decimal" value={f.price} onChange={set('price')} aria-label="Unit price in rupees" />
        <input className="input input-sm font-mono sm:col-span-2" value={f.hsn_sac} onChange={set('hsn_sac')} placeholder="HSN/SAC" aria-label="HSN or SAC" />
        <input className="input input-sm sm:col-span-2" value={f.category} onChange={set('category')} placeholder="Category" aria-label="Category" />
        <input className="input input-sm sm:col-span-2" value={f.brand} onChange={set('brand')} placeholder="Brand" aria-label="Brand" />
      </div>
      <ErrorNote error={err} title="Could not save" />
      <div className="flex justify-end gap-2">
        <button type="button" className="btn btn-soft btn-sm" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn btn-navy btn-sm" disabled={busy || !f.name.trim() || toPaise(f.price) <= 0} onClick={save}>
          {busy ? <Spinner /> : 'Save'}
        </button>
      </div>
    </div>
  );
}

/** Merchant catalog: add (AI classifies HSN/SAC, category, brand), edit, delete. */
export default function CatalogManager({ merchantId, catalog, setCatalog, error }) {
  const { textModel } = useConfig();
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [editing, setEditing] = useState(null);
  const [recent, setRecent] = useState({}); // id -> fallback_reason from the create response
  const [delErr, setDelErr] = useState(null);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const add = async (e) => {
    e.preventDefault();
    if (!f.name.trim() || toPaise(f.price) <= 0) return;
    setBusy(true);
    setErr(null);
    try {
      const item = await api.addCatalogItem(merchantId, toBody(f));
      setRecent((r) => ({ ...r, [item.id]: { reason: item.fallback_reason || null, fresh: true } }));
      setCatalog((c) => [item, ...(c || [])]);
      setF(blank);
    } catch (ex) {
      setErr(ex);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item) => {
    if (!window.confirm(`Delete "${item.name}" from your catalog?`)) return;
    setDelErr(null);
    try {
      await api.deleteCatalogItem(merchantId, item.id);
      setCatalog((c) => c.filter((x) => x.id !== item.id));
    } catch (e) {
      setDelErr(e);
    }
  };

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
      <Card accent icon="add_box" title="Add a product or service" subtitle="Leave the code blank and AI fills in the HSN/SAC code, category and brand." className="xl:col-span-4">
        <AiWarning className="mb-3" what="Catalog classification" />
        <form className="space-y-3" onSubmit={add}>
          <Field label="Name">
            <input className="input" value={f.name} onChange={set('name')} placeholder="As printed on your bill" required />
          </Field>
          <Field label="Unit price (₹)">
            <input className="input tnum" inputMode="decimal" value={f.price} onChange={set('price')} placeholder="0.00" required />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="HSN / SAC (optional)">
              <input className="input font-mono" value={f.hsn_sac} onChange={set('hsn_sac')} placeholder="AI fills" />
            </Field>
            <Field label="Category (optional)">
              <input className="input" value={f.category} onChange={set('category')} placeholder="AI fills" />
            </Field>
          </div>
          <Field label="Brand (optional)">
            <input className="input" value={f.brand} onChange={set('brand')} placeholder="AI fills" />
          </Field>
          <ErrorNote error={err} title="Could not add item" />
          <button className="btn btn-navy w-full" disabled={busy || !f.name.trim() || toPaise(f.price) <= 0}>
            {busy ? <Spinner /> : <Icon name="auto_awesome" className="text-[18px] text-paytm-cyan" />}
            {busy ? 'Classifying…' : 'Add to catalog'}
          </button>
        </form>
      </Card>

      <Card icon="inventory_2" title="Catalog" subtitle={catalog ? `${catalog.length} item${catalog.length === 1 ? '' : 's'}` : undefined} className="xl:col-span-8">
        <ErrorNote error={error} title="Could not load catalog" className="mb-3" />
        <ErrorNote error={delErr} title="Could not delete" className="mb-3" />
        {!catalog ? (
          !error && (
            <div className="flex items-center gap-2 text-on-surface-variant">
              <Spinner /> Loading…
            </div>
          )
        ) : catalog.length === 0 ? (
          <Empty icon="inventory_2" title="No catalog items yet">
            Add the products and services you sell. They become one-tap buttons on the bill, already classified for GST.
          </Empty>
        ) : (
          <div className="space-y-2">
            {catalog.map((c) =>
              editing === c.id ? (
                <EditRow
                  key={c.id}
                  item={c}
                  merchantId={merchantId}
                  onCancel={() => setEditing(null)}
                  onSaved={(it) => {
                    setCatalog((list) => list.map((x) => (x.id === it.id ? it : x)));
                    setEditing(null);
                  }}
                />
              ) : (
                <div key={c.id} className={`flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center ${recent[c.id]?.fresh ? 'border-paytm-cyan/40 bg-paytm-cyan-light/40' : 'border-outline-variant bg-white'}`}>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-label-lg text-paytm-navy">{c.name}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-body-sm text-on-surface-variant">
                      {codeLabel(c) && <span className={`code-chip ${supplyOf(c) === 'services' ? 'code-services' : 'code-goods'}`}>{codeLabel(c)}</span>}
                      <span>{supplyOf(c)}</span>
                      {c.category && <span>· {titleCase(c.category)}</span>}
                      {c.brand && <span>· {titleCase(c.brand)}</span>}
                      <SourceBadge source={c.source} model={c.source === 'ai' ? textModel : null} reason={recent[c.id]?.reason || c.fallback_reason} />
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2 sm:justify-end">
                    <b className="tnum text-headline-sm text-paytm-navy">{inr(c.unit_price)}</b>
                    <span className="flex">
                      <button type="button" className="btn-icon" title="Edit" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c.id)}>
                        <Icon name="edit" className="text-[18px]" />
                      </button>
                      <button type="button" className="btn-icon hover:text-error-red" title="Delete" aria-label={`Delete ${c.name}`} onClick={() => remove(c)}>
                        <Icon name="delete" className="text-[18px]" />
                      </button>
                    </span>
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
