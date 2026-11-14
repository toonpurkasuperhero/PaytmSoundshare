import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AccountProvider, ConfigProvider, HOME_BY_ROLE, SessionProvider, useSession } from './session.jsx';
import { Footer, Header, OfflineBanner } from './components/Layout.jsx';
import { Icon, Spinner } from './components/ui.jsx';
import Login from './pages/Login.jsx';
import Register from './pages/Register.jsx';
import Merchant from './pages/Merchant.jsx';
import Advertiser from './pages/Advertiser.jsx';
import Admin from './pages/Admin.jsx';

function Splash({ children }) {
  return <div className="flex flex-1 items-center justify-center p-10 text-on-surface-variant">{children}</div>;
}

function SessionError() {
  const { retry, logout } = useSession();
  return (
    <Splash>
      <div className="card max-w-md text-center">
        <Icon name="cloud_off" className="text-[32px] text-error-red" />
        <h2 className="mt-2 text-headline-sm font-bold text-paytm-navy">Could not check your session</h2>
        <p className="mt-1 text-body-sm">The backend did not answer. Your login is kept; retry when the server is back.</p>
        <div className="mt-4 flex justify-center gap-2">
          <button type="button" className="btn btn-navy" onClick={retry}>
            Retry
          </button>
          <button type="button" className="btn btn-outline" onClick={logout}>
            Log out
          </button>
        </div>
      </div>
    </Splash>
  );
}

/** Lets a route through only for `role`; others go to login or to their own home. */
function RequireRole({ role, children }) {
  const { user, status } = useSession();
  const loc = useLocation();
  if (status === 'loading') {
    return (
      <Splash>
        <Spinner className="mr-2" /> Loading your account…
      </Splash>
    );
  }
  if (status === 'error') return <SessionError />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (user.role !== role) return <Navigate to={HOME_BY_ROLE[user.role] || '/login'} replace />;
  return children;
}

function Home() {
  const { user, status } = useSession();
  if (status === 'loading') return <Splash>Loading…</Splash>;
  if (status === 'error') return <SessionError />;
  return <Navigate to={user ? HOME_BY_ROLE[user.role] || '/login' : '/login'} replace />;
}

function Shell() {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <OfflineBanner />
      <main className="flex w-full flex-1 flex-col">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/merchant/*"
            element={
              <RequireRole role="merchant">
                <Merchant />
              </RequireRole>
            }
          />
          <Route
            path="/advertiser/*"
            element={
              <RequireRole role="advertiser">
                <Advertiser />
              </RequireRole>
            }
          />
          <Route
            path="/admin/*"
            element={
              <RequireRole role="admin">
                <Admin />
              </RequireRole>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}

export default function App() {
  return (
    <ConfigProvider>
      <SessionProvider>
        <AccountProvider>
          <Shell />
        </AccountProvider>
      </SessionProvider>
    </ConfigProvider>
  );
}
