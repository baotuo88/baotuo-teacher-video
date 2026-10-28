import { useEffect, useState } from 'react';
import { ArrowRight, ArrowUp, Check, Clock, FileCode, FileText, Film, MessageSquareText, Plus, RefreshCw, Send, Timer, Undo2, X } from 'lucide-react';
import { api, cueText, fmtTime, P, type Cue, type ScriptPage, type Timeline } from '../../api';
import { Code, DirectorNote, Empty, Notice, PageHeader, toast } from '../../ui';
import { useProject } from '../Workspace';

export default function ScriptStep() {
  const { p, reload, run, busy } = useProject();
  const [pages, setPages] = useState<ScriptPage[]>(p.script.PAGES);
  const [dirty, setDirty] = useState(false);
  const [raw, setRaw] = useState<string | null>(null);
  const [tl, setTl] = useState<Timeline | null>(null);
  const [fb, setFb] = useState('');
  const loadTl = () => api.get<Timeline>(`${P(p.id)}/timeline`).then(setTl).catch(() => setTl(null));
  useEffect(() => { if (!dirty) setPages(p.script.PAGES); }, [p.script.PAGES]);
  useEffect(() => { if (p.overview.script) loadTl(); }, [p.overview.script, p.script]);

  if (!p.overview.script) {
    return (
      <div className="stack">
        <PageHeader eyebrow="第 3 步" title="口播" />
        <Empty icon={<FileText />} title={busy ? '导演正在写口播…' : '还没有口播'} actions={
          <button className="primary large" disabled={busy || !p.storyboard} onClick={() => run('script/generate')}>{p.storyboard ? <>写口播<ArrowRight /></> : '先完成分镜'}</button>}>
          口播是每一页要说的话，一句一个动画落点。分镜确认后，导演按分镜来写。
        </Empty>
      </div>
    );
  }
  const edit = (fn: (x: ScriptPage[]) => void) => {
    const n = structuredClone(pages);
    fn(n);
    setPages(n);
    setDirty(true);
  };
  const setCue = (pi: number, ci: number, text: string, hold?: number) => edit((n) => {
    n[pi].cues[ci] = hold ? { t: text, hold } : text;
  });
  const save = async () => {
    try {
      const r = await api.put<{ duration: number; voice: string }>(`${P(p.id)}/script`, { pages });
      toast.ok(`已保存，估算 ${fmtTime(r.duration)}${r.voice === 'stale' ? '，改过的句子需要重新配音' : ''}`);
      setDirty(false);
      await reload();
    } catch (e) { toast.err(e); }
  };
  const openRaw = () => fetch(`/files/${p.id}/script.js`).then((r) => r.text()).then(setRaw).catch(toast.err);
  const saveRaw = async () => {
    try {
      await api.put(`${P(p.id)}/script`, { raw });
      toast.ok('script.js 已保存');
      setRaw(null);
      await reload();
    } catch (e) { toast.err(e); }
  };
  const total = pages.reduce((n, pg) => n + pg.cues.length, 0);
  const chars = pages.reduce((n, pg) => n + pg.cues.reduce((m, c) => m + cueText(c).length, 0), 0);
  const span = (id: string) => tl?.pages.find((x) => x.id === id);
  const ratio = tl ? tl.duration / p.duration : 0;
  const next = p.overview.voice === 'off' ? ['pages/generate', '画画面'] : ['voice/generate', '配音'];

  const actions = raw !== null ? <>
    <button onClick={() => setRaw(null)}><X />取消</button>
    <button className="primary" onClick={saveRaw}><Check />保存 script.js</button>
  </> : dirty ? (
    <div className="savebar">
      <span>有未保存的修改</span>
      <button className="ghost small" onClick={() => { setPages(p.script.PAGES); setDirty(false); }}><Undo2 />撤销</button>
      <button className="primary small" disabled={busy} onClick={save}><Check />保存</button>
    </div>
  ) : <>
    <button className="ghost" onClick={openRaw}><FileCode />编辑 script.js</button>
    <button className="primary" disabled={busy} onClick={() => run(next[0])}>{next[1]}<ArrowRight /></button>
  </>;

  return (
    <div className="stack">
      <PageHeader eyebrow="第 3 步" title="口播" sticky actions={actions}
        desc="一句一个动画落点（页面代码里的 P.c(i) 指第 i 句）。增删句子后，相关页面的动画时间会跟着移动，建议重画受影响的页。" />

      {raw !== null ? <Code value={raw} onChange={setRaw} height="70vh" /> : <>
        <div className="stats">
          <div className="stat"><div className="k"><Film />页数</div><div className="v">{pages.length}</div></div>
          <div className="stat"><div className="k"><MessageSquareText />句数</div><div className="v">{total}<small>{chars.toLocaleString()} 字</small></div></div>
          <div className="stat">
            <div className="k"><Clock />{tl?.voiced ? '实际时长' : '估算时长'}</div>
            <div className="v">{tl ? fmtTime(tl.duration) : '—'}<small>目标 {fmtTime(p.duration)}</small></div>
            {tl && <div className={`bar ${ratio > 1.25 || ratio < .75 ? 'warn' : 'ok'}`}><div style={{ width: `${Math.min(100, ratio * 100)}%` }} /></div>}
          </div>
        </div>
        {p.overview.voice === 'stale' && <Notice kind="warn">口播改过，改过的句子需要重新配音。</Notice>}
        {p.script_report && <DirectorNote>{p.script_report}</DirectorNote>}
        {p.script_issues?.length > 0 && (
          <Notice kind="warn">还没完全满足的要求：<ul>{p.script_issues.map((x, i) => <li key={i} className="small">{x}</li>)}</ul></Notice>
        )}

        {pages.map((pg, pi) => {
          const sp = span(pg.id);
          return (
            <section key={pg.id} className="spage">
              <div className="spage-head">
                <span className="pid">{pg.id}</span>
                <input className="bare sec" value={pg.section || ''} placeholder="章节" onChange={(e) => edit((n) => { n[pi].section = e.target.value; })} />
                <input className="bare ttl grow" value={pg.title || ''} placeholder="页标题" onChange={(e) => edit((n) => { n[pi].title = e.target.value; })} />
                {sp && <span className="tag mono">{fmtTime(sp.start)} – {fmtTime(sp.end)}</span>}
              </div>
              <div className="cues">
                {pg.cues.map((c: Cue, ci) => (
                  <div key={ci} className="cue">
                    <span className="n">{ci}</span>
                    <input className="bare t" value={cueText(c)} placeholder="这一句说什么" onChange={(e) => setCue(pi, ci, e.target.value, typeof c === 'string' ? undefined : c.hold)} />
                    <div className="hold" title="念完后多停几秒（画面继续动）">
                      <Timer />
                      <input type="number" step={0.1} min={0} max={3} placeholder="停顿"
                        value={typeof c === 'string' ? '' : c.hold ?? ''} onChange={(e) => setCue(pi, ci, cueText(c), +e.target.value || undefined)} />
                    </div>
                    <div className="acts">
                      <button className="ghost icon small" title="在下面插一句" onClick={() => edit((n) => { n[pi].cues.splice(ci + 1, 0, ''); })}><Plus /></button>
                      <button className="ghost icon small" title="上移" disabled={ci === 0} onClick={() => edit((n) => { const x = n[pi].cues; [x[ci - 1], x[ci]] = [x[ci], x[ci - 1]]; })}><ArrowUp /></button>
                      <button className="ghost icon small danger" title="删除" onClick={() => edit((n) => { n[pi].cues.splice(ci, 1); })}><X /></button>
                    </div>
                  </div>
                ))}
                {pg.cues.length === 0 && <button className="ghost small" onClick={() => edit((n) => { n[pi].cues.push(''); })}><Plus />加一句</button>}
              </div>
            </section>
          );
        })}

        <div className="composer">
          <textarea rows={2} placeholder="告诉导演怎么重写。例：语气再口语一点；第 3 页太长，压到 3 句" value={fb} onChange={(e) => setFb(e.target.value)} />
          <div className="bar-row">
            <span className="who"><RefreshCw />按意见整体重写口播（会覆盖当前内容）</span>
            <button className="primary small" disabled={busy || !fb.trim()} onClick={() => confirm('会按分镜整体重写口播，覆盖当前内容，确定？') && run('script/generate', { feedback: fb })}><Send />重写口播</button>
          </div>
        </div>
      </>}
    </div>
  );
}
