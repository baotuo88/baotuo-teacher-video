import { useEffect, useState } from 'react';
import { MonitorPlay, Presentation, RefreshCw, SkipBack } from 'lucide-react';
import { api, fmtTime, P, pageThumb, type Timeline } from '../../api';
import { Empty, Notice, PageHeader, Switch, Thumb } from '../../ui';
import { useProject } from '../Workspace';

export default function PreviewStep() {
  const { p } = useProject();
  const [tl, setTl] = useState<Timeline | null>(null);
  const [sel, setSel] = useState('');          // the page the player starts at
  const [only, setOnly] = useState(false);     // loop just that page
  const [nonce, setNonce] = useState(0);
  const [deck, setDeck] = useState(false);
  useEffect(() => { api.get<Timeline>(`${P(p.id)}/timeline`).then(setTl).catch(() => setTl(null)); }, [p.id, p.script]);
  if (!p.overview.script) {
    return <div className="stack"><PageHeader eyebrow="第 6 步" title="预览" /><Empty icon={<MonitorPlay />} title="先完成口播">有了口播和画面，就能在浏览器里直接播放整部片。</Empty></div>;
  }
  const page = tl?.pages.find((x) => x.id === sel);
  const q = new URLSearchParams();
  if (page && only) q.set('only', page.id);
  else if (page?.start) q.set('from', String(page.start));
  if (deck) q.set('deck', '');
  q.set('lang', 'zh');
  q.set('n', String(nonce));
  const pick = (id: string) => (id === sel ? setNonce(nonce + 1) : setSel(id));
  const title = (id: string) => { const pg = p.script.PAGES.find((x) => x.id === id); return pg?.title || pg?.section || id; };

  return (
    <div className="stack">
      <PageHeader eyebrow="第 6 步" title="预览"
        desc="引擎自带的播放器，和成片同一套画面代码，改完立刻能看。"
        actions={<>
          <Switch checked={deck} onChange={setDeck} hint="一句一点击，适合当课件讲"><span className="row gap-s"><Presentation size={15} />幻灯片模式</span></Switch>
          <button onClick={() => setNonce(nonce + 1)}><RefreshCw />刷新</button>
        </>} />
      {p.overview.voice !== 'ok' && p.overview.voice !== 'off' && <Notice kind="warn">还没配音（或口播改过），声音不全，时间按估算。</Notice>}

      <div className="player">
        {/* page code is model-written: run it in an opaque-origin sandbox, away from the app's cookies and API */}
        <iframe key={`${sel}-${only}-${nonce}-${deck}`} src={`${p.preview}?${q}`} sandbox="allow-scripts" allow="autoplay; fullscreen" title="preview" />
      </div>
      <div className="row between small muted">
        <span className="row gap-s">
          <span className="kbd">空格</span>播放/暂停 <span className="kbd">←</span><span className="kbd">→</span>快退快进 <span className="kbd">F</span>全屏
        </span>
        {tl && <span>全片 {fmtTime(tl.duration)}{tl.voiced ? '（真实配音）' : '（估算）'}</span>}
      </div>

      {tl && tl.pages.length > 0 && (
        <div className="col">
          <div className="row between">
            <h3>按页跳转</h3>
            <div className="row">
              <Switch checked={only} onChange={setOnly}>只播选中的这一页</Switch>
              <button className="ghost small" disabled={!sel} onClick={() => { setSel(''); setOnly(false); }}><SkipBack />从头</button>
            </div>
          </div>
          <div className="timebar">
            {tl.pages.map((pg) => (
              <button key={pg.id} title={`${pg.id} ${title(pg.id)} · ${fmtTime(pg.start)}`} className={sel === pg.id ? 'on' : ''}
                style={{ flex: Math.max(0.5, pg.end - pg.start) }} onClick={() => pick(pg.id)} />
            ))}
          </div>
          <div className="chapters">
            {tl.pages.map((pg) => (
              <button key={pg.id} className={`chapter ${sel === pg.id ? 'on' : ''}`} onClick={() => pick(pg.id)}>
                <Thumb src={pageThumb(p, pg.id) || undefined} />
                <div className="cap"><b>{pg.id}</b><em className="nm">{title(pg.id)}</em><span>{fmtTime(pg.start)}</span></div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
