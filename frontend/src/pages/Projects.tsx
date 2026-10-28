import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BookOpen, Clapperboard, FileArchive, GitBranch, Play, Plus, Search, Sparkles, WandSparkles } from 'lucide-react';
import { api, exampleThumb, fileUrl, fmtAgo, fmtTime, type Card, type Example, type Style } from '../api';
import { Empty, Field, Modal, Seg, StylePicker, Thumb, toast } from '../ui';

const DURATIONS = [30, 60, 90, 120, 180, 300];
type Kind = 'topic' | 'github' | 'example';
const KINDS: [Kind, string, string, typeof BookOpen][] = [
  ['topic', '知识讲解', '一个主题或一份资料', BookOpen],
  ['github', 'GitHub 项目', '介绍一个开源仓库', GitBranch],
  ['example', '从样片开始', '现成的完整视频源码', Sparkles],
];

function NewProject({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [tab, setTab] = useState<Kind>('topic');
  const [styles, setStyles] = useState<Style[]>([]);
  const [examples, setExamples] = useState<Example[]>([]);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ topic: '', audience: '', notes: '', text: '', url: '', repo: '', duration: 90, style: 'whiteboard', lang: 'zh' });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  useEffect(() => {
    api.get<Style[]>('/api/styles').then(setStyles).catch(toast.err);
    api.get<Example[]>('/api/examples').then(setExamples).catch(toast.err);
  }, []);

  const create = async (body: Record<string, unknown>) => {
    setBusy(true);
    try {
      const p = await api.post<{ id: string }>('/api/projects', body);
      // a new film starts with its storyboard; a sample film is complete already
      if (!body.example) await api.post(`/api/projects/${p.id}/storyboard/generate`).catch(() => {});
      nav(`/p/${p.id}/${body.example ? 'preview' : 'storyboard'}`);
    } catch (e) {
      toast.err(e);
      setBusy(false);
    }
  };
  const submit = () => {
    if (tab === 'github') {
      if (!/^https?:\/\/(www\.)?github\.com\/[^/]+\/[^/]+/.test(f.repo.trim())) return toast.err('填一个 GitHub 仓库地址，如 https://github.com/owner/repo');
      const name = f.repo.trim().replace(/\/+$/, '').split('/').slice(-1)[0];
      return create({ kind: 'github', repo: f.repo.trim(), url: f.repo.trim(), topic: f.topic || `开源项目 ${name} 介绍`, title: name,
        audience: f.audience, notes: f.notes, duration: f.duration, style: f.style, lang: f.lang, text: f.text });
    }
    if (!f.topic.trim() && !f.text.trim() && !f.url.trim()) return toast.err('至少写一个主题，或给一份素材');
    create({ topic: f.topic, title: f.topic.slice(0, 40), audience: f.audience, notes: f.notes, text: f.text, url: f.url,
      duration: f.duration, style: f.style, lang: f.lang });
  };

  return (
    <Modal title="新建视频" icon={<WandSparkles />} size="wide" onClose={onClose} footer={tab !== 'example' ? (
      <>
        <span className="small muted grow">创建后导演马上开始写分镜，你确认后再往下做。</span>
        <button onClick={onClose}>取消</button>
        <button className="primary" disabled={busy} onClick={submit}><Sparkles />{busy ? '创建中…' : '创建并生成分镜'}</button>
      </>
    ) : <span className="small muted grow">样片打开就能预览，也可以在它的基础上改。</span>}>
      <div className="kinds">
        {KINDS.map(([k, name, sub, Icon]) => (
          <button key={k} type="button" className={`kind ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>
            <span className="ki"><Icon /></span><span><b>{name}</b><small>{sub}</small></span>
          </button>
        ))}
      </div>
      {tab === 'example' ? (
        <div className="examples">
          {examples.map((x) => (
            <button key={x.id} type="button" className="excard" disabled={busy} onClick={() => create({ example: x.id })}>
              <Thumb src={exampleThumb(x.id)} retry={12} />
              <div className="ex-body">
                <b className="clamp2">{x.title}</b>
                <small>{x.style_name || x.style} · {x.pages} 页{x.source === 'app' ? ' · 白板 skill 示例' : ''}</small>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="np">
          <div className="col" style={{ gap: 16 }}>
            {tab === 'github' ? (
              <Field label="仓库地址"><input placeholder="https://github.com/owner/repo" value={f.repo} onChange={set('repo')} autoFocus /></Field>
            ) : (
              <Field label="讲什么"><input placeholder="例：为什么复利是世界第八大奇迹" value={f.topic} onChange={set('topic')} autoFocus /></Field>
            )}
            <Field label="给谁看" optional><input placeholder="例：刚工作的年轻人" value={f.audience} onChange={set('audience')} /></Field>
            <div className="row" style={{ alignItems: 'flex-start', gap: 20 }}>
              <Field label="时长" as="div">
                <Seg small value={f.duration} onChange={(d) => setF({ ...f, duration: d })}
                  options={DURATIONS.map((d) => [d, d < 60 ? `${d}秒` : `${d / 60}分`])} />
              </Field>
              <Field label="语言" as="div">
                <Seg small value={f.lang} onChange={(l) => setF({ ...f, lang: l })} options={[['zh', '中文'], ['en', 'English']]} />
              </Field>
            </div>
            {tab === 'topic' && (
              <Field label="素材网址" optional><input placeholder="文章、文档或 GitHub 仓库链接" value={f.url} onChange={set('url')} /></Field>
            )}
            <Field label={tab === 'github' ? '补充说明' : '素材原文'} optional hint={tab === 'github' ? 'GitHub 打不开时，可以把 README 粘贴在这里。' : '没有素材时导演会按自己的知识写。'}>
              <textarea rows={4} placeholder="粘贴文章、讲稿或笔记" value={f.text} onChange={set('text')} />
            </Field>
            <Field label="其他要求" optional><input placeholder="例：多用生活里的例子，结尾留一个思考题" value={f.notes} onChange={set('notes')} /></Field>
          </div>
          <Field label="画面风格" as="div">
            <StylePicker styles={styles} value={f.style} onChange={(s) => setF({ ...f, style: s })} maxHeight={480} />
          </Field>
        </div>
      )}
    </Modal>
  );
}
function status(p: Card): [string, string] {
  if (p.job) return ['run', p.job.label];
  if (p.film) return ['ok', '已出片'];
  if (p.pages) return ['', `已画 ${p.pages} 页`];
  if (p.storyboard_status === 'draft') return ['warn', '分镜待确认'];
  return ['', '新建'];
}

function ProjectCard({ p }: { p: Card }) {
  const [cls, label] = status(p);
  return (
    <Link to={`/p/${p.id}`} className="pcard">
      <Thumb src={p.thumb ? fileUrl(p.id, p.thumb) : undefined} className="thumb">
        <div className="badges">
          <span className={`tag glass ${cls}`}>{cls === 'run' && <span className="spin sm" />}{label}</span>
        </div>
        <span className="dur">{fmtTime(p.duration)}</span>
        <div className="play"><span><Play size={18} fill="currentColor" /></span></div>
      </Thumb>
      <div className="body">
        <div className="title clamp2">{p.title}</div>
        <div className="meta"><span>{p.style_name}</span><span className="sep" /><span>{fmtAgo(p.updated)}更新</span></div>
      </div>
    </Link>
  );
}

export default function Projects() {
  const [list, setList] = useState<Card[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<'all' | 'doing' | 'done'>('all');
  const fileRef = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const load = () => api.get<Card[]>('/api/projects').then(setList).catch(toast.err);
  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  const importZip = async (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const p = await api.post<{ id: string }>('/api/projects/import', fd);
      nav(`/p/${p.id}`);
    } catch (e) {
      toast.err(e);
    }
  };
  const shown = useMemo(() => (list || []).filter((p) =>
    (!q.trim() || p.title.toLowerCase().includes(q.trim().toLowerCase()))
    && (filter === 'all' || (filter === 'done' ? !!p.film : !p.film))), [list, q, filter]);
  const done = (list || []).filter((p) => p.film).length;

  return (
    <div className="page">
      <div className="hero">
        <div>
          <h1>我的视频</h1>
          <p>{list?.length ? `共 ${list.length} 部 · ${done} 部已出片` : '写下主题，导演出分镜，确认后自动写口播、配音、画画面、渲染成片。'}</p>
        </div>
        <div className="row">
          <input ref={fileRef} type="file" accept=".zip" hidden onChange={(e) => e.target.files?.[0] && importZip(e.target.files[0])} />
          <button onClick={() => fileRef.current?.click()}><FileArchive />导入项目包</button>
          <button className="primary" onClick={() => setCreating(true)}><Plus />新建视频</button>
        </div>
      </div>

      {list === null ? (
        <div className="projects">{[0, 1, 2].map((i) => <div key={i} className="pcard"><div className="thumb shimmer" style={{ aspectRatio: '16/9' }} /><div className="body"><div className="shimmer" style={{ height: 14, borderRadius: 4, width: '70%' }} /></div></div>)}</div>
      ) : list.length === 0 ? (
        <Empty icon={<Clapperboard />} title="还没有视频" actions={<>
          <button className="primary large" onClick={() => setCreating(true)}><Plus />新建第一部视频</button>
        </>}>
          写下一个主题（或给一份资料），导演会先出分镜；你确认后，口播、配音、画面和成片都会自动完成。也可以从现成的样片开始。
        </Empty>
      ) : (
        <>
          <div className="toolbar">
            <div className="search"><Search /><input placeholder="搜索标题" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            <Seg small value={filter} onChange={setFilter} options={[['all', '全部'], ['doing', '制作中'], ['done', '已出片']]} />
          </div>
          <div className="projects">
            <button className="newcard" onClick={() => setCreating(true)}>
              <span className="plus"><Plus /></span>
              <b>新建视频</b>
              <small>知识讲解 · GitHub 项目 · 样片</small>
            </button>
            {shown.map((p) => <ProjectCard key={p.id} p={p} />)}
          </div>
          {shown.length === 0 && <div className="muted small mt">没有符合条件的视频。</div>}
        </>
      )}
      {creating && <NewProject onClose={() => setCreating(false)} />}
    </div>
  );
}
