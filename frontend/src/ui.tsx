import { Component, useEffect, useState, type ReactNode } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { javascript } from '@codemirror/lang-javascript';
import { json } from '@codemirror/lang-json';
import {
  AlertTriangle, Bot, Check, CircleAlert, CircleCheck, Clapperboard, Clock, ImageOff, Info, Loader2, X,
} from 'lucide-react';
import { exampleThumb, type Style } from './api';

// ── toasts ──
type Toast = { id: number; msg: string; kind: 'ok' | 'err' | 'info' };
let push: (t: Omit<Toast, 'id'>) => void = () => {};
export const toast = {
  ok: (msg: string) => push({ msg, kind: 'ok' }),
  err: (e: unknown) => push({ msg: e instanceof Error ? e.message : String(e), kind: 'err' }),
  info: (msg: string) => push({ msg, kind: 'info' }),
};
export function ToastHost() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    let n = 0;
    push = (t) => {
      const id = ++n;
      setItems((x) => [...x.slice(-4), { ...t, id }]);
      setTimeout(() => setItems((x) => x.filter((y) => y.id !== id)), t.kind === 'err' ? 8000 : 3500);
    };
  }, []);
  const icon = { ok: <CircleCheck />, err: <CircleAlert />, info: <Info /> };
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {icon[t.kind]}
          <div className="grow">{t.msg}</div>
          <button className="ghost icon small" aria-label="关闭" onClick={() => setItems((x) => x.filter((y) => y.id !== t.id))}><X /></button>
        </div>
      ))}
    </div>
  );
}

// ── modal ──
export function Modal({ title, icon, onClose, children, footer, size }: {
  title: ReactNode; icon?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; size?: 'narrow' | 'wide';
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', k);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { window.removeEventListener('keydown', k); document.body.style.overflow = prev; };
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${size || ''}`} role="dialog" aria-modal="true">
        <header>
          {icon && <span className="ico">{icon}</span>}
          <h2>{title}</h2>
          <button className="ghost icon" aria-label="关闭" onClick={onClose}><X /></button>
        </header>
        <div className="content">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export function Lightbox({ src, title = '截图', onClose }: { src: string; title?: string; onClose: () => void }) {
  return (
    <Modal title={title} onClose={onClose} size="wide">
      <div className="lightbox"><img src={src} alt="" /></div>
    </Modal>
  );
}

// ── layout pieces ──
export function PageHeader({ title, eyebrow, desc, actions, badge, sticky }: {
  title: ReactNode; eyebrow?: ReactNode; desc?: ReactNode; actions?: ReactNode; badge?: ReactNode; sticky?: boolean;
}) {
  return (
    <div className={`page-head ${sticky ? 'sticky' : ''}`}>
      <div className="titles">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}{badge}</h1>
        {desc && <div className="desc">{desc}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function Panel({ title, sub, icon, actions, children, body = 'pad', foot, className = '' }: {
  title?: ReactNode; sub?: ReactNode; icon?: ReactNode; actions?: ReactNode; children?: ReactNode;
  body?: 'pad' | 'tight' | 'flush'; foot?: ReactNode; className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <div className="panel-head">
          {icon && <span className="ico">{icon}</span>}
          <div className="titles"><h2>{title}</h2>{sub && <div className="sub">{sub}</div>}</div>
          {actions && <div className="row gap-s">{actions}</div>}
        </div>
      )}
      {children !== undefined && <div className={`panel-body ${body === 'pad' ? '' : body}`}>{children}</div>}
      {foot && <div className="panel-foot">{foot}</div>}
    </section>
  );
}

export function Empty({ icon, title, children, actions }: { icon: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-ico">{icon}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Notice({ kind = 'info', children, icon }: { kind?: 'info' | 'ok' | 'warn' | 'err'; children: ReactNode; icon?: ReactNode }) {
  const ic = icon ?? { info: <Info />, ok: <CircleCheck />, warn: <AlertTriangle />, err: <CircleAlert /> }[kind];
  return <div className={`notice ${kind === 'info' ? '' : kind}`}>{ic}<div className="grow">{children}</div></div>;
}

export function DirectorNote({ children }: { children: ReactNode }) {
  return (
    <div className="director">
      <span className="av"><Bot /></span>
      <div className="grow"><div className="who">导演说明</div><div className="say">{children}</div></div>
    </div>
  );
}

export function Field({ label, hint, optional, children, as = 'label', className = '' }: {
  label: ReactNode; hint?: ReactNode; optional?: boolean; children: ReactNode; as?: 'label' | 'div'; className?: string;
}) {
  const inner = <>
    <span className="label">{label}{optional && <span className="opt">可选</span>}</span>
    {children}
    {hint && <span className="hint">{hint}</span>}
  </>;
  return as === 'label' ? <label className={`field ${className}`}>{inner}</label> : <div className={`field ${className}`}>{inner}</div>;
}

export function Switch({ checked, onChange, children, hint }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="sw-text"><span>{children}</span>{hint && <small>{hint}</small>}</span>
    </label>
  );
}

export function Seg<T extends string | number>({ value, options, onChange, small }: {
  value: T; options: [T, ReactNode][]; onChange: (v: T) => void; small?: boolean;
}) {
  return (
    <div className={`seg ${small ? 'small' : ''}`} role="radiogroup">
      {options.map(([v, l]) => (
        <button type="button" key={String(v)} role="radio" aria-checked={v === value} className={v === value ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  );
}

/** A page that throws while rendering shows this instead of taking the whole app down to a blank screen.
 *  `resetKey` (e.g. the path) clears it when the user goes elsewhere. */
export class PageBoundary extends Component<{ resetKey: string; children: ReactNode }, { error: Error | null; key: string }> {
  state = { error: null as Error | null, key: this.props.resetKey };
  static getDerivedStateFromError(error: Error) { return { error }; }
  static getDerivedStateFromProps(props: { resetKey: string }, state: { error: Error | null; key: string }) {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }
  componentDidCatch(error: Error) { console.error('page crashed:', error); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="empty">
        <div className="empty-ico"><CircleAlert /></div>
        <h3>这个页面出错了</h3>
        <p className="mono small">{this.state.error.message}</p>
        <div className="row">
          <button className="primary" onClick={() => this.setState({ error: null })}>重试</button>
          <button onClick={() => window.location.reload()}>刷新页面</button>
        </div>
      </div>
    );
  }
}

export const Logo =({ large }: { large?: boolean }) => <span className={`logo ${large ? 'lg' : ''}`}><Clapperboard /></span>;

export const Spinner = ({ small }: { small?: boolean }) => <span className={`spin ${small ? 'sm' : ''}`} />;
// ── stills ──
/** A 16:9 still over a placeholder. `retry`: the server makes some stills on first ask (404 meanwhile), so ask again. */
export function Thumb({ src, fallback, retry = 0, className = '', children, onClick }: {
  src?: string; fallback?: ReactNode; retry?: number; className?: string; children?: ReactNode; onClick?: () => void;
}) {
  // remember which url has loaded rather than resetting a flag: a cached still can load before any effect would run
  const [loaded, setLoaded] = useState('');
  const [tries, setTries] = useState<{ src?: string; n: number }>({ n: 0 });
  const n = tries.src === src ? tries.n : 0;
  const url = src && n ? `${src}${src.includes('?') ? '&' : '?'}r=${n}` : src;
  const ok = !!url && loaded === url;
  const failed = () => { if (n < retry) setTimeout(() => setTries({ src, n: n + 1 }), 5000); };
  return (
    <div className={`thumbbox ${className}`} onClick={onClick}>
      {!ok && (fallback ?? <div className="ph"><Clapperboard /></div>)}
      {url && <img key={url} src={url} alt="" loading="lazy" className={ok ? 'on' : ''} onLoad={() => setLoaded(url)} onError={failed}
        ref={(el) => { if (el?.complete && el.naturalWidth && loaded !== url) setLoaded(url); }} />}
      {children}
    </div>
  );
}

export function SwatchArt({ colors }: { colors: string[] }) {
  const c = colors.length ? colors : ['#eceae4', '#8b877e'];
  return (
    <div className="swatch-art" style={{ background: c[0] }}>
      {(c.length > 1 ? c.slice(1) : c).slice(0, 4).map((x, i) => <i key={i} style={{ background: x }} />)}
    </div>
  );
}

// ── code editor ──
export function Code({ value, onChange, lang = 'js', height = '480px', readOnly }: {
  value: string; onChange?: (v: string) => void; lang?: 'js' | 'json'; height?: string; readOnly?: boolean;
}) {
  const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  return (
    <CodeMirror value={value} height={height} theme={dark ? 'dark' : 'light'} readOnly={readOnly}
      extensions={[lang === 'json' ? json() : javascript()]} onChange={onChange} basicSetup={{ foldGutter: true }} />
  );
}

// ── style picker: a real still of each style's sample film where there is one, its palette otherwise ──
export function StylePicker({ styles, value, onChange, maxHeight }: { styles: Style[]; value: string; onChange: (s: string) => void; maxHeight?: number }) {
  const [all, setAll] = useState(false);
  const shown = all ? styles : styles.filter((s) => s.classic || s.id === value);
  const cur = styles.find((s) => s.id === value);
  return (
    <div className="col">
      <div className="row between">
        <Seg small value={all ? 'all' : 'classic'} onChange={(v) => setAll(v === 'all')}
          options={[['classic', '经典 5 款'], ['all', `全部 ${styles.length || ''} 款`]]} />
        {cur && <span className="small muted ellipsis" style={{ maxWidth: 260 }}>适合：{cur.fit.join('、')}</span>}
      </div>
      <div className="styles" style={maxHeight ? { maxHeight } : undefined}>
        {shown.map((s) => (
          <button type="button" key={s.id} className={`style-opt ${value === s.id ? 'on' : ''}`} onClick={() => onChange(s.id)} title={s.tagline}>
            <Thumb src={s.example ? exampleThumb(`style:${s.id}`) : undefined} retry={s.example ? 12 : 0} fallback={<SwatchArt colors={s.swatch} />} />
            {value === s.id && <span className="check"><Check strokeWidth={3} /></span>}
            <div className="so-body">
              <b>{s.name}{s.webgl && <span className="tag warn" title="3D 风格，服务器没有 GPU 时渲染较慢">3D</span>}</b>
              <small className="clamp2">{s.tagline}</small>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

export function StatusTag({ status, glass }: { status?: string; glass?: boolean }) {
  const map: Record<string, [string, string, ReactNode]> = {
    done: ['ok', '通过', <Check />], edited: ['ok', '已手改', <Check />], flagged: ['warn', '需关注', <AlertTriangle />],
    failed: ['err', '失败', <CircleAlert />], queued: ['', '排队', <Clock />],
    drawing: ['run', '在画', null], checking: ['run', '检查中', null], reviewing: ['run', '审片中', null], fixing: ['run', '修改中', null],
  };
  const [cls, label, ic] = map[status || ''] || ['', status || '未画', <ImageOff />];
  return <span className={`tag ${cls} ${glass ? 'glass' : ''}`}>{cls === 'run' ? <Loader2 className="spin-ico" /> : ic}{label}</span>;
}

export function useConfirm() {
  return (msg: string) => window.confirm(msg);
}
