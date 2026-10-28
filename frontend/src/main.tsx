import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { KeyRound, LayoutGrid, LogOut, Settings } from 'lucide-react';
import { api } from './api';
import Projects from './pages/Projects';
import Workspace from './pages/Workspace';
import SettingsPage from './pages/Settings';
import { Logo, ToastHost } from './ui';
import './styles.css';

function Login({ onOk }: { onOk: () => void }) {
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post('/api/auth/login', { password: pw });
      onOk();
    } catch (x) {
      setErr((x as Error).message);
      setBusy(false);
    }
  };
  return (
    <div className="login-wrap">
      <form className="panel login" onSubmit={submit}>
        <div className="lh">
          <Logo large />
          <div><h1>宝拓讲解视频</h1><p>一句话主题，自动做成讲解视频</p></div>
        </div>
        <label className="field"><span className="label"><KeyRound size={14} />访问密码</span>
          <input type="password" autoFocus value={pw} onChange={(e) => { setPw(e.target.value); setErr(''); }} placeholder="输入密码" />
        </label>
        {err && <div className="err-text small">{err}</div>}
        <button className="primary large block" type="submit" disabled={busy || !pw}>{busy ? '验证中…' : '进入'}</button>
      </form>
    </div>
  );
}

function Top({ auth, onLogout }: { auth: { enabled: boolean }; onLogout: () => void }) {
  const loc = useLocation();
  const inProject = loc.pathname === '/' || loc.pathname.startsWith('/p/');
  return (
    <header className="top">
      <Link to="/" className="brand"><Logo /><span>宝拓讲解视频<small>AI 讲解视频工作室</small></span></Link>
      <nav>
        <NavLink to="/" className={inProject ? 'active' : ''}><LayoutGrid />项目</NavLink>
        <NavLink to="/settings"><Settings />设置</NavLink>
      </nav>
      <div className="spacer" />
      {auth.enabled && <button className="ghost small" onClick={onLogout}><LogOut />退出</button>}
    </header>
  );
}

function App() {
  const [auth, setAuth] = useState<{ enabled: boolean; ok: boolean } | null>(null);
  const check = () => api.get<{ enabled: boolean; ok: boolean }>('/api/auth/status').then(setAuth).catch(() => setAuth({ enabled: false, ok: true }));
  useEffect(() => {
    check();
    const f = () => setAuth((a) => (a ? { ...a, ok: false } : a));
    window.addEventListener('btv-login', f);
    return () => window.removeEventListener('btv-login', f);
  }, []);
  if (!auth) return null;
  if (auth.enabled && !auth.ok) return <><Login onOk={check} /><ToastHost /></>;
  return (
    <BrowserRouter>
      <Top auth={auth} onLogout={() => api.post('/api/auth/logout').then(check)} />
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route path="/p/:pid/*" element={<Workspace />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<div className="notfound"><b>404</b>没有这个页面<Link to="/">回到项目</Link></div>} />
      </Routes>
      <ToastHost />
    </BrowserRouter>
  );
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
