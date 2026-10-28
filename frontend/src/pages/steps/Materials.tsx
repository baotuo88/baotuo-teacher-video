import { useRef, useState } from 'react';
import { ArrowRight, FileText, Globe, ImagePlus, Image as ImageIcon, Pencil, Plus, Trash2, Upload } from 'lucide-react';
import { api, fileUrl, P } from '../../api';
import { Modal, PageHeader, Panel, toast } from '../../ui';
import { useProject } from '../Workspace';

/** A click-or-drop area for files. */
function Drop({ accept, onFiles, disabled, children }: { accept: string; onFiles: (f: FileList) => void; disabled?: boolean; children: React.ReactNode }) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div className={`drop ${over ? 'over' : ''}`} onClick={() => !disabled && ref.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled && e.dataTransfer.files.length) onFiles(e.dataTransfer.files); }}>
      <input ref={ref} type="file" multiple hidden accept={accept} onChange={(e) => { if (e.target.files?.length) onFiles(e.target.files); e.target.value = ''; }} />
      {children}
    </div>
  );
}

export default function Materials() {
  const { p, reload, run, busy } = useProject();
  const [text, setText] = useState('');
  const [title, setTitle] = useState('');
  const [url, setUrl] = useState('');
  const [working, setWorking] = useState(false);
  const [view, setView] = useState<{ name: string; text: string } | null>(null);

  const go = async (fn: () => Promise<unknown>, ok: string) => {
    setWorking(true);
    try { await fn(); toast.ok(ok); await reload(); } catch (e) { toast.err(e); } finally { setWorking(false); }
  };
  const upload = (files: FileList | null, kind: 'file' | 'asset') => {
    if (!files?.length) return;
    go(async () => {
      for (const f of Array.from(files)) {
        const fd = new FormData();
        fd.append('file', f);
        await api.post(kind === 'asset' ? `${P(p.id)}/assets` : `${P(p.id)}/materials/file`, fd);
      }
    }, '已添加');
  };
  const images = p.assets_files.filter((n) => !n.startsWith('bgm'));

  return (
    <div className="stack">
      <PageHeader eyebrow="第 1 步" title="素材"
        desc="导演写分镜时会读这里的全部文字，画面上出现的数字必须能在素材或口播里找到。没有素材也可以，导演按常识写。"
        actions={!p.storyboard && <button className="primary" disabled={busy} onClick={() => run('storyboard/generate')}>生成分镜<ArrowRight /></button>} />

      <Panel title="文字素材" icon={<FileText />} sub={p.materials.length ? `${p.materials.length} 份 · 共 ${p.materials.reduce((n, m) => n + m.chars, 0).toLocaleString()} 字` : '文章、讲稿、网页、PDF'} body="flush">
        {p.materials.length > 0 && (
          <div>
            {p.materials.map((m) => (
              <div key={m.name} className="mrow">
                <span className="fi"><FileText /></span>
                <div className="grow">
                  <div className="row gap-s"><b className="small">{m.name}</b><span className="tiny muted">{m.chars.toLocaleString()} 字</span></div>
                  <div className="small muted ellipsis">{m.preview}</div>
                </div>
                <button className="ghost small" onClick={() => api.get<{ name: string; text: string }>(`${P(p.id)}/materials/${encodeURIComponent(m.name)}`).then(setView).catch(toast.err)}><Pencil />查看/编辑</button>
                <button className="ghost icon small danger" aria-label="删除" onClick={() => confirm(`删除 ${m.name}？`) && go(() => api.del(`${P(p.id)}/materials/${encodeURIComponent(m.name)}`), '已删除')}><Trash2 /></button>
              </div>
            ))}
          </div>
        )}
        <div className="panel-body" style={p.materials.length ? { borderTop: '1px solid var(--line)' } : undefined}>
          <div className="grid2">
            <div className="col">
              <input placeholder="标题（可选）" value={title} onChange={(e) => setTitle(e.target.value)} />
              <textarea rows={6} placeholder="粘贴文章、讲稿、笔记…" value={text} onChange={(e) => setText(e.target.value)} />
              <button disabled={working || !text.trim()} onClick={() => go(() => api.post(`${P(p.id)}/materials/text`, { title, text }).then(() => { setText(''); setTitle(''); }), '已添加')}><Plus />添加这段文字</button>
            </div>
            <div className="col">
              <div className="row nowrap">
                <input placeholder="网页 / PDF / GitHub 仓库地址" value={url} onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && url.trim() && go(() => api.post(`${P(p.id)}/materials/url`, { url }).then(() => setUrl('')), '已读取网页')} />
                <button disabled={working || !url.trim()} onClick={() => go(() => api.post(`${P(p.id)}/materials/url`, { url }).then(() => setUrl('')), '已读取网页')}><Globe />{working ? '读取中…' : '读取'}</button>
              </div>
              <div className="or">或</div>
              <Drop accept=".txt,.md,.markdown,.pdf,.html,.htm,.csv,.json" disabled={working} onFiles={(f) => upload(f, 'file')}>
                <Upload /><b className="small">上传文件</b><small>点击或拖进来 · txt / md / pdf / html</small>
              </Drop>
            </div>
          </div>
        </div>
      </Panel>

      <Panel title="图片素材" icon={<ImageIcon />} sub="截图、产品图、示意图。写一句说明，导演会把它安排进合适的页面（原样放上去，不会重画）。" body="flush">
        {images.map((n) => (
          <div key={n} className="mrow">
            <img className="asset-thumb" src={fileUrl(p.id, `assets/${n}`)} alt="" />
            <div className="grow col gap-s">
              <span className="tiny mono muted">assets/{n}</span>
              <input defaultValue={p.assets[n] || ''} placeholder="这张图是什么、想用在哪（例：首页截图，用在介绍界面那页）"
                onBlur={(e) => e.target.value !== (p.assets[n] || '') && api.patch(`${P(p.id)}/assets/${encodeURIComponent(n)}`, { desc: e.target.value }).then(() => { toast.ok('说明已保存'); reload(); }).catch(toast.err)} />
            </div>
            <button className="ghost icon small danger" aria-label="删除" onClick={() => confirm(`删除 ${n}？`) && go(() => api.del(`${P(p.id)}/assets/${encodeURIComponent(n)}`), '已删除')}><Trash2 /></button>
          </div>
        ))}
        <div className="panel-body" style={images.length ? { borderTop: '1px solid var(--line)' } : undefined}>
          <Drop accept="image/png,image/jpeg,image/webp,image/gif" disabled={working} onFiles={(f) => upload(f, 'asset')}>
            <ImagePlus /><b className="small">上传图片</b><small>点击或拖进来 · png / jpg / webp / gif</small>
          </Drop>
        </div>
      </Panel>

      {view && (
        <Modal title={view.name} icon={<FileText />} onClose={() => setView(null)} footer={<>
          <span className="small muted grow">{view.text.length.toLocaleString()} 字</span>
          <button onClick={() => setView(null)}>关闭</button>
          <button className="primary" onClick={() => api.put(`${P(p.id)}/materials/${encodeURIComponent(view.name)}`, { text: view.text }).then(() => { toast.ok('已保存'); setView(null); reload(); }).catch(toast.err)}>保存</button>
        </>}>
          <textarea style={{ minHeight: '60vh' }} value={view.text} onChange={(e) => setView({ ...view, text: e.target.value })} />
        </Modal>
      )}
    </div>
  );
}
