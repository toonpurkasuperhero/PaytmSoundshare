import { absUrl, qrSrc } from '../api.js';
import { langLabel } from '../format.js';
import { useConfig } from '../session.jsx';
import { Icon, SourceBadge } from './ui.jsx';

/** The counter-screen banner in the creative's own colours, with the offer-claim QR. */
export function Banner({ creative, advertiserName }) {
  const b = creative?.banner || {};
  const bg = b.bg || '#002970';
  const fg = b.fg || '#FFFFFF';
  const accent = b.accent || '#00BAF2';
  return (
    <div className="relative overflow-hidden rounded-xl p-4 shadow-md" style={{ background: bg, color: fg }}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: accent }} />
            <span className="truncate text-[11px] font-bold uppercase tracking-wider" style={{ color: accent }}>
              {b.title || advertiserName}
            </span>
          </div>
          {b.subtitle && <h4 className="break-words text-[17px] font-bold leading-tight">{b.subtitle}</h4>}
          {b.cta && (
            <div className="pt-1">
              <span className="inline-flex items-center gap-1 rounded-md px-3 py-1 text-label-sm font-bold shadow-sm" style={{ background: accent, color: bg }}>
                <Icon name="qr_code_scanner" className="text-[14px]" />
                {b.cta}
              </span>
            </div>
          )}
        </div>
        {creative?.offer_url && (
          <div className="shrink-0 rounded-lg bg-white p-1.5 shadow-md">
            <img src={qrSrc(creative.offer_url, 3)} alt="Offer claim QR code" width="72" height="72" className="h-[72px] w-[72px]" />
          </div>
        )}
      </div>
    </div>
  );
}

/** Banner + script + audio for one campaign creative, with where each part came from. */
export default function CreativePreview({ creative, advertiserName }) {
  const { ttsModel } = useConfig();
  if (!creative) return null;
  const secs = creative.duration_ms ? (creative.duration_ms / 1000).toFixed(1) : null;
  return (
    <div className="space-y-4">
      <Banner creative={creative} advertiserName={advertiserName} />
      <div className="space-y-3 rounded-xl border border-slate-200/80 bg-slate-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 text-label-sm">
          <span className="flex items-center gap-1.5 font-medium text-slate-600">
            <Icon name="record_voice_over" className="text-[16px] text-paytm-cyan-dark" />
            Script ({langLabel(creative.lang)}
            {creative.voice ? ` · voice ${creative.voice}` : ''})
          </span>
          {secs && <span className="font-mono font-semibold text-paytm-navy">Duration: {secs}s</span>}
        </div>
        {creative.script && <p className="rounded-lg border border-l-[3px] border-slate-200/60 border-l-paytm-cyan bg-white p-3 text-body-sm italic text-slate-800 shadow-sm">“{creative.script}”</p>}
        {creative.audio_url ? (
          <audio controls preload="none" src={absUrl(creative.audio_url)} className="h-10 w-full">
            Your browser can't play this audio.
          </audio>
        ) : (
          <div className="text-body-sm text-on-surface-variant">No voice-over for this creative.</div>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          <SourceBadge label="Copy" source={creative.source} model={creative.model} reason={creative.fallback_reason} />
          <SourceBadge label="Voice" source={creative.voice_source} model={creative.voice_source === 'ai' ? ttsModel : null} reason={creative.voice_fallback_reason} />
        </div>
      </div>
    </div>
  );
}
