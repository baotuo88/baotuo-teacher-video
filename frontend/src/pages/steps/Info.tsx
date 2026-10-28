import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Download, FileText, Music, Palette, Replace, Trash2, TriangleAlert, Upload } from 'lucide-react';
import { api, fileUrl, P, type Style } from '../../api';
import { Field, PageHeader, Panel, Seg, StylePicker, toast } from '../../ui';
import { useProject } from '../Workspace';

export default function InfoStep() {
  const { p, reload, busy } = useProject();
  const nav = useNavigate();
  const [styles, setStyles] = useState<Style[]>([]);
  const init = { title: p.title, topic: p.topic, audience: p.audience, notes: p.notes, duration: p.duration, style: p.style, lang: p.lang, repo: p.repo };
  const [f, setF] = useState(init);
  const [vol, setVol] = useState(p.bgm?.vol ?? -20);
  const bgmRef = useRef<HTMLInputElement>(null);
  useEffect(() => { api.get<Style[]>('/api/styles').then(setStyles).catch(toast.err); }, []);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const dirty = (Object.keys(init) as (keyof typeof init)[]).some((k) => String(f[k]) !== String(init[k]));
  const save = async () => {
    if (f.style !== p.style && p.overview.pages_drawn && !confirm('换风格后，已画的页面还是按旧风格写的代码，配色会自动跟着变，但构图最好重画。继续？')) return;
    try {
      await api.patch(P(p.id), { ...f, duration: +f.duration });
      toast.ok('已保存');
      await reload();
    } catch (e) { toast.err(e); }
  };
  const uploadBgm = async (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('vol', String(vol));
    try { await api.post(`${P(p.id)}/bgm`, fd); toast.ok('背景音乐已加上（讲话时自动压低）'); await reload(); } catch (e) { toast.err(e); }
  };

  return (
    <div className="stack">
      <PageHeader title="项目设置" sticky={dirty}
        actions={<>
          {dirty && <span className="small warn-text">有未保存的修改</span>}
          <button className="primary" disabled={!dirty} onClick={save}><Check />保存</button>
        </>} />

      <Panel title="基本信息" icon={<FileText />}>
        <div className="col" style={{ gap: 16 }}>
          <div className="grid2">
            <Field label="标题"><input value={f.title} onChange={set('title')} /></Field>
            <Field label="主题"><input value={f.topic} onChange={set('topic')} /></Field>
            <Field label="受众"><input value={f.audience} onChange={set('audience')} /></Field>
            <div className="grid2">
              <Field label="目标时长（秒）"><input type="number" min={20} max={600} value={f.duration} onChange={set('duration')} /></Field>
              <Field label="语言" as="div"><Seg value={f.lang} onChange={(l) => setF({ ...f, lang: l })} options={[['zh', '中文'], ['en', 'English']]} /></Field>
            </div>
          </div>
          {p.kind === 'github' && <Field label="仓库地址"><input value={f.repo} onChange={set('repo')} /></Field>}
          <Field label="其他要求" optional><textarea rows={2} value={f.notes} onChange={set('notes')} /></Field>
        </div>
      </Panel>

      <Panel title="画面风格" icon={<Palette />} sub={`当前：${p.style_name}`}>
        <StylePicker styles={styles} value={f.style} onChange={(s) => setF({ ...f, style: s })} maxHeight={520} />
      </Panel>

      <Panel title="背景音乐" icon={<Music />} sub="整片循环一首，开头淡入、结尾淡出，讲话时自动压低。请用你有版权的音乐。">
        {p.bgm ? (
          <div className="col" style={{ gap: 16 }}>
            <div className="row"><audio controls src={fileUrl(p.id, `assets/${p.bgm.file}`)} /><span className="small soft">{p.bgm.name}</span></div>
            <Field label={<>音量 <span className="mono muted">{vol} dB</span></>} className="" hint="松开滑块后保存">
              <input type="range" min={-40} max={0} step={1} value={vol} style={{ maxWidth: 360 }} onChange={(e) => setVol(+e.target.value)}
                onMouseUp={() => api.patch(`${P(p.id)}/bgm`, { vol }).then(reload).catch(toast.err)}
                onTouchEnd={() => api.patch(`${P(p.id)}/bgm`, { vol }).then(reload).catch(toast.err)} />
            </Field>
            <div className="row">
              <button onClick={() => bgmRef.current?.click()}><Replace />换一首</button>
              <button className="ghost danger" onClick={() => api.del(`${P(p.id)}/bgm`).then(reload).catch(toast.err)}><Trash2 />去掉音乐</button>
            </div>
          </div>
        ) : (
          <div className="drop" onClick={() => bgmRef.current?.click()}><Upload /><b className="small">上传音乐</b><small>mp3 / m4a / wav</small></div>
        )}
        <input ref={bgmRef} type="file" hidden accept="audio/*" onChange={(e) => e.target.files?.[0] && uploadBgm(e.target.files[0])} />
      </Panel>

      <Panel title="导出与删除" icon={<TriangleAlert />} className="danger-zone"
        sub={<>项目 ID <span className="mono">{p.id}</span>{p.imported && ` · 来自样片 ${p.imported}`}</>}>
        <div className="row">
          <a className="btn" href={`${P(p.id)}/export`}><Download />导出项目 zip</a>
          <button className="danger" disabled={busy} onClick={async () => {
            if (!confirm(`删除「${p.title}」？所有分镜、配音、画面和成片都会删除，不能恢复。`)) return;
            try { await api.del(P(p.id)); nav('/'); } catch (e) { toast.err(e); }
          }}><Trash2 />删除项目</button>
          <span className="small muted">删除后不能恢复。</span>
        </div>
      </Panel>
    </div>
  );
}
