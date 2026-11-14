import { useCallback, useEffect, useRef, useState } from 'react';
import { getToken, wsUrl } from './api.js';

/**
 * Runs `fn` now and every `ms` while `enabled`. Returns {data, error, loading, reload, setData}.
 * Changing anything in `deps` triggers an immediate reload. Polling pauses while the tab is hidden.
 */
export function usePoll(fn, ms, deps = [], enabled = true) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const my = ++seq.current;
    try {
      const d = await fnRef.current();
      if (my === seq.current) {
        setData(d);
        setError(null);
      }
      return d;
    } catch (e) {
      if (my === seq.current) setError(e);
      return null;
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    setLoading(true);
    reload();
    if (!ms) return undefined;
    const t = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      reload();
    }, ms);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, ms, enabled]);

  return { data, error, loading, reload, setData };
}

/**
 * Connects to an authenticated backend WebSocket (e.g. "/ws/admin"; the session token is sent as ?token=),
 * auto-reconnects with backoff, and calls onEvent(parsedJson) per message.
 * Returns 'connecting' | 'open' | 'closed'.
 */
export function useSocket(path, onEvent, enabled = true) {
  const [state, setState] = useState('connecting');
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    if (!enabled) return undefined;
    let ws;
    let stopped = false;
    let retry;
    let backoff = 1000;
    const connect = () => {
      if (stopped) return;
      setState('connecting');
      const token = getToken();
      const sep = path.includes('?') ? '&' : '?';
      try {
        ws = new WebSocket(wsUrl(`${path}${token ? `${sep}token=${encodeURIComponent(token)}` : ''}`));
      } catch {
        retry = setTimeout(connect, backoff);
        return;
      }
      ws.onopen = () => {
        backoff = 1000;
        setState('open');
      };
      ws.onmessage = (m) => {
        let msg;
        try {
          msg = JSON.parse(m.data);
        } catch {
          msg = { type: 'message', raw: String(m.data) };
        }
        if (msg && msg.type === 'ping') {
          try {
            ws.send(JSON.stringify({ type: 'pong' }));
          } catch {
            /* ignore */
          }
          return;
        }
        if (cb.current) cb.current(msg || {});
      };
      ws.onclose = () => {
        setState('closed');
        if (!stopped) {
          retry = setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 15000);
        }
      };
      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      if (ws) {
        ws.onclose = null;
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      }
    };
  }, [path, enabled]);

  return state;
}

/** Ticks every `ms` so countdowns re-render. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Wraps an async action with busy/error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = useCallback(async (fn) => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}
