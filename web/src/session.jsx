import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { api, getToken, setToken, setUnauthorizedHandler } from './api.js';

/* ---------------------------------------------------------------- config */

const ConfigCtx = createContext({ config: null, online: null, recheck: () => {} });
export const useConfig = () => useContext(ConfigCtx);

/** Polls GET /api/config (public) to drive the provider pill, AI badges and the offline banner. */
export function ConfigProvider({ children }) {
  const [state, setState] = useState({ config: null, online: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    let timer;
    const check = async () => {
      try {
        const config = await api.config();
        if (alive) setState({ online: true, config });
      } catch (e) {
        if (alive) setState((s) => ({ online: !e.network, config: s.config }));
      }
      if (alive) timer = setTimeout(check, 15000);
    };
    check();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [tick]);
  const value = useMemo(() => {
    const c = state.config;
    return {
      ...state,
      isMock: c?.provider === 'mock',
      aiConfigured: c ? !!c.ai?.configured : null,
      textModel: c?.ai?.text_model || null,
      ttsModel: c?.ai?.tts_model || null,
      recheck: () => setTick((t) => t + 1),
    };
  }, [state]);
  return <ConfigCtx.Provider value={value}>{children}</ConfigCtx.Provider>;
}

/* --------------------------------------------------------------- session */

const SessionCtx = createContext(null);
export const useSession = () => useContext(SessionCtx);

export const HOME_BY_ROLE = { merchant: '/merchant', advertiser: '/advertiser', admin: '/admin' };

export function SessionProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(getToken() ? 'loading' : 'anon');
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setUser(null);
      setStatus('anon');
      setExpired(true);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    let alive = true;
    api
      .me()
      .then((u) => {
        if (!alive) return;
        setUser(u);
        setStatus('authed');
      })
      .catch((e) => {
        if (!alive) return;
        if (e.status === 401 || e.status === 403) {
          setToken(null);
          setStatus('anon');
        } else {
          // Backend down or erroring: keep the token, show the error state and let the user retry.
          setStatus('error');
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  const begin = useCallback((session) => {
    setToken(session.token);
    setUser(session.user);
    setStatus('authed');
    setExpired(false);
    return session.user;
  }, []);

  const value = useMemo(
    () => ({
      user,
      status,
      expired,
      login: async (phone, password) => begin(await api.login(phone, password)),
      registerMerchant: async (body) => begin(await api.registerMerchant(body)),
      registerAdvertiser: async (body) => begin(await api.registerAdvertiser(body)),
      logout: async () => {
        try {
          await api.logout();
        } catch {
          /* the token is dropped locally either way */
        }
        setToken(null);
        setUser(null);
        setStatus('anon');
        setExpired(false);
      },
      retry: () => window.location.reload(),
    }),
    [user, status, expired, begin],
  );
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

/* --------------------------------------------------------------- account */

const AccountCtx = createContext({ account: null, error: null, reload: async () => null, setAccount: () => {} });
export const useAccount = () => useContext(AccountCtx);

/**
 * Loads the logged-in merchant or advertiser profile (with stats / wallet) and refreshes it
 * in the background so the header balance and page stats stay current.
 */
export function AccountProvider({ children }) {
  const { user } = useSession();
  const [account, setAccount] = useState(null);
  const [error, setError] = useState(null);
  const kind = user?.role === 'merchant' ? 'merchant' : user?.role === 'advertiser' ? 'advertiser' : null;
  const id = kind === 'merchant' ? user.merchant_id : kind === 'advertiser' ? user.advertiser_id : null;
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (!kind || !id) return null;
    const my = ++seq.current;
    try {
      const a = kind === 'merchant' ? await api.merchant(id) : await api.advertiser(id);
      if (my === seq.current) {
        setAccount(a);
        setError(null);
      }
      return a;
    } catch (e) {
      if (my === seq.current) setError(e);
      return null;
    }
  }, [kind, id]);

  useEffect(() => {
    setAccount(null);
    setError(null);
    if (!kind || !id) return undefined;
    reload();
    const t = setInterval(reload, kind === 'advertiser' ? 8000 : 20000);
    return () => clearInterval(t);
  }, [kind, id, reload]);

  const value = useMemo(() => ({ account, error, reload, setAccount, kind }), [account, error, reload, kind]);
  return <AccountCtx.Provider value={value}>{children}</AccountCtx.Provider>;
}
