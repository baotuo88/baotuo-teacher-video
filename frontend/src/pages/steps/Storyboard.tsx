import { useEffect, useState } from 'react';
import {
  ArrowDown, ArrowRight, ArrowUp, Braces, Check, Clock, Film, LayoutList, Pencil, Plus, RefreshCw, ScanSearch, Send, Star, Trash2, Video, X,
} from 'lucide-react';
import { api, fmtTime, P, type Beat, type Issue, type Storyboard } from '../../api';
import { Code, DirectorNote, Empty, PageHeader, Panel, toast } from '../../ui';
import { useProject } from '../Workspace';

export function Issues({ items }: { items: Issue[] }) {
  const [all, setAll] = useState(false);
  if (!items?.length) return null;
  const red = items.filter((i) => i.level === 'red');
  const shown = all ? items : items.slice(0, 6);
  return (
    <Panel title="机器检查" icon={<ScanSearch />} body="tight"
      sub={red.length ? `${red.length} 处建议修改 · ${items.length - red.length} 条提示` : `没有必改的问题 · ${items.length} 条提示`}
      actions={red.length ? <span className="tag warn dot">需处理</span> : <span className="tag ok dot">可以继续</span>}>
      <div className="issues">
        {shown.map((i, k) => (
          <div key={k} className="issue">
            <span className={`tag ${i.level === 'red' ? 'err' : ''}`}>{i.level === 'red' ? '必改' : '提示'}</span>
            <span className="where">{i.page || '全片'}{i.beat != null ? ` · 第${i.beat + 1}拍` : ''}</span>
            <span className="grow">{i.zh || i.msg}</span>
          </div>
        ))}
      </div>
      {items.length > 6 && <button className="ghost small mt-s" onClick={() => setAll(!all)}>{all ? '收起' : `还有 ${items.length - 6} 条`}</button>}
    </Panel>
  );
}

// the planner's examples are English, so a Chinese storyboard may still say "push in"
const CAMERA: Record<string, string> = {
  fixed: '固定', static: '固定', 'push in': '推近', push: '推近', 'zoom in': '推近', 'pull back': '拉远', 'pull out': '拉远', 'zoom out': '拉远',
  pan: '横移', 'pan left': '左移', 'pan right': '右移', tilt: '上下摇', follow: '跟随', track: '跟随', slam: '猛推', orbit: '环绕',
};
const camera = (c: string) => CAMERA[c.trim().toLowerCase()] || c;

const emptyBeat = (): Beat => ({ at: 'c0', object: '', action: '', camera: '', text: '' });
const BEAT_KEYS = ['at', 'object', 'action', 'camera', 'text'] as const;
const BEAT_LABELS = ['落点', '画什么', '怎么动', '镜头', '上屏文字'];

export default function StoryboardStep() {
  const { p, reload, run, busy } = useProject();
  const [sb, setSb] = useState<Storyboard | null>(p.storyboard);
  const [mode, setMode] = useState<'view' | 'edit' | 'json'>('view');
  const [raw, setRaw] = useState('');
  const [fb, setFb] = useState('');
  useEffect(() => { if (mode === 'view') setSb(p.storyboard); }, [p.storyboard, mode]);

  if (!p.storyboard) {
    return (
      <div className="stack">
        <PageHeader eyebrow="第 2 步" title="分镜" />
        <Empty icon={<LayoutList />} title={busy ? '导演正在写分镜…' : '还没有分镜'} actions={
          <button className="primary large" disabled={busy} onClick={() => run('storyboard/generate')}>{busy ? '有任务在跑…' : <>生成分镜<ArrowRight /></>}</button>}>
          分镜决定每一页讲什么、画什么。导演会根据素材和主题先写一版，你确认后才继续往下做。
        </Empty>
      </div>
    );
  }
  const save = async (next: Storyboard) => {
    try {
      await api.put(`${P(p.id)}/storyboard`, { storyboard: next });
      toast.ok('分镜已保存');
      setMode('view');
      await reload();
    } catch (e) { toast.err(e); }
  };
  const edit = (fn: (s: Storyboard) => void) => {
    const n = structuredClone(sb!) as Storyboard;
    fn(n);
    setSb(n);
  };
  const s = sb!;
  const approved = p.storyboard_status === 'approved';
  const nBeats = s.pages.reduce((n, pg) => n + pg.beats.length, 0);

  const actions = mode === 'view' ? <>
    <button className="ghost" onClick={() => { setRaw(JSON.stringify(p.storyboard, null, 2)); setMode('json'); }}><Braces />JSON</button>
    <button onClick={() => setMode('edit')}><Pencil />编辑</button>
    <button disabled={busy} onClick={() => confirm('重新生成会覆盖当前分镜，确定？') && run('storyboard/generate')}><RefreshCw />重新生成</button>
    {!approved && <button className="primary" disabled={busy} onClick={() => api.post(`${P(p.id)}/storyboard/approve`).then(() => run('script/generate'))}><Check />确认分镜，写口播</button>}
    {approved && <button className="primary" disabled={busy} onClick={() => p.overview.script && !confirm('已经有口播了，按分镜重写会覆盖它，确定？') ? null : run('script/generate')}>
      {p.overview.script ? <><RefreshCw />按分镜重写口播</> : <>写口播<ArrowRight /></>}</button>}
  </> : <>
    <button onClick={() => { setMode('view'); setSb(p.storyboard); }}><X />取消</button>
    <button className="primary" onClick={() => {
      if (mode === 'json') { try { save(JSON.parse(raw)); } catch (e) { toast.err(`JSON 格式不对：${(e as Error).message}`); } }
      else save(s);
    }}><Check />保存</button>
  </>;

  return (
    <div className="stack">
      <PageHeader eyebrow="第 2 步 · 分镜" title={s.title} sticky={mode !== 'view'}
        badge={approved ? <span className="tag ok lg"><Check />已确认</span> : <span className="tag warn lg dot">待你确认</span>}
        desc={s.summary} actions={actions} />
      <div className="row gap-s" style={{ marginTop: -10 }}>
        <span className="tag outline"><Film />{s.pages.length} 页</span>
        <span className="tag outline"><Video />{nBeats} 拍</span>
        <span className="tag outline"><Clock />目标 {fmtTime(s.durationSec || p.duration)}</span>
        <span className="tag outline">{p.style_name}</span>
      </div>

      {p.storyboard_report && mode === 'view' && <DirectorNote>{p.storyboard_report}</DirectorNote>}
      {mode === 'view' && <Issues items={p.storyboard_issues} />}

      {mode === 'json' ? <Code value={raw} onChange={setRaw} lang="json" height="68vh" /> : (
        <div className="stack" style={{ gap: 12 }}>
          {s.pages.map((pg, pi) => (
            <article key={pi} className={`scene ${pg.core ? 'core' : ''}`}>
              <div className="scene-head">
                <span className="scene-no">{pi + 1}</span>
                {mode === 'edit'
                  ? <input className="bare" value={pg.section} onChange={(e) => edit((n) => { n.pages[pi].section = e.target.value; })} style={{ fontWeight: 600, fontSize: 15, flex: 1 }} />
                  : <h3>{pg.section}</h3>}
                {pg.core && mode === 'view' && <span className="tag accent"><Star fill="currentColor" />重点页</span>}
                {mode === 'edit' && <div className="row gap-s">
                  <button className={`small ${pg.core ? 'subtle' : 'ghost'}`} onClick={() => edit((n) => { n.pages[pi].core = !n.pages[pi].core; })}><Star fill={pg.core ? 'currentColor' : 'none'} />重点页</button>
                  <button className="ghost icon small" aria-label="上移" disabled={pi === 0} onClick={() => edit((n) => { [n.pages[pi - 1], n.pages[pi]] = [n.pages[pi], n.pages[pi - 1]]; })}><ArrowUp /></button>
                  <button className="ghost icon small" aria-label="下移" disabled={pi === s.pages.length - 1} onClick={() => edit((n) => { [n.pages[pi + 1], n.pages[pi]] = [n.pages[pi], n.pages[pi + 1]]; })}><ArrowDown /></button>
                  <button className="ghost icon small danger" aria-label="删除页" onClick={() => edit((n) => { n.pages.splice(pi, 1); })}><Trash2 /></button>
                </div>}
              </div>
              {mode === 'edit'
                ? <div style={{ margin: '12px 18px 4px' }}><textarea rows={2} value={pg.say} placeholder="这一页要讲的意思" onChange={(e) => edit((n) => { n.pages[pi].say = e.target.value; })} /></div>
                : pg.say && <div className="scene-say">{pg.say}</div>}
              <div className="beats">
                {mode === 'edit' && <div className="beat-labels">{BEAT_LABELS.map((l) => <span key={l}>{l}</span>)}<span /></div>}
                {pg.beats.map((b, bi) => mode === 'edit' ? (
                  <div key={bi} className="beat edit">
                    {BEAT_KEYS.map((k) => (
                      <input key={k} className={k === 'at' ? 'mono' : ''} value={b[k] || ''} placeholder={BEAT_LABELS[BEAT_KEYS.indexOf(k)]}
                        onChange={(e) => edit((n) => { n.pages[pi].beats[bi][k] = e.target.value; })} />
                    ))}
                    <button className="ghost icon small" aria-label="删除这一拍" onClick={() => edit((n) => { n.pages[pi].beats.splice(bi, 1); })}><X /></button>
                  </div>
                ) : (
                  <div key={bi} className="beat">
                    <span className="at" title={b.at}>{b.at}</span>
                    <div className="what"><b>{b.object}</b>{b.action && <span className="act"> — {b.action}</span>}</div>
                    <div className="side-tags">
                      {b.camera && <span className="tag"><Video />{camera(b.camera)}</span>}
                      {b.text && <span className="onscreen">「{b.text}」</span>}
                    </div>
                  </div>
                ))}
                {mode === 'edit' && <button className="ghost small mt-s" style={{ alignSelf: 'flex-start' }} onClick={() => edit((n) => { n.pages[pi].beats.push(emptyBeat()); })}><Plus />加一拍</button>}
              </div>
            </article>
          ))}
          {mode === 'edit' && <button style={{ alignSelf: 'flex-start' }} onClick={() => edit((n) => { n.pages.push({ id: '', section: '新的一页', say: '', beats: [emptyBeat(), emptyBeat()] }); })}><Plus />加一页</button>}
          <div className="small muted">落点：<span className="mono">c0</span> = 第 1 句开始时；<span className="mono">c2:三十</span> = 第 3 句念到「三十」时。上屏文字每处不超过 8 个字。</div>
        </div>
      )}

      {mode === 'view' && (
        <div className="composer">
          <textarea rows={2} placeholder="告诉导演怎么改。例：第 2 页太抽象，换成一个厨房里的例子；结尾加一个思考题；整体再短一点"
            value={fb} onChange={(e) => setFb(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && fb.trim() && !busy) run('storyboard/revise', { feedback: fb }).then(() => setFb('')); }} />
          <div className="bar-row">
            <span className="who"><Pencil />让导演按你的意见改分镜 · <span className="kbd">⌘ Enter</span> 发送</span>
            <button className="primary small" disabled={busy || !fb.trim()} onClick={() => run('storyboard/revise', { feedback: fb }).then(() => setFb(''))}><Send />修改分镜</button>
          </div>
        </div>
      )}
    </div>
  );
}
