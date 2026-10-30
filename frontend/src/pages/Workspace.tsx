import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom';
import {
  AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronUp, CircleAlert, Cpu, FileText, Film, FolderOpen,
  Image as ImageIcon, LayoutList, Mic, MonitorPlay, Play, Settings2, Square, Terminal, X,
} from 'lucide-react';
import { api, coverThumb, fmtTime, P, type JobLog, type JobSummary, type Project } from '../api';
import { PageBoundary, Spinner, Thumb, toast } from '../ui';
import Materials from './steps/Materials';
import StoryboardStep from './steps/Storyboard';
import ScriptStep from './steps/Script';
import VoiceStep from './steps/Voice';
import PagesStep from './steps/Pages';
import PreviewStep from './steps/Preview';
import FilmStep from './steps/Film';
import InfoStep from './steps/Info';

interface Ctx {
  p: Project;
  reload: () => Promise<void>;
  /** start a stage: POST to the project's `path`; the job dock follows it */
  run: (path: string, body?: unknown) => Promise<void>;
  busy: boolean;
  /** the job running now, if any */
  job: JobSummary | null;
}
const C = createContext<Ctx>(null as unknown as Ctx);
export const useProject = () => useContext(C);

function JobDock({ pid, job, onEnd, onClose }: { pid: string; job: JobSummary; onEnd: () => void; onClose: () => void }) {
  const [log, setLog] = useState<JobLog | null>(null);
  const [open, setOpen] = useState(false);
  const lines = useRef<JobLog['lines']>([]);
  const since = useRef(0);
  const box = useRef<HTMLPreElement>(null);
  useEffect(() => {
    lines.current = [];
    since.current = 0;
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.get<JobLog>(`${P(pid)}/jobs/${job.id}?since=${since.current}`);
        lines.current = [...lines.current, ...j.lines].slice(-800);
        since.current = j.next;
        setLog({ ...j, lines: lines.current });
        if (j.status !== 'running') {
          onEnd();
          if (j.status === 'failed') { toast.err(`${j.label}失败：${j.error}`); setOpen(true); }
          else if (j.status === 'done') toast.ok(`${j.label}：${j.result || '完成'}`);
          return;
        }
      } catch { /* keep polling */ }
      if (!stop) setTimeout(tick, 1500);
    };
    tick();
    return () => { stop = true; };
  }, [pid, job.id]);
  useEffect(() => { if (open && box.current) box.current.scrollTop = box.current.scrollHeight; }, [log, open]);
  const s = log || { ...job, lines: [], next: 0 };
  const pr = s.progress || {};
  const pct = pr.total ? Math.round(((pr.done || 0) / pr.total) * 100) : null;
  const last = s.status === 'failed' ? s.error : s.status === 'done' ? (s.result || '完成') : s.lines.filter((l) => l.msg.trim()).slice(-1)[0]?.msg || '准备中…';
  const t0 = s.started;
  const icon = { running: <Spinner />, done: <Check />, failed: <CircleAlert />, cancelled: <Square /> }[s.status];
  return (
    <div className="dock">
      <div className="dock-head" onClick={() => setOpen(!open)}>
        <span className={`state ${s.status}`}>{icon}</span>
        <div className="what">
          <div className="l1">
            <b>{s.label}</b>
            {s.status === 'running' && <div className={`bar ${pct === null ? 'indeterminate' : ''}`}><div style={{ width: `${pct ?? 0}%` }} /></div>}
            {pct !== null && <span className="count">{pr.done}/{pr.total}{pr.phase && pr.phase !== 'video' ? ` · ${pr.phase === 'audio' ? '混音' : '字幕'}` : ''}</span>}
          </div>
          <div className="l2">{last}</div>
        </div>
        {s.status === 'running' && (
          <button className="small danger" onClick={(e) => { e.stopPropagation(); api.post(`${P(pid)}/jobs/${job.id}/cancel`).catch(toast.err); }}>
            <Square />取消
          </button>
        )}
        <button className="ghost small" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          <Terminal />日志{open ? <ChevronDown /> : <ChevronUp />}
        </button>
        {s.status !== 'running' && (
          <button className="ghost icon small" aria-label="关闭" onClick={(e) => { e.stopPropagation(); onClose(); }}><X /></button>
        )}
      </div>
      {open && (
        <pre className="log" ref={box}>
          {s.lines.length === 0 && <span className="ts">还没有输出</span>}
          {s.lines.map((l, i) => (
            <div key={i} className={l.level}><span className="ts">{fmtTime(Math.max(0, l.t - t0))}</span>{l.msg}</div>
          ))}
        </pre>
      )}
    </div>
  );
}
const STEPS: { path: string; name: string; hint: string; icon: typeof FileText }[] = [
  { path: 'materials', name: '素材', hint: '资料、图片', icon: FolderOpen },
  { path: 'storyboard', name: '分镜', hint: '每页讲什么、画什么', icon: LayoutList },
  { path: 'script', name: '口播', hint: '每一句台词', icon: FileText },
  { path: 'voice', name: '配音', hint: '逐句配音、自录', icon: Mic },
  { path: 'pages', name: '画面', hint: '逐页绘制与质检', icon: ImageIcon },
  { path: 'preview', name: '预览', hint: '浏览器里直接看', icon: MonitorPlay },
  { path: 'film', name: '成片', hint: '渲染、下载、发布', icon: Film },
];

export default function Workspace() {
  const { pid = '' } = useParams();
  const loc = useLocation();
  const [p, setP] = useState<Project | null>(null);
  const [err, setErr] = useState('');
  const [job, setJob] = useState<JobSummary | null>(null);
  const [lastJob, setLastJob] = useState<JobSummary | null>(null);
  const reload = useCallback(async () => {
    try {
      const x = await api.get<Project>(P(pid));
      setP(x);
      if (x.job) { setJob(x.job); setLastJob(x.job); } else setJob(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [pid]);
  useEffect(() => { reload(); }, [reload]);
  // while a job runs, the pages' states change under it
  useEffect(() => {
    if (!job) return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [job, reload]);

  const run = useCallback(async (path: string, body?: unknown) => {
    try {
      const j = await api.post<JobSummary>(`${P(pid)}/${path}`, body ?? {});
      setJob(j);
      setLastJob(j);
    } catch (e) {
      toast.err(e);
    }
  }, [pid]);

  if (err) return <div className="page"><div className="empty"><h3>打不开这个项目</h3><p>{err}</p><div className="row"><Link className="btn" to="/">回到项目</Link></div></div></div>;
  if (!p) return <div className="page"><div className="row muted"><Spinner />加载中…</div></div>;
  const o = p.overview;
  const flagged = Object.values(p.pages).filter((x) => x.status === 'flagged' || x.status === 'failed').length;
  const state: Record<string, 'done' | 'warn' | ''> = {
    materials: p.materials.length || p.assets_files.length ? 'done' : '',
    storyboard: o.storyboard_status === 'approved' ? 'done' : o.storyboard ? 'warn' : '',
    script: o.script ? 'done' : '',
    voice: o.voice === 'ok' || o.voice === 'off' ? 'done' : o.voice === 'stale' ? 'warn' : '',
    pages: o.pages_total && o.pages_drawn === o.pages_total ? (flagged ? 'warn' : 'done') : o.pages_drawn ? 'warn' : '',
    preview: o.pages_drawn ? 'done' : '',
    film: o.film ? (o.film_stale ? 'warn' : 'done') : '',
  };
  const running = job?.status === 'running' ? job.kind : '';
  const runningStep = { storyboard: 'storyboard', storyboard_revise: 'storyboard', script: 'script', voice: 'voice', pages: 'pages', page: 'pages', check: 'pages', render: 'film', publish: 'film' }[running] || '';
  const sub: Record<string, [string, boolean?]> = {
    storyboard: o.storyboard_status === 'draft' ? ['待你确认', true] : o.storyboard_status === 'approved' ? ['已确认'] : ['', false],
    voice: ({ ok: ['已配音'], stale: ['口播改了，需重配', true], none: [''], off: ['不配音'] } as Record<string, [string, boolean?]>)[o.voice],
    pages: o.pages_total ? [`${o.pages_drawn}/${o.pages_total} 页${flagged ? ` · ${flagged} 页需关注` : ''}`, !!flagged] : [''],
    film: o.film ? (o.film_stale ? ['有改动，可重渲', true] : ['已出片']) : [''],
  };
  const stepIcon = (path: string, Icon: typeof FileText) =>
    runningStep === path ? <Spinner small /> : state[path] === 'done' ? <Check strokeWidth={3} /> : state[path] === 'warn' ? <AlertTriangle /> : <Icon />;
  const autoLabel = o.film && !o.film_stale ? '检查并补全' : o.storyboard_status === 'draft' ? '确认分镜后继续' : '继续自动完成';

  return (
    <C.Provider value={{ p, reload, run, busy: job?.status === 'running', job: job?.status === 'running' ? job : null }}>
      <div className="ws">
        <aside className="side">
          <Link to="/" className="back"><ChevronLeft />全部视频</Link>
          <div className="proj">
            <Thumb src={coverThumb(p)} />
            <div className="info">
              <div className="t clamp2">{o.title}</div>
              <div className="m"><span className="tag">{p.style_name}</span><span className="tag">目标 {fmtTime(p.duration)}</span></div>
            </div>
          </div>
          <nav className="steps">
            <div className="group">制作流程</div>
            {STEPS.map((s, i) => {
              const [hint, warn] = sub[s.path] || [''];
              return (
                <NavLink key={s.path} to={`/p/${pid}/${s.path}`} className={({ isActive }) => `step ${i ? 'chain' : ''} ${i && state[STEPS[i - 1].path] === 'done' ? 'prev-done' : ''} ${isActive ? 'active' : ''}`}>
                  <span className={`si ${runningStep === s.path ? 'run' : state[s.path]}`}>{stepIcon(s.path, s.icon)}</span>
                  <span className="st"><b>{s.name}</b><small className={warn ? 'warn' : ''}>{runningStep === s.path ? '进行中…' : hint || s.hint}</small></span>
                </NavLink>
              );
            })}
            <div className="group">项目</div>
            <NavLink to={`/p/${pid}/info`} className={({ isActive }) => `step ${isActive ? 'active' : ''}`}>
              <span className="si"><Settings2 /></span>
              <span className="st"><b>项目设置</b><small>风格、时长、音乐</small></span>
            </NavLink>
          </nav>
          <div className="auto">
            <button className="primary block" disabled={!!running}
              title="把还没做的步骤依次做完，直到出片（分镜需要你先确认）"
              onClick={() => run('auto', { skip_approval: false })}>
              {running ? <><Spinner small />{job?.label}</> : <><Play fill="currentColor" />{autoLabel}</>}
            </button>
            <div className="usage"><Cpu />模型 {p.usage.calls} 次 · {Math.round((p.usage.input + p.usage.output) / 1000)}k tokens</div>
          </div>
        </aside>
        <main className="ws-main">
          <PageBoundary resetKey={loc.pathname}>
          <Routes>
            <Route index element={<Navigate to={`/p/${pid}/${o.film ? 'film' : o.pages_drawn ? 'pages' : o.script ? 'voice' : o.storyboard ? 'storyboard' : 'materials'}`} replace />} />
            <Route path="materials" element={<Materials />} />
            <Route path="storyboard" element={<StoryboardStep />} />
            <Route path="script" element={<ScriptStep />} />
            <Route path="voice" element={<VoiceStep />} />
            <Route path="pages" element={<PagesStep />} />
            <Route path="preview" element={<PreviewStep />} />
            <Route path="film" element={<FilmStep />} />
            <Route path="info" element={<InfoStep />} />
            {/* an unknown or nested step path goes back to the project's current step */}
            <Route path="*" element={<Navigate to={`/p/${pid}`} replace />} />
          </Routes>
          </PageBoundary>
        </main>
      </div>
      {lastJob && <JobDock key={lastJob.id} pid={pid} job={lastJob} onEnd={() => { setJob(null); reload(); }} onClose={() => setLastJob(null)} />}
    </C.Provider>
  );
}
