import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { useConfig } from '../session.jsx';
import { Icon, SourceBadge, Spinner } from './ui.jsx';

const SR = typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : null;
const CAN_RECORD = typeof window !== 'undefined' && !!window.MediaRecorder && !!navigator.mediaDevices?.getUserMedia;
const MAX_BYTES = 2 * 1024 * 1024;
const MAX_MS = 60000;

function pickMime() {
  const opts = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  return opts.find((m) => window.MediaRecorder.isTypeSupported?.(m)) || '';
}

/**
 * Hold-to-talk dictation. Primary path: record with MediaRecorder and POST /api/ai/transcribe.
 * If the AI answers 502 (or the browser can't record), it switches to the Web Speech API.
 * Calls onText(text) with each finished transcript and shows which path produced it.
 */
export default function HoldToTalk({ speechLang = 'en-IN', onText, className = '' }) {
  const { textModel } = useConfig();
  const [mode, setMode] = useState(CAN_RECORD ? 'ai' : SR ? 'browser' : 'none');
  const [state, setState] = useState('idle'); // idle | starting | recording | transcribing
  const [interim, setInterim] = useState('');
  const [last, setLast] = useState(null); // {path, model}
  const [note, setNote] = useState(null);
  const [err, setErr] = useState(null);
  const rec = useRef(null);
  const sr = useRef(null);
  const stopAsked = useRef(false);
  const timer = useRef(null);

  useEffect(
    () => () => {
      clearTimeout(timer.current);
      try {
        rec.current?.stream?.getTracks().forEach((t) => t.stop());
        sr.current?.abort();
      } catch {
        /* ignore */
      }
    },
    [],
  );

  const transcribe = async (blob) => {
    if (blob.size < 800) {
      setErr('That was too short. Hold the button while you speak.');
      setState('idle');
      return;
    }
    if (blob.size > MAX_BYTES) {
      setErr('Recording is over 2 MB. Keep it under a minute.');
      setState('idle');
      return;
    }
    setState('transcribing');
    try {
      const res = await api.transcribe(blob, speechLang.startsWith('or') ? 'od' : speechLang.slice(0, 2));
      const text = (res?.text || '').trim();
      if (text) {
        onText(text);
        setLast({ path: 'ai', model: res.model || textModel });
      } else setErr('No speech detected. Try again a little closer to the microphone.');
    } catch (e) {
      if (e.status === 502 && SR) {
        setMode('browser');
        setNote(`AI transcription failed${e.message ? ` (${e.message})` : ''}. Switched to your browser's speech recognition: hold the button and speak again.`);
      } else if (e.status === 502) {
        setErr(`AI transcription failed${e.message ? ` (${e.message})` : ''}, and this browser has no built-in speech recognition. Type the offer instead.`);
      } else {
        setErr(e.message);
      }
    } finally {
      setState('idle');
    }
  };

  const startRecording = async () => {
    stopAsked.current = false;
    setState('starting');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      setState('idle');
      if (e.name === 'NotAllowedError') setErr('Microphone permission denied. Allow it in the browser to dictate.');
      else if (SR) {
        setMode('browser');
        setNote('Could not open the microphone for recording; using browser speech recognition instead. Hold to talk again.');
      } else setErr(`Microphone unavailable: ${e.message || e.name}`);
      return;
    }
    const mime = pickMime();
    const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks = [];
    r.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
    r.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(timer.current);
      rec.current = null;
      transcribe(new Blob(chunks, { type: r.mimeType || mime || 'audio/webm' }));
    };
    rec.current = r;
    r.start();
    setState('recording');
    timer.current = setTimeout(() => r.state === 'recording' && r.stop(), MAX_MS);
    if (stopAsked.current) r.stop();
  };

  const startBrowser = () => {
    const s = new SR();
    s.lang = speechLang;
    s.interimResults = true;
    s.continuous = true;
    let finalText = '';
    s.onresult = (ev) => {
      let tmp = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else tmp += res[0].transcript;
      }
      setInterim(`${finalText} ${tmp}`.replace(/\s+/g, ' ').trim());
    };
    s.onerror = (ev) => {
      if (ev.error === 'not-allowed') setErr('Microphone permission denied.');
      else if (ev.error !== 'aborted' && ev.error !== 'no-speech') setErr(`Speech recognition error: ${ev.error}`);
    };
    s.onend = () => {
      sr.current = null;
      setState('idle');
      setInterim('');
      const text = finalText.replace(/\s+/g, ' ').trim();
      if (text) {
        onText(text);
        setLast({ path: 'browser' });
      }
    };
    try {
      s.start();
      sr.current = s;
      setState('recording');
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  const start = (e) => {
    e?.preventDefault();
    if (state !== 'idle') return;
    setErr(null);
    if (mode === 'ai') startRecording();
    else if (mode === 'browser') startBrowser();
  };
  const stop = () => {
    if (mode === 'ai') {
      stopAsked.current = true;
      if (rec.current?.state === 'recording') rec.current.stop();
    } else if (sr.current) sr.current.stop();
  };

  if (mode === 'none') {
    return (
      <div className={`text-body-sm text-on-surface-variant ${className}`}>
        <Icon name="mic_off" className="mr-1 text-[16px] align-[-3px]" />
        Voice input isn't available in this browser. Type the offer instead.
      </div>
    );
  }

  const live = state === 'recording';
  return (
    <div className={`min-w-0 ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={`btn select-none ${live ? 'rec-live bg-error-red text-white hover:bg-error-red' : 'btn-navy'}`}
          style={{ touchAction: 'none' }}
          disabled={state === 'transcribing'}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture?.(e.pointerId);
            start(e);
          }}
          onPointerUp={stop}
          onPointerCancel={stop}
          onKeyDown={(e) => {
            if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) start(e);
          }}
          onKeyUp={(e) => {
            if (e.key === ' ' || e.key === 'Enter') stop();
          }}
          onContextMenu={(e) => e.preventDefault()}
          aria-pressed={live}
        >
          {state === 'transcribing' || state === 'starting' ? <Spinner /> : <Icon name="mic" className={`text-[18px] ${live ? '' : 'text-paytm-cyan'}`} />}
          {live ? 'Listening… release' : state === 'transcribing' ? 'Transcribing…' : 'Hold to talk'}
        </button>
        <span className="text-label-sm text-slate-500">{mode === 'ai' ? 'AI transcription' : `Browser speech recognition (${speechLang})`}</span>
      </div>
      {interim && <div className="mt-1 text-body-sm italic text-on-surface-variant">“{interim}”</div>}
      {last && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-body-sm text-on-surface-variant">
          Last dictation:
          {last.path === 'ai' ? (
            <SourceBadge source="ai" model={last.model} />
          ) : (
            <span className="pill pill-muted">
              <Icon name="language" className="text-[13px]" />
              Browser speech recognition
            </span>
          )}
        </div>
      )}
      {note && <div className="note note-warn mt-2">{note}</div>}
      {err && <div className="mt-1 text-body-sm text-error-red">{err}</div>}
    </div>
  );
}
