import { useState } from 'react';
import { absUrl, api } from '../api.js';
import { ago } from '../format.js';
import { useNow } from '../hooks.js';
import { Card, CopyButton, Empty, ErrorNote, Field, Icon, Spinner } from './ui.jsx';

function Provisioning({ device, onDone }) {
  const p = device.provisioning || {};
  const token = device.token || p.token;
  const rows = [
    ['Device ID', p.device_id || device.id],
    ['Token', token],
    ['Host', p.host],
    ['Port', p.port],
  ].filter(([, v]) => v !== undefined && v !== null && v !== '');
  return (
    <div className="rounded-xl border-2 border-paytm-cyan bg-paytm-cyan-light/50 p-4" role="status">
      <div className="flex items-start gap-3">
        <Icon name="key" className="text-[24px] text-paytm-cyan-dark" />
        <div className="min-w-0">
          <div className="text-headline-sm text-paytm-navy">Provisioning details for {device.name || device.id}</div>
          <div className="text-body-sm text-amber-800">
            <b>The token is shown only once.</b> Flash it to the Soundbox now or copy it somewhere safe. Rotate it if it leaks.
          </div>
        </div>
      </div>
      <dl className="mt-3 space-y-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex flex-col gap-1 rounded-lg border border-outline-variant bg-white p-2 sm:flex-row sm:items-center">
            <dt className="w-24 shrink-0 text-label-sm text-on-surface-variant">{k}</dt>
            <dd className="min-w-0 flex-1 break-all font-mono text-body-sm text-paytm-navy">{String(v)}</dd>
            <CopyButton text={String(v)} />
          </div>
        ))}
      </dl>
      <div className="mt-3 flex flex-wrap gap-2">
        {p.sim_url && (
          <a className="btn btn-navy btn-sm" href={absUrl(p.sim_url)} target="_blank" rel="noreferrer">
            <Icon name="open_in_new" className="text-[16px] text-paytm-cyan" />
            Open browser simulator
          </a>
        )}
        <button type="button" className="btn btn-outline btn-sm" onClick={onDone}>
          I've saved the token
        </button>
      </div>
      {p.sim_url && <p className="mt-2 text-body-sm text-on-surface-variant">The simulator acts as this Soundbox in a browser tab. Its link contains the token, so treat it like a password.</p>}
    </div>
  );
}

/** Soundboxes owned by the merchant: pair, rotate token, remove. */
export default function DeviceManager({ devices, error, reload }) {
  const now = useNow(10000);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [fresh, setFresh] = useState(null);

  const run = async (key, fn) => {
    setBusy(key);
    setErr(null);
    try {
      return await fn();
    } catch (e) {
      setErr(e);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const pair = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    const d = await run('pair', () => api.createDevice(name.trim()));
    if (d) {
      setFresh(d);
      setName('');
      reload();
    }
  };
  const rotate = async (d) => {
    if (!window.confirm(`Rotate the token for ${d.name || d.id}? The Soundbox disconnects until it gets the new token.`)) return;
    const r = await run(`rotate:${d.id}`, () => api.rotateDeviceToken(d.id));
    if (r) {
      setFresh(r);
      reload();
    }
  };
  const remove = async (d) => {
    if (!window.confirm(`Remove ${d.name || d.id}? It stops receiving bills and ads.`)) return;
    const ok = await run(`del:${d.id}`, async () => {
      await api.deleteDevice(d.id);
      return true;
    });
    if (ok) {
      if (fresh?.id === d.id) setFresh(null);
      reload();
    }
  };

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
      <div className="space-y-6 xl:col-span-5">
        <Card accent icon="speaker" title="Pair new Soundbox" subtitle="Creates a device ID and a secret token for an ESP32 Soundbox or the browser simulator.">
          <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={pair}>
            <Field label="Name" className="flex-1">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Front counter" maxLength={60} />
            </Field>
            <button className="btn btn-navy" disabled={busy === 'pair' || !name.trim()}>
              {busy === 'pair' ? <Spinner /> : <Icon name="add_link" className="text-[18px] text-paytm-cyan" />}
              Pair
            </button>
          </form>
        </Card>
        {fresh && <Provisioning device={fresh} onDone={() => setFresh(null)} />}
      </div>

      <Card icon="devices" title="Your Soundboxes" subtitle={devices ? `${devices.filter((d) => d.online).length} online of ${devices.length}` : undefined} className="xl:col-span-7">
        <ErrorNote error={error} title="Could not load devices" className="mb-3" />
        <ErrorNote error={err} title="Device action failed" className="mb-3" />
        {!devices ? (
          !error && (
            <div className="flex items-center gap-2 text-on-surface-variant">
              <Spinner /> Loading…
            </div>
          )
        ) : devices.length === 0 ? (
          <Empty icon="speaker" title="No Soundbox paired">
            Pair a Soundbox to show bill QR codes at the counter, announce payments and play the ads that pay your MDR.
          </Empty>
        ) : (
          <div className="space-y-2">
            {devices.map((d) => (
              <div key={d.id} className="flex flex-col gap-2 rounded-xl border border-outline-variant bg-surface-subtle p-3 sm:flex-row sm:items-center">
                <div className="flex min-w-0 flex-1 items-start gap-2.5">
                  <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${d.online ? 'bg-success-green' : 'bg-rose-500'}`} title={d.online ? 'Online' : 'Offline'} />
                  <div className="min-w-0">
                    <div className="truncate text-label-lg text-paytm-navy">{d.name || d.id}</div>
                    <div className="font-mono text-[11px] text-on-surface-variant">
                      {d.id}
                      {d.fw ? ` · fw ${d.fw}` : ''}
                      {d.rssi !== null && d.rssi !== undefined ? ` · ${d.rssi} dBm` : ''}
                    </div>
                    <div className="text-body-sm text-on-surface-variant">
                      {d.online ? 'Online' : 'Offline'} · last seen {ago(d.last_seen, now)}
                      {d.created_at ? ` · paired ${ago(d.created_at, now)}` : ''}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button type="button" className="btn btn-outline btn-sm" disabled={!!busy} onClick={() => rotate(d)}>
                    {busy === `rotate:${d.id}` ? <Spinner /> : <Icon name="autorenew" className="text-[16px]" />}
                    Rotate token
                  </button>
                  <button type="button" className="btn btn-danger btn-sm" disabled={!!busy} onClick={() => remove(d)}>
                    {busy === `del:${d.id}` ? <Spinner /> : <Icon name="link_off" className="text-[16px]" />}
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
