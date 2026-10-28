import { useEffect, useState } from 'react';
import {
  Code as CodeIcon, Grid3x3, Image as ImageIcon, Maximize2, Paintbrush, RefreshCw, ScanSearch, Send, Star, Wand2, WandSparkles,
} from 'lucide-react';
import { api, fileUrl, fmtDate, P, pageThumb, type PageState } from '../../api';
import { Code, Empty, Lightbox, Modal, Notice, PageHeader, StatusTag, Thumb, toast } from '../../ui';
import { useProject } from '../Workspace';

function CodeModal({ pid, page, onClose, onSaved, busy }: { pid: string; page: string; onClose: () => void; onSaved: (check: boolean) => void; busy: boolean }) {
  const [code, setCode] = useState<string | null>(null);
  useEffect(() => { api.get<{ code: string }>(`${P(pid)}/pages/${page}/code`).then((x) => setCode(x.code)).catch(toast.err); }, [pid, page]);
  const save = async (check: boolean) => {
    try {
      await api.put(`${P(pid)}/pages/${page}/code`, { code });
      toast.ok('已保存');
      onSaved(check);
    } catch (e) { toast.err(e); }
  };
  return (
    <Modal title={<span className="mono">pages/{page}.js</span>} icon={<CodeIcon />} size="wide" onClose={onClose} footer={<>
      <span className="small muted grow">纯函数时间轴：不要用 Math.random / Date.now；颜色只写语义名。保存后预览立刻生效。</span>
      <button onClick={onClose}>关闭</button>
      <button disabled={busy || code === null} onClick={() => save(false)}>保存</button>
      <button className="primary" disabled={busy || code === null} onClick={() => save(true)}><ScanSearch />保存并质检</button>
    </>}>
      {code === null ? <div className="muted">加载中…</div> : <Code value={code} onChange={setCode} height="68vh" />}
    </Modal>
  );
}

const RUNNING = ['drawing', 'checking', 'reviewing', 'fixing'];

function PageCard({ id, st, title, onZoom, onCode }: { id: string; st: PageState; title: string; onZoom: (s: string) => void; onCode: () => void }) {
  const { p, run, busy, reload } = useProject();
  const [ask, setAsk] = useState(false);
  const [change, setChange] = useState('');
  const errs = (st.issues || []).filter((i) => i.level === 'error');
  const warns = (st.issues || []).filter((i) => i.level !== 'error');
  const sheet = st.sheet ? fileUrl(p.id, `${st.sheet}?v=${st.updated || 0}`) : '';
  const still = pageThumb(p, id);
  const bad = st.status === 'failed' || !!st.crash;
  const hasProblems = errs.length > 0 || (st.problems || []).length > 0 || !!st.crash;
  const placeholder = (
    <div className="ph label">
      {RUNNING.includes(st.status || '') ? <><span className="spin" />正在{st.status === 'drawing' ? '画' : '检查'}…</> : st.sheet ? <ImageIcon /> : <><Paintbrush />还没画</>}
    </div>
  );
  return (
    <div className={`pg ${bad ? 'is-bad' : st.status === 'flagged' ? 'is-warn' : ''}`}>
      <Thumb src={still || (sheet || undefined)} fallback={placeholder} className={RUNNING.includes(st.status || '') ? 'busy' : ''}
        onClick={() => sheet && onZoom(sheet)}>
        <div className="ov">
          <span className="pid">{id}</span>
          <StatusTag status={st.status} glass />
          {st.rounds ? <span className="tag glass">{st.rounds} 轮</span> : null}
          <span className="grow" />
          {p.cover === id && <span className="tag glass warn"><Star fill="currentColor" />封面</span>}
        </div>
        {sheet && <span className="zoom tag glass"><Maximize2 />看检查截图</span>}
      </Thumb>
      <div className="info">
        <div className="t ellipsis">{title || id}</div>
        {st.say && <div className="say clamp3">{st.say}</div>}
        {st.note && <div className="small warn-text">{st.note}</div>}
        {hasProblems && (
          <div className="probs">
            {st.crash && <div className="err-text">运行出错：{st.crash.split('\n')[0]}</div>}
            {errs.map((i, k) => <div key={k} className="err-text"><span className="at">{i.local?.toFixed?.(1)}s</span>{i.zh || i.msg}</div>)}
            {(st.problems || []).map((x, k) => <div key={`r${k}`} className="warn-text"><span className="at">{x.at?.toFixed?.(1)}s</span>{x.what}</div>)}
          </div>
        )}
        {warns.length > 0 && <div className="tiny muted" title={warns.map((w) => w.zh || w.msg).join('\n')}>另有 {warns.length} 条提示（悬停查看）</div>}
        {ask && (
          <div className="ask">
            <textarea rows={2} autoFocus placeholder="例：右边的钟再大一点；数字等念到「三十」再出现；去掉底部那行字" value={change} onChange={(e) => setChange(e.target.value)} />
            <div className="row end gap-s">
              <button className="ghost small" onClick={() => setAsk(false)}>取消</button>
              <button className="primary small" disabled={busy || !change.trim()} onClick={() => { run(`pages/${id}/redo`, { mode: 'change', change }); setAsk(false); setChange(''); }}><Send />让模型改</button>
            </div>
          </div>
        )}
        <div className="tools">
          <button className="ghost small" disabled={busy} onClick={() => setAsk(!ask)}><Wand2 />改…</button>
          <button className="ghost small" disabled={busy} onClick={() => run(`pages/${id}/redo`, { mode: 'check' })} title="检查这页，有问题就让模型修"><ScanSearch />检查</button>
          <button className="ghost small" disabled={busy} onClick={() => confirm(`从头重画 ${id}？`) && run(`pages/${id}/redo`, { mode: 'redraw' })}><RefreshCw />重画</button>
          <button className="ghost small" onClick={onCode}><CodeIcon />代码</button>
          <span className="grow" />
          <button className={`ghost icon small ${p.cover === id ? 'warn-text' : ''}`} title={p.cover === id ? '取消封面' : '设为封面（成片第一帧用这页）'}
            onClick={() => api.patch(P(p.id), { cover: p.cover === id ? '' : id }).then(reload).catch(toast.err)}>
            <Star fill={p.cover === id ? 'currentColor' : 'none'} />
          </button>
        </div>
      </div>
    </div>
  );
}

export default function PagesStep() {
  const { p, run, busy, reload } = useProject();
  const [zoom, setZoom] = useState('');
  const [code, setCode] = useState('');
  const pages = p.script.PAGES;
  if (!p.overview.script) {
    return <div className="stack"><PageHeader eyebrow="第 5 步" title="画面" /><Empty icon={<ImageIcon />} title="先完成口播">口播写好后，模型逐页写绘图代码，再自动质检和修改。</Empty></div>;
  }
  const states = pages.map((pg) => p.pages[pg.id] || {});
  const count = (f: (s: PageState) => boolean) => states.filter(f).length;
  const nOk = count((s) => s.status === 'done' || s.status === 'edited');
  const nWarn = count((s) => s.status === 'flagged');
  const nBad = count((s) => s.status === 'failed');
  const undrawn = pages.filter((pg) => !p.pages[pg.id] || ['failed', 'queued', undefined].includes(p.pages[pg.id].status)).length;
  const n = pages.length || 1;
  const fc = p.film_check;
  return (
    <div className="stack">
      <PageHeader eyebrow="第 5 步" title="画面"
        desc="每页由模型写成绘图代码，再在浏览器里做机器检查（出界、压字幕、重叠、字太小）和看图审片，有问题就退回去改。点画面看检查截图。"
        actions={<>
          <button className="ghost" disabled={busy} onClick={() => confirm('所有页面从头重画？') && run('pages/generate', { redo: true })}><RefreshCw />全部重画</button>
          <button disabled={busy || !p.overview.pages_drawn} onClick={() => run('check', { fix: false })}><ScanSearch />全片质检</button>
          <button disabled={busy || !p.overview.pages_drawn} onClick={() => run('check', { fix: true })} title="质检后把有必改问题的页交给模型修"><WandSparkles />质检并自动修</button>
          <button className="primary" disabled={busy || undrawn === 0} onClick={() => run('pages/generate')}><Paintbrush />{undrawn ? `画未完成的 ${undrawn} 页` : '都画好了'}</button>
        </>} />

      {p.overview.voice === 'stale' && <Notice kind="warn">口播改过，建议先重新配音，画面时间才对得上。</Notice>}

      <div className="summary-bar">
        <b className="small">{p.overview.pages_drawn}/{pages.length} 页已画</b>
        <div className="bar">
          <div style={{ width: `${(nOk / n) * 100}%` }} />
          <div className="w" style={{ width: `${(nWarn / n) * 100}%` }} />
          <div className="e" style={{ width: `${(nBad / n) * 100}%` }} />
        </div>
        <div className="legend">
          <span><i style={{ background: 'var(--ok)' }} />通过 {nOk}</span>
          <span><i style={{ background: 'var(--warn)' }} />需关注 {nWarn}</span>
          <span><i style={{ background: 'var(--err)' }} />失败 {nBad}</span>
        </div>
      </div>

      {fc && (
        <Notice kind={fc.bad.length ? 'warn' : 'ok'}>
          <div className="row between">
            <span>全片质检（{fmtDate(fc.at)}）：{fc.bad.length ? `${fc.bad.join('、')} 有必改问题` : '没有必改问题'} · 共 {fc.issues.length} 条</span>
            {fc.sheet && <button className="small" onClick={() => setZoom(fileUrl(p.id, fc.sheet))}><Grid3x3 />看全片拼图</button>}
          </div>
        </Notice>
      )}

      <div className="pages-grid">
        {pages.map((pg) => <PageCard key={pg.id} id={pg.id} title={pg.title || pg.section || ''} st={p.pages[pg.id] || {}} onZoom={setZoom} onCode={() => setCode(pg.id)} />)}
      </div>
      {zoom && <Lightbox src={zoom} title="检查截图" onClose={() => setZoom('')} />}
      {code && <CodeModal pid={p.id} page={code} busy={busy} onClose={() => setCode('')}
        onSaved={(check) => { setCode(''); if (check) run(`pages/${code}/redo`, { mode: 'check' }); else reload(); }} />}
    </div>
  );
}
