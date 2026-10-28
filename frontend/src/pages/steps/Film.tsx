import { useEffect, useState } from 'react';
import {
  Captions, Clapperboard, Copy, Download, Eraser, ExternalLink, File, FileArchive, FileText, FileVideo, Film, Megaphone, Rocket, Sparkles, Trash2, Zap,
} from 'lucide-react';
import { api, fileUrl, fmtDate, fmtSize, P } from '../../api';
import { Field, Notice, PageHeader, Panel, Seg, Switch, toast } from '../../ui';
import { useProject } from '../Workspace';

const PLATFORMS: [string, string][] = [['bilibili', 'B 站'], ['youtube', 'YouTube'], ['douyin', '抖音'], ['shipinhao', '视频号'], ['xiaohongshu', '小红书']];

function fileIcon(name: string) {
  if (name.endsWith('.mp4')) return <FileVideo />;
  if (name.endsWith('.srt')) return <Captions />;
  if (name.endsWith('.md') || name.endsWith('.txt')) return <FileText />;
  return <File />;
}
const copy = (t: string) => navigator.clipboard.writeText(t).then(() => toast.ok('已复制')).catch(toast.err);

export default function FilmStep() {
  const { p, run, busy, reload, job } = useProject();
  // the files are rewritten while a render runs: no player on a half-written file (it would restart on every poll)
  const rendering = job?.kind === 'render' || (job?.kind === 'auto' && job.progress?.phase !== undefined);
  const [fps, setFps] = useState(30);
  const [workers, setWorkers] = useState(3);
  const [subs, setSubs] = useState(true);
  useEffect(() => {
    api.get<{ render: { fps: number; workers: number } }>('/api/settings').then((s) => { setFps(s.render.fps); setWorkers(s.render.workers); }).catch(() => {});
  }, []);
  const films = p.outputs.filter((f) => f.name.endsWith('.mp4'));
  const docs = p.outputs.filter((f) => !f.name.endsWith('.mp4'));
  const [pick, setPick] = useState('');
  const shown = films.find((f) => f.name === pick) || films[0];
  const missing = p.overview.pages_total - p.overview.pages_drawn;
  const last = p.renders[0];

  return (
    <div className="stack">
      <PageHeader eyebrow="第 7 步" title="成片"
        badge={films.length ? (p.overview.film_stale ? <span className="tag warn lg dot">有新改动</span> : <span className="tag ok lg">已出片</span>) : undefined}
        desc={<>分段并行渲染，改一页只重渲受影响的片段，其余直接复用缓存。{p.webgl && ' 这是 3D 风格：服务器没有 GPU 时用软件渲染，会慢很多。'}</>} />

      <div className="film-layout">
        <div className="stack">
          {rendering ? (
            <div className="noplay">
              <span className="spin" style={{ width: 32, height: 32, borderWidth: 3, color: '#a99fff' }} />
              <b>正在渲染…</b>
              <span className="small">{job?.progress?.total ? `${job.progress.done || 0}/${job.progress.total} 段` : '准备中'} · 完成后自动显示新成片，进度看底部任务栏</span>
            </div>
          ) : shown ? (
            <section className="panel" style={{ overflow: 'hidden' }}>
              <video className="film" key={`${shown.name}-${shown.mtime}`} src={`${fileUrl(p.id, `out/${shown.name}`)}?v=${shown.mtime}`} controls preload="metadata" />
              <div className="panel-head" style={{ borderBottom: 0, borderTop: '1px solid var(--line)' }}>
                <div className="titles">
                  <h2 className="ellipsis">{shown.name}</h2>
                  <div className="sub">{fmtDate(shown.mtime)} · {fmtSize(shown.size)}{last && ` · ${last.fps}fps · 渲染用时 ${last.seconds} 秒`}</div>
                </div>
                {films.length > 1 && <Seg small value={shown.name} onChange={setPick} options={films.map((f) => [f.name, f.name.includes('有字幕') ? '有字幕' : f.name.includes('无字幕') ? '无字幕' : f.name.replace(/\.mp4$/, '')])} />}
                <a className="btn primary" href={fileUrl(p.id, `out/${shown.name}`, true)}><Download />下载</a>
              </div>
            </section>
          ) : (
            <div className="noplay">
              <Clapperboard />
              <b>还没有成片</b>
              <span className="small">在右边选好参数，点「渲染成片」。{missing > 0 ? `还有 ${missing} 页没画，会显示成标题页。` : ''}</span>
            </div>
          )}
          {p.overview.film_stale && shown && <Notice kind="warn">渲染之后口播、配音或画面又改过，这个文件是旧的，重新渲染即可（只重渲改过的部分）。</Notice>}

          <Panel title="发布文案" icon={<Megaphone />} sub="按口播内容生成各平台的标题、简介和标签"
            actions={<button className="small" disabled={busy || !p.overview.script} onClick={() => run('publish')}><Sparkles />{p.publish ? '重新生成' : '生成'}</button>}>
            {p.publish ? (
              <div className="col">
                <div>
                  {PLATFORMS.map(([k, n]) => p.publish!.titles[k] && (
                    <div key={k} className="plat">
                      <span className="pn">{n}</span><span className="pt">{p.publish!.titles[k]}</span>
                      <button className="ghost icon small" title="复制" onClick={() => copy(p.publish!.titles[k])}><Copy /></button>
                    </div>
                  ))}
                </div>
                <div className="scene-say" style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{p.publish.description}</div>
                <div className="row between">
                  <div className="chips">{p.publish.tags.map((t) => <span key={t} className="tag">#{t}</span>)}</div>
                  <button className="ghost small" onClick={() => copy(`${p.publish!.description}\n\n${p.publish!.tags.map((t) => `#${t}`).join(' ')}`)}><Copy />复制简介和标签</button>
                </div>
                <div className="tiny muted">完整版（含按章节自动算好的时间戳）在下面的「发布信息.md」。</div>
              </div>
            ) : <div className="muted small">B 站、YouTube、抖音、视频号、小红书，一次生成。</div>}
          </Panel>

          <Panel title="文件" icon={<FileArchive />} sub="成片、字幕、口播稿和项目包" body="flush">
            <div className="files">
              {[...films, ...docs].map((f) => (
                <div key={f.name} className="frow">
                  <span className={`fi ${f.name.endsWith('.mp4') ? 'video' : ''}`}>{fileIcon(f.name)}</span>
                  <div className="grow"><div className="fname ellipsis">{f.name}</div><div className="fmeta">{fmtSize(f.size)} · {fmtDate(f.mtime)}</div></div>
                  {!f.name.endsWith('.mp4') && <a className="btn ghost small" href={fileUrl(p.id, `out/${f.name}`)} target="_blank" rel="noreferrer"><ExternalLink />查看</a>}
                  <a className="btn ghost small" href={fileUrl(p.id, `out/${f.name}`, true)}><Download />下载</a>
                  {f.name.endsWith('.mp4') && <button className="ghost icon small danger" title="删除" onClick={() => confirm(`删除 ${f.name}？`) && api.del(`${P(p.id)}/outputs/${encodeURIComponent(f.name)}`).then(reload).catch(toast.err)}><Trash2 /></button>}
                </div>
              ))}
              <div className="frow">
                <span className="fi"><FileArchive /></span>
                <div className="grow"><div className="fname">整个项目</div><div className="fmeta">源码、配音、素材，可再导入</div></div>
                <a className="btn ghost small" href={`${P(p.id)}/export`}><Download />导出 zip</a>
              </div>
            </div>
          </Panel>
        </div>

        <div className="aside">
          <Panel title="渲染" icon={<Film />}
            foot={<div className="col" style={{ width: '100%', gap: 8 }}>
              <button className="primary large block" disabled={busy} onClick={() => run('render', { fps, workers, subs })}><Rocket />{films.length ? '重新渲染' : '渲染成片'}</button>
              <div className="row nowrap">
                <button className="grow" disabled={busy} onClick={() => run('render', { draft: true, workers })} title="24fps、不烧字幕，先看个大概"><Zap />快速出粗片</button>
                <button className="ghost" disabled={busy} title="清掉渲染缓存，下次全部重渲" onClick={() => confirm('清掉渲染缓存？下次会全部重渲。') && api.post(`${P(p.id)}/render/clear-cache`).then(() => toast.ok('缓存已清')).catch(toast.err)}><Eraser />清缓存</button>
              </div>
            </div>}>
            <div className="col" style={{ gap: 16 }}>
              {missing > 0 && <Notice kind="warn">还有 {missing} 页没画，会显示成标题页。</Notice>}
              {(p.overview.voice === 'stale' || p.overview.voice === 'none') && <Notice>口播还没配音或改过：渲染前会先自动配音。</Notice>}
              <Field label="帧率" as="div" hint={fps === 60 ? '顺滑，但渲染慢一倍' : fps === 24 ? '最快' : '推荐'}>
                <Seg value={fps} onChange={setFps} options={[[24, '24'], [30, '30'], [60, '60']]} />
              </Field>
              <Field label="并行浏览器数" hint="每路一个 Chrome，约占 1 核 CPU、400MB 内存。">
                <input type="number" min={1} max={16} value={workers} onChange={(e) => setWorkers(+e.target.value)} />
              </Field>
              <Switch checked={subs} onChange={setSubs} hint="字幕直接画进视频，适合手机平台">同时出一版烧录字幕的</Switch>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
