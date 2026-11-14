import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, qrSrc } from '../api.js';
import { inr, LANGS, langLabel, num, pct, time, titleCase, toPaise, toRupeeInput } from '../format.js';
import { usePoll } from '../hooks.js';
import { useAccount, useConfig } from '../session.jsx';
import { AiWarning, Card, ChipInput, Empty, ErrorNote, Icon, PageHead, Pill, Progress, SourceBadge, Spinner, TestModeBadge, Toggle } from '../components/ui.jsx';
import HoldToTalk from '../components/HoldToTalk.jsx';
import GeofenceMap from '../components/GeofenceMap.jsx';
import LocationPicker from '../components/LocationPicker.jsx';
import CreativePreview from '../components/CreativePreview.jsx';

const TOPUP_PRESETS = [10000, 30000, 100000, 500000];
const DEFAULTS = { bid: '1.20', cap: '50' };

/* ------------------------------------------------------------------ wallet */

function TopUpStatus({ topup, onPaid }) {
  const [t, setT] = useState(topup);
  useEffect(() => setT(topup), [topup]);
  useEffect(() => {
    if (!t || t.status !== 'pending') return undefined;
    const iv = setInterval(async () => {
      try {
        const next = await api.topupStatus(t.id);
        setT(next);
        if (next.status !== 'pending') onPaid();
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => clearInterval(iv);
  }, [t, onPaid]);
  if (!t) return null;
  const payable = t.status === 'pending' && (t.qr_data || t.checkout_url);
  return (
    <div className={`rounded-xl border p-3 ${t.status === 'paid' ? 'border-emerald-200 bg-emerald-50' : t.status === 'pending' ? 'border-paytm-cyan/40 bg-paytm-cyan-light/50' : 'border-rose-200 bg-rose-50'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 text-body-sm">
        <span>
          Top-up <b className="tnum">{inr(t.amount_paise)}</b> <span className="font-mono text-[11px] text-on-surface-variant">{t.id}</span>
        </span>
        <Pill status={t.status} dot />
      </div>
      {payable && (
        <div className="mt-2 flex flex-col items-center gap-3 sm:flex-row sm:items-start">
          {t.qr_data && <img src={qrSrc(t.qr_data, 5)} alt="UPI QR to pay the top-up" width="150" height="150" className="h-[150px] w-[150px] rounded-lg border border-outline bg-white p-1" />}
          <div className="space-y-2 text-body-sm">
            <p>Scan with any UPI app to pay. This updates automatically when the payment arrives.</p>
            {t.checkout_url && (
              <a className="btn btn-outline btn-sm" href={t.checkout_url} target="_blank" rel="noreferrer">
                <Icon name="open_in_new" className="text-[16px]" />
                Open payment page
              </a>
            )}
            <div className="flex items-center gap-1.5 text-on-surface-variant">
              <Spinner /> Waiting for payment…
            </div>
          </div>
        </div>
      )}
      {t.status === 'paid' && <div className="mt-1 text-body-sm text-emerald-800">Credited to your wallet.</div>}
    </div>
  );
}

function Wallet({ advertiser, reload }) {
  const { isMock } = useConfig();
  const [amount, setAmount] = useState('300');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [topup, setTopup] = useState(null);
  const history = usePoll(() => api.topups(advertiser.id), 0, [advertiser.id]);
  const w = advertiser.wallet || {};
  const st = advertiser.stats || {};
  const balance = w.balance_paise ?? advertiser.balance_paise ?? 0;
  const cap = w.daily_cap_total_paise ?? 0;
  const spentToday = w.spent_today_paise ?? 0;

  const onPaid = useCallback(() => {
    reload();
    history.reload();
  }, [reload, history]);

  const submit = async () => {
    const p = toPaise(amount);
    if (p < 100) return;
    setBusy(true);
    setErr(null);
    try {
      const t = await api.topup(advertiser.id, p);
      setTopup(t);
      if (t.status !== 'pending') onPaid();
      else history.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      id="wallet"
      className="scroll-mt-24"
      icon="account_balance_wallet"
      title="Prepaid wallet"
      actions={
        balance > 0 ? (
          <Pill tone="good" dot>
            Funded
          </Pill>
        ) : (
          <Pill tone="warn" dot>
            Empty
          </Pill>
        )
      }
    >
      <p className="mb-4 text-body-sm text-slate-500">You're charged only for verified plays on paid bills. Funds are held when an ad is scheduled and released if the play isn't verified or the bill isn't paid.</p>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3 rounded-xl border border-paytm-cyan/20 bg-gradient-to-br from-paytm-cyan-light/70 to-slate-50 p-4">
        <div>
          <span className="block text-[10px] font-bold uppercase tracking-wider text-slate-500">Available balance</span>
          <span className="tnum text-headline-xl text-paytm-navy">{inr(balance)}</span>
          {w.reserved_paise > 0 && <span className="block text-body-sm text-on-surface-variant">{inr(w.reserved_paise)} held for pending plays</span>}
        </div>
        <div className="text-right">
          <span className="block text-label-sm text-slate-500">Burn per play</span>
          <span className="tnum text-label-md font-bold text-paytm-navy">{w.burn_per_play_paise ? `~${inr(w.burn_per_play_paise)} / play` : 'No plays yet'}</span>
        </div>
      </div>

      <div className="mb-4 space-y-1.5">
        <div className="flex justify-between gap-2 text-label-sm text-slate-600">
          <span>Spent today</span>
          <span className="tnum font-bold text-slate-800">
            {inr(spentToday)} / {cap ? `${inr(cap)} daily cap` : 'no active cap'}
          </span>
        </div>
        <Progress value={spentToday} max={cap || 1} label="Spent today against daily cap" />
        <div className="flex justify-between gap-2 text-label-sm text-slate-500">
          <span>{cap ? `${pct((spentToday / cap) * 100)} of today's cap used` : 'Deploy a campaign to set a cap'}</span>
          <span className="font-semibold text-paytm-navy">{w.est_plays_remaining !== null && w.est_plays_remaining !== undefined ? `Est. ${num(w.est_plays_remaining)} plays remain` : ''}</span>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-3 gap-2 rounded-xl border border-slate-200/80 bg-slate-50 px-2 py-3 text-center">
        <div>
          <span className="block text-label-sm text-slate-500">Verified plays</span>
          <span className="tnum text-headline-sm text-paytm-navy">{num(st.plays ?? 0)}</span>
        </div>
        <div className="border-x border-slate-200">
          <span className="block text-label-sm text-slate-500">Total spend</span>
          <span className="tnum text-headline-sm text-paytm-cyan-dark">{inr(w.lifetime_spend_paise ?? st.spend_paise ?? 0)}</span>
        </div>
        <div>
          <span className="block text-label-sm text-slate-500">Offer claims</span>
          <span className="tnum text-headline-sm text-paytm-navy">{num(st.claims ?? 0)}</span>
        </div>
      </div>
      {st.released_plays > 0 && <p className="-mt-2 mb-3 text-body-sm text-on-surface-variant">{num(st.released_plays)} unverified plays were released, not charged.</p>}

      <div className="space-y-2">
        <div className="grid grid-cols-4 gap-1.5">
          {TOPUP_PRESETS.map((p) => {
            const on = toPaise(amount) === p;
            return (
              <button
                key={p}
                type="button"
                className={`rounded-lg border py-1.5 text-label-sm transition-colors ${on ? 'border-paytm-cyan bg-paytm-cyan-light font-bold text-paytm-navy' : 'border-slate-200 bg-slate-50 font-semibold text-slate-700 hover:bg-slate-100'}`}
                onClick={() => setAmount(toRupeeInput(p))}
              >
                +{inr(p, { decimals: 0 })}
              </button>
            );
          })}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-label-sm font-bold text-slate-400">₹</span>
            <input
              id="topup-amount"
              className="input tnum pl-7 font-bold"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-label="Top-up amount in rupees"
            />
          </div>
          <button type="button" className="btn btn-navy" disabled={busy || toPaise(amount) < 100} onClick={submit}>
            {busy ? <Spinner /> : <Icon name="bolt" className="text-[16px] text-paytm-cyan" />}
            {isMock ? 'Top up (test mode)' : 'Top Up with UPI'}
          </button>
        </div>
        {isMock && (
          <div className="flex items-center gap-2 text-body-sm text-on-surface-variant">
            <TestModeBadge /> The mock provider credits test top-ups without real payment.
          </div>
        )}
        <ErrorNote error={err} title="Top-up failed" />
        <TopUpStatus topup={topup} onPaid={onPaid} />
      </div>

      {history.data?.length > 0 && (
        <details className="mt-4 rounded-xl border border-outline-variant">
          <summary className="cursor-pointer px-3 py-2 text-label-md text-paytm-navy">
            Top-up history ({history.data.length}) · lifetime {inr(w.lifetime_topup_paise ?? 0)}
          </summary>
          <ul className="divide-y divide-outline-variant border-t border-outline-variant text-body-sm">
            {history.data.slice(0, 10).map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="text-on-surface-variant">{time(t.created_at)}</span>
                <span className="tnum font-semibold">{inr(t.amount_paise)}</span>
                <Pill status={t.status} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

/* --------------------------------------------------------------- builder */

function Geofence({ center, setCenter, radius, setRadius, enabled }) {
  const [geo, setGeo] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!enabled || !center) return undefined;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        setGeo(await api.geoSoundboxes(center.lat, center.lng, radius));
        setErr(null);
      } catch (e) {
        setErr(e);
      } finally {
        setLoading(false);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [center, radius, enabled]);

  if (!center) {
    return (
      <div>
        <p className="mb-2 text-body-sm text-on-surface-variant">Pick the centre of the area to target.</p>
        <LocationPicker lat={null} lng={null} onChange={setCenter} required height={220} />
      </div>
    );
  }
  const list = geo?.soundboxes || [];
  return (
    <div className="space-y-3">
      <input
        type="range"
        min="100"
        max="5000"
        step="50"
        value={radius}
        onChange={(e) => setRadius(Number(e.target.value))}
        className="h-2 w-full cursor-pointer appearance-none rounded-lg bg-slate-200 accent-paytm-cyan"
        aria-label="Geofence radius in metres"
      />
      <GeofenceMap lat={center.lat} lng={center.lng} radius={radius} onChange={setCenter} soundboxes={list} height={240} />
      <div className="flex flex-wrap items-center justify-between gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 shadow-sm">
        <span className="flex items-center gap-2 text-label-sm text-slate-600">
          {loading ? <Spinner className="text-paytm-cyan-dark" /> : <span className="h-2 w-2 rounded-full bg-paytm-cyan-dark" />}
          {geo ? (
            <span>
              <strong className="font-bold text-paytm-navy">
                {num(geo.count)} merchant Soundbox{geo.count === 1 ? '' : 'es'}
              </strong>{' '}
              in radius · {num(geo.online)} online
            </span>
          ) : (
            'Counting Soundboxes…'
          )}
        </span>
        <span className="font-mono text-[10px] text-slate-500">
          {center.lat.toFixed(5)}° N, {center.lng.toFixed(5)}° E
        </span>
      </div>
      <ErrorNote error={err} title="Could not count Soundboxes" />
      {geo && geo.count === 0 && <div className="note note-info">No merchant Soundboxes in this radius yet. Widen the radius or move the centre; the campaign can still be saved.</div>}
      {list.length > 0 && (
        <ul className="max-h-40 divide-y divide-outline-variant overflow-y-auto rounded-lg border border-outline-variant bg-white text-body-sm">
          {list
            .slice()
            .sort((a, b) => a.distance_m - b.distance_m)
            .map((s) => (
              <li key={s.device_id} className="flex items-center gap-2 px-3 py-1.5">
                <span className={`h-2 w-2 shrink-0 rounded-full ${s.online ? 'bg-success-green' : 'bg-slate-300'}`} title={s.online ? 'online' : 'offline'} />
                <span className="font-mono text-[11px] text-on-surface-variant">{s.device_id}</span>
                <span className="min-w-0 flex-1 truncate font-semibold text-paytm-navy">{s.merchant_name}</span>
                {s.category && <span className="hidden text-on-surface-variant sm:inline">{titleCase(s.category)}</span>}
                <span className="tnum text-on-surface-variant">{s.distance_m >= 1000 ? `${(s.distance_m / 1000).toFixed(1)} km` : `${Math.round(s.distance_m)} m`}</span>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

function CampaignBuilder({ advertiser, onCreated }) {
  const { textModel, ttsModel, aiConfigured } = useConfig();
  const isBrand = advertiser.type === 'brand';
  const [inputMode, setInputMode] = useState('type'); // 'type' (English text) | 'speak'
  const [prompt, setPrompt] = useState('');
  const [speechLang, setSpeechLang] = useState('en-IN');
  const [name, setName] = useState('');
  const [lang, setLang] = useState('en');
  const [bid, setBid] = useState(DEFAULTS.bid);
  const [tagBid, setTagBid] = useState(''); // empty = 75% of the full-ad bid
  const [cap, setCap] = useState(DEFAULTS.cap);
  const hasHome = advertiser.lat !== null && advertiser.lat !== undefined;
  const [geofence, setGeofence] = useState(!isBrand || hasHome);
  const [center, setCenter] = useState(hasHome ? { lat: advertiser.lat, lng: advertiser.lng } : null);
  const [radius, setRadius] = useState(500);
  const [targets, setTargets] = useState([]);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [touched, setTouched] = useState(false);

  const bidP = toPaise(bid);
  const capP = toPaise(cap);
  const tagP = tagBid.trim() ? toPaise(tagBid) : null;
  const problems = [
    prompt.trim().length < 3 && 'Describe the offer (type it or hold to talk).',
    name.trim().length < 2 && 'Give the campaign a name.',
    bidP <= 0 && 'Set a bid.',
    capP > 0 && capP < bidP && 'The daily cap must be at least one bid.',
    tagP !== null && (tagP <= 0 || tagP >= bidP) && 'The sponsor tag must cost less than the full ad.',
    geofence && !center && 'Pick the geofence centre on the map.',
  ].filter(Boolean);

  const submit = async (deploy) => {
    setTouched(true);
    if (problems.length) return;
    setBusy(deploy ? 'deploy' : 'draft');
    setErr(null);
    try {
      const body = {
        kind: 'audio',
        name: name.trim(),
        prompt: prompt.trim(),
        lang,
        radius_m: geofence ? radius : 0,
        target_categories: targets,
        bid_paise: bidP,
        ...(tagP !== null ? { tag_bid_paise: tagP } : {}),
        daily_cap_paise: capP,
        deploy,
        ...(geofence && center ? { lat: center.lat, lng: center.lng } : {}),
      };
      const c = await api.createCampaign(body);
      onCreated(c);
      setPrompt('');
      setName('');
      setTouched(false);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  };

  const balance = advertiser.wallet?.balance_paise ?? advertiser.balance_paise ?? 0;

  return (
    <Card accent>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Icon name="auto_awesome" className="text-[22px] text-paytm-cyan-dark" />
            <h2 className="text-headline-md text-paytm-navy">Create an ad in 30 seconds</h2>
          </div>
          <p className="mt-1 text-body-md text-slate-600">Type your offer in English or say it. AI writes the ad in the language you pick, voices it and designs the counter-screen banner.</p>
        </div>
        {aiConfigured && (
          <span className="shrink-0 rounded-md border border-paytm-cyan/30 bg-paytm-cyan-light px-2.5 py-1 text-label-sm font-bold text-paytm-navy" title={ttsModel ? `Voice: ${ttsModel}` : undefined}>
            {textModel || 'AI'}
          </span>
        )}
      </div>
      <AiWarning className="mb-4" what="Ad copy and voice-over" />

      <div className="mb-3 grid grid-cols-2 gap-2 rounded-xl border border-slate-200/80 bg-slate-100 p-1.5" role="tablist" aria-label="How you describe the offer">
        {[
          ['type', 'keyboard', 'Type in English'],
          ['speak', 'mic', 'Hold to talk'],
        ].map(([k, ic, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={inputMode === k}
            onClick={() => setInputMode(k)}
            className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-label-md transition-all ${inputMode === k ? 'border border-slate-200/60 bg-white font-bold text-paytm-navy shadow-sm' : 'font-semibold text-slate-600 hover:text-paytm-navy'}`}
          >
            <Icon name={ic} className={`text-[18px] ${inputMode === k ? 'text-paytm-cyan-dark' : ''}`} />
            {label}
          </button>
        ))}
      </div>

      <div className="mb-6 rounded-xl border border-slate-200 bg-slate-50 p-3.5 transition-all focus-within:border-paytm-cyan focus-within:bg-white focus-within:ring-2 focus-within:ring-paytm-cyan">
        <textarea
          className="w-full resize-none border-0 bg-transparent p-0 text-body-md text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0"
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          maxLength={1000}
          lang={inputMode === 'type' ? 'en' : undefined}
          placeholder={
            inputMode === 'type'
              ? 'Write your offer in English, for example: 20% off all mixer grinders this week at Sharma Electronics, MG Road'
              : 'Hold the button and say your offer in any language; the words appear here and you can edit them'
          }
          aria-label="Describe your offer"
        />
        <div className="mt-2 flex flex-col gap-2 border-t border-slate-200/60 pt-2 sm:flex-row sm:items-center sm:justify-between">
          {inputMode === 'speak' ? (
            <>
              <HoldToTalk speechLang={speechLang} onText={(t) => setPrompt((p) => (p.trim() ? `${p.trim()} ${t}` : t))} />
              <label className="flex shrink-0 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1 shadow-sm">
                <Icon name="translate" className="text-[15px] text-slate-500" />
                <select className="border-0 bg-transparent py-0 pl-0 pr-7 text-label-sm font-medium text-slate-700 focus:ring-0" value={speechLang} onChange={(e) => setSpeechLang(e.target.value)} aria-label="Language you speak in">
                  {LANGS.map((l) => (
                    <option key={l.value} value={l.bcp47}>Speak {l.label}</option>
                  ))}
                </select>
              </label>
            </>
          ) : (
            <span className="flex items-center gap-1.5 text-label-sm text-slate-600">
              <Icon name="translate" className="text-[16px] text-paytm-cyan-dark" />
              English brief → ad written and voiced in
            </span>
          )}
          {inputMode === 'type' && (
            <label className="flex shrink-0 items-center gap-1.5 rounded-md border border-paytm-cyan/40 bg-paytm-cyan-light px-2.5 py-1 shadow-sm">
              <select className="border-0 bg-transparent py-0 pl-0 pr-7 text-label-sm font-bold text-paytm-navy focus:ring-0" value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Language of the generated ad">
                {LANGS.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>
      {lang !== 'en' && (
        <p className="-mt-4 mb-6 text-label-sm text-slate-500">
          AI translates your brief and writes the ad in {LANGS.find((l) => l.value === lang)?.label || lang}. You can check the script and listen before it goes live.
        </p>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <div className="rounded-xl border border-slate-200/80 bg-slate-50 p-3">
          <label className="mb-1 block text-label-sm text-slate-500" htmlFor="cmp-name">
            Campaign name
          </label>
          <input id="cmp-name" className="input input-sm font-medium" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </div>
        <div className="rounded-xl border border-slate-200/80 bg-slate-50 p-3">
          <label className="mb-1 block text-label-sm text-slate-500" htmlFor="cmp-lang">
            Audio language
          </label>
          <select id="cmp-lang" className="input input-sm font-medium" value={lang} onChange={(e) => setLang(e.target.value)}>
            {LANGS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
        <div className="rounded-xl border border-slate-200/80 bg-slate-50 p-3">
          <label className="mb-1 block text-label-sm text-slate-500" htmlFor="cmp-bid">
            Bid / verified play
          </label>
          <div className="flex items-center rounded-lg border border-input-border bg-white px-2 focus-within:border-primary">
            <span className="mr-1 text-label-sm font-bold text-paytm-cyan-dark">₹</span>
            <input id="cmp-bid" className="tnum w-full min-w-0 border-0 bg-transparent px-0 py-1.5 text-label-md font-semibold focus:ring-0" inputMode="decimal" value={bid} onChange={(e) => setBid(e.target.value)} />
          </div>
        </div>
        {(
          <div className="rounded-xl border border-slate-200/80 bg-slate-50 p-3">
            <label className="mb-1 block text-label-sm text-slate-500" htmlFor="cmp-tag" title="Busy hours: only a 1-second 'Sponsored by ...' line after the payment message">
              Sponsor tag (busy hour)
            </label>
            <div className="flex items-center rounded-lg border border-input-border bg-white px-2 focus-within:border-primary">
              <span className="mr-1 text-label-sm font-bold text-amber-600">₹</span>
              <input id="cmp-tag" className="tnum w-full min-w-0 border-0 bg-transparent px-0 py-1.5 text-label-md font-semibold focus:ring-0" inputMode="decimal"
                value={tagBid} onChange={(e) => setTagBid(e.target.value)} placeholder={bidP > 0 ? (Math.max(1, Math.round(bidP * 0.75)) / 100).toFixed(2) : ''} />
            </div>
          </div>
        )}
        <div className="rounded-xl border border-slate-200/80 bg-slate-50 p-3">
          <label className="mb-1 block text-label-sm text-slate-500" htmlFor="cmp-cap">
            Daily cap
          </label>
          <div className="flex items-center rounded-lg border border-input-border bg-white px-2 focus-within:border-primary">
            <span className="mr-1 text-label-sm font-bold text-paytm-navy">₹</span>
            <input id="cmp-cap" className="tnum w-full min-w-0 border-0 bg-transparent px-0 py-1.5 text-label-md font-semibold focus:ring-0" inputMode="decimal" value={cap} onChange={(e) => setCap(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="mb-6 space-y-3">
        <details className="rounded-xl border border-slate-200/80 bg-slate-50">
          <summary className="cursor-pointer px-3 py-2 text-label-md text-paytm-navy">Target merchant categories {targets.length ? `(${targets.length})` : '(all)'}</summary>
          <div className="border-t border-slate-200/80 p-3">
            <ChipInput values={targets} onChange={setTargets} placeholder="Leave empty for all categories" />
          </div>
        </details>
      </div>

      <div className="space-y-3 rounded-xl border border-slate-200/90 bg-slate-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Icon name="radar" className="text-[20px] text-paytm-cyan-dark" />
            <span className="text-headline-sm text-paytm-navy">Soundbox geofence</span>
          </div>
          {geofence ? (
            <div className="flex items-center gap-2">
              <span className="text-label-sm text-slate-500">Radius:</span>
              <span className="tnum text-label-md font-extrabold text-paytm-cyan-dark">{radius >= 1000 ? `${(radius / 1000).toFixed(radius % 1000 ? 2 : 0)} km` : `${radius} m`}</span>
            </div>
          ) : null}
        </div>
        {isBrand && <Toggle checked={geofence} onChange={setGeofence} label="Limit to an area" hint="Off: the campaign can run on any Soundbox that matches your categories and keywords." />}
        {geofence && <Geofence center={center} setCenter={setCenter} radius={radius} setRadius={setRadius} enabled={geofence} />}
      </div>

      {balance <= 0 && (
        <div className="note note-warn mt-4 flex items-start gap-2">
          <Icon name="account_balance_wallet" className="text-[18px]" />
          Your wallet is empty. You can deploy now, but ads only play once you top up.
        </div>
      )}
      {touched && problems.length > 0 && (
        <ul className="note note-warn mt-4 list-disc pl-7">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <ErrorNote error={err} title="Could not create campaign" className="mt-4" />

      <div className="mt-4 flex flex-col items-center justify-between gap-4 border-t border-slate-100 pt-4 sm:flex-row">
        <div className="flex items-center gap-2 text-label-sm text-slate-600">
          <Icon name="verified_user" className="text-[18px] text-paytm-cyan-dark" />
          <span>A play is billed only when the Soundbox confirms at least 80% of the ad played.</span>
        </div>
        <div className="flex w-full items-center gap-3 sm:w-auto">
          <button type="button" className="btn btn-soft flex-1 sm:flex-none" disabled={!!busy} onClick={() => submit(false)}>
            {busy === 'draft' && <Spinner />}
            Save Draft
          </button>
          <button type="button" className="btn btn-cyan flex-[2] sm:flex-none" disabled={!!busy} onClick={() => submit(true)}>
            {busy === 'deploy' ? <Spinner /> : <Icon name="bolt" className="text-[18px]" />}
            Deploy Campaign Now
          </button>
        </div>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------- preview + list */

function Preview({ campaign, advertiser, onChanged }) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [lang, setLang] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => {
    setOpen(false);
    setErr(null);
    setPrompt(campaign?.prompt || '');
    setLang(campaign?.lang || 'en');
  }, [campaign?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const regen = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = {};
      if (prompt.trim() && prompt.trim() !== campaign.prompt) body.prompt = prompt.trim();
      if (lang && lang !== campaign.lang) body.lang = lang;
      onChanged(await api.regenerateCampaign(campaign.id, body));
      setOpen(false);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      icon="preview"
      title="Creative preview"
      actions={campaign && <span className="max-w-[200px] truncate text-label-sm font-medium text-slate-500">{campaign.name} · {campaign.status}</span>}
    >
      {!campaign ? (
        <Empty icon="graphic_eq" title="No creative yet">
          Create a campaign and its banner, script and voice-over appear here.
        </Empty>
      ) : (
        <div className="space-y-3">
          {campaign.status === 'generating' && (
            <div className="flex items-center gap-3 rounded-xl border border-paytm-cyan/30 bg-paytm-cyan-light/60 p-4 text-body-sm text-paytm-navy">
              <Spinner className="text-paytm-cyan-dark" />
              AI is writing the copy and recording the voice-over…
            </div>
          )}
          {campaign.status === 'failed' && (
            <div className="note note-bad">
              <b>Generation failed.</b> {campaign.error || 'No reason was given.'}
            </div>
          )}
          {campaign.creative && <CreativePreview creative={campaign.creative} advertiserName={advertiser.name} brief={campaign.prompt} />}
          {campaign.status !== 'generating' && (
            <div className="space-y-2">
              {!open ? (
                <button type="button" className="btn btn-outline btn-sm" onClick={() => setOpen(true)}>
                  <Icon name="refresh" className="text-[16px] text-paytm-cyan-dark" />
                  Regenerate
                </button>
              ) : (
                <div className="space-y-2 rounded-xl border border-outline-variant p-3">
                  <textarea className="input min-h-[80px]" value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={1000} aria-label="Prompt for regeneration" />
                  <div className="flex flex-wrap items-center gap-2">
                    <select className="input input-sm w-auto" value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Audio language">
                      {LANGS.map((l) => (
                        <option key={l.value} value={l.value}>
                          {l.label}
                        </option>
                      ))}
                    </select>
                    <button type="button" className="btn btn-navy btn-sm" disabled={busy || prompt.trim().length < 3} onClick={regen}>
                      {busy ? <Spinner /> : <Icon name="auto_awesome" className="text-[16px] text-paytm-cyan" />}
                      Regenerate creative
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
              <ErrorNote error={err} title="Regenerate failed" />
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function CampaignRow({ c, selected, onSelect, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const setStatus = async (status) => {
    setBusy(true);
    setErr(null);
    try {
      onChanged(await api.updateCampaign(c.id, { status }));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const action =
    c.status === 'active'
      ? ['Pause', 'paused']
      : c.status === 'paused'
        ? ['Resume', 'active']
        : c.status === 'draft'
          ? ['Deploy', 'active']
          : null;
  const st = c.stats || {};
  return (
    <div
      className={`cursor-pointer space-y-3 rounded-xl border p-3.5 transition-colors ${selected ? 'border-primary bg-surface-ice' : 'border-slate-200/80 bg-slate-50 hover:border-primary/50'}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && e.target === e.currentTarget && onSelect()}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[16px] font-bold text-paytm-navy">{c.name}</span>
            <Pill status={c.status} dot />
          </div>
          <p className="mt-0.5 text-label-sm text-slate-600">
            Ad {inr(c.bid_paise)} · Sponsor tag {inr(c.tag_bid_paise)} · Cap {c.daily_cap_paise ? `${inr(c.daily_cap_paise, { decimals: 0 })}/day` : 'none'} · {c.lat !== null && c.lat !== undefined && c.radius_m ? `Geofence ${c.radius_m >= 1000 ? `${(c.radius_m / 1000).toFixed(1)} km` : `${c.radius_m} m`}` : 'No geofence'} · {langLabel(c.lang)}
          </p>
        </div>
        {action && (
          <button
            type="button"
            className="btn btn-outline btn-sm shrink-0"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              setStatus(action[1]);
            }}
          >
            {busy && <Spinner />}
            {action[0]}
          </button>
        )}
      </div>
      {c.status === 'failed' && c.error && <div className="note note-bad">{c.error}</div>}
      {c.creative && (
        <div className="flex flex-wrap gap-1.5">
          <SourceBadge label="Copy" source={c.creative.source} model={c.creative.model} reason={c.creative.fallback_reason} />
          <SourceBadge label="Voice" source={c.creative.voice_source} reason={c.creative.voice_fallback_reason} />
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border border-slate-200/70 bg-white px-3 py-2 text-label-sm">
        <span>
          <b className="tnum text-paytm-navy">{num(st.plays ?? 0)}</b> <span className="text-slate-500">verified play{st.plays === 1 ? '' : 's'}</span>
        </span>
        <span className="text-slate-300">|</span>
        <span>
          <b className="tnum text-paytm-cyan-dark">{inr(st.spent_today_paise ?? 0)}</b> <span className="text-slate-500">spent today</span>
        </span>
        <span className="text-slate-300">|</span>
        <span>
          <b className="tnum text-paytm-navy">{num(st.tag_plays ?? 0)}</b> <span className="text-slate-500">sponsor line{st.tag_plays === 1 ? '' : 's'}</span>
        </span>
      </div>
      <ErrorNote error={err} title="Update failed" />
    </div>
  );
}

// GST verification + Rs 200 deposit gate: campaigns wait as "pending verification" until both are done.
function KycBanner({ advertiser, onChanged }) {
  const k = advertiser.kyc;
  const [gst, setGst] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (!k) return null;
  if (k.can_go_live) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-body-sm text-emerald-800">
        <Icon name="verified" className="text-[18px] text-success-green" />
        GST verified <span className="font-mono">{k.gstin}</span> · your ads can go live
      </div>
    );
  }
  const resubmit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.updateAdvertiser(advertiser.id, { gstin: gst.trim().toUpperCase() });
      setGst('');
      onChanged?.();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const rejected = k.status === 'rejected';
  return (
    <div className={`rounded-xl border p-4 ${rejected ? 'border-rose-300 bg-rose-50' : 'border-amber-300 bg-amber-50'}`}>
      <div className="flex items-start gap-3">
        <Icon name={rejected ? 'gpp_bad' : 'pending_actions'} className={`text-[24px] ${rejected ? 'text-rose-600' : 'text-amber-600'}`} />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="text-label-lg text-on-surface">Your ads aren't live yet</div>
          <ul className="list-disc pl-5 text-body-sm text-on-surface">
            {k.blockers.map((b) => <li key={b}>{b}</li>)}
          </ul>
          <div className="text-body-sm text-on-surface-variant">
            GSTIN on file: <span className="font-mono">{k.gstin || 'none'}</span>. You can build and preview campaigns now; they go live automatically once this is done.
          </div>
          {rejected && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <input className="input input-sm w-52 font-mono uppercase" maxLength={15} placeholder="Correct GSTIN" value={gst} onChange={(e) => setGst(e.target.value)} />
              <button type="button" className="btn btn-navy btn-sm" disabled={busy || gst.trim().length !== 15} onClick={resubmit}>
                {busy && <Spinner />} Resubmit for verification
              </button>
            </div>
          )}
          {err && <div className="text-body-sm text-error-red">{err.message}</div>}
        </div>
      </div>
    </div>
  );
}

export default function Advertiser() {
  const { account: advertiser, error, reload } = useAccount();
  const [selectedId, setSelectedId] = useState(null);
  const [fast, setFast] = useState(false);
  const campaigns = usePoll(() => api.campaigns(), fast ? 2000 : 10000, [fast]);
  const list = campaigns.data || [];

  useEffect(() => {
    setFast(list.some((c) => c.status === 'generating'));
  }, [list]);

  const selected = useMemo(() => list.find((c) => c.id === selectedId) || list[0] || null, [list, selectedId]);

  const upsert = (c) => {
    campaigns.setData((cur) => {
      const arr = cur || [];
      return arr.some((x) => x.id === c.id) ? arr.map((x) => (x.id === c.id ? c : x)) : [c, ...arr];
    });
    if (c.status === 'generating') setFast(true);
  };

  if (!advertiser) {
    return (
      <div className="shell py-6">
        {error ? <ErrorNote error={error} title="Could not load your account" /> : <div className="flex items-center gap-2 text-on-surface-variant"><Spinner /> Loading your account…</div>}
      </div>
    );
  }

  return (
    <div className="shell space-y-6 py-6">
      <PageHead
        crumbs={['Advertiser', 'SoundShare Ads']}
        title={advertiser.name}
        chips={
          <span className="rounded-full border border-paytm-cyan/30 bg-paytm-cyan-light px-2.5 py-0.5 text-label-sm text-paytm-navy">
            {advertiser.type === 'brand' ? 'Brand' : 'Local business'} · {titleCase(advertiser.category)}
          </span>
        }
        right={advertiser.address && <span className="flex items-center gap-1 text-body-sm text-on-surface-variant"><Icon name="location_on" className="text-[16px]" />{advertiser.address}</span>}
      />
      <KycBanner advertiser={advertiser} onChanged={reload} />
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12">
        <section className="min-w-0 space-y-6 lg:col-span-7">
          <CampaignBuilder
            advertiser={advertiser}
            onCreated={(c) => {
              upsert(c);
              setSelectedId(c.id);
              reload();
            }}
          />
        </section>
        <section className="min-w-0 space-y-6 lg:col-span-5">
          <Wallet advertiser={advertiser} reload={reload} />
          <Preview campaign={selected} advertiser={advertiser} onChanged={upsert} />
          <Card
            icon="monitoring"
            title="Campaigns"
            actions={
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  campaigns.reload();
                  reload();
                }}
              >
                <Icon name="refresh" className="text-[16px] text-paytm-cyan-dark" />
                Refresh telemetry
              </button>
            }
          >
            <ErrorNote error={campaigns.error} title="Could not load campaigns" className="mb-3" />
            {!campaigns.data ? (
              !campaigns.error && <div className="flex items-center gap-2 text-on-surface-variant"><Spinner /> Loading…</div>
            ) : list.length === 0 ? (
              <Empty icon="campaign" title="No campaigns yet">
                Your campaigns and their live play counts show up here.
              </Empty>
            ) : (
              <div className="space-y-3">
                {list.map((c) => (
                  <CampaignRow key={c.id} c={c} selected={selected?.id === c.id} onSelect={() => setSelectedId(c.id)} onChanged={upsert} />
                ))}
              </div>
            )}
          </Card>
        </section>
      </div>
    </div>
  );
}
