import { useEffect, useRef, useState } from 'react';
import { ArrowRight, AudioLines, Check, Mic, MicOff, Pause, Play, RefreshCw, Server, Square, Upload, Volume2, X } from 'lucide-react';
import { api, fileUrl, P, type Tts } from '../../api';
import { Empty, Field, PageHeader, Panel, toast } from '../../ui';
import { useProject } from '../Workspace';

interface Row { page: string; i: number; text: string; audio: string; d: number | null; own: boolean }
interface VoiceState { status: 'off' | 'none' | 'ok' | 'stale'; cues: Row[]; stats: Record<string, number> | null; tts: Tts }

const PROVIDERS: [Tts['provider'], string, string, typeof Mic][] = [
  ['edge', 'Edge 朗读', '免费、不用 Key，几十种中英文音色', Volume2],
  ['openai', 'OpenAI 兼容接口', 'OpenAI、硅基流动 CosyVoice 等', Server],
  ['none', '不配音', '按字数估算时间，之后可自己录', MicOff],
];

export function VoicePicker({ value, onChange }: { value: Partial<Tts>; onChange: (v: Partial<Tts>) => void }) {
  const [edge, setEdge] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => { api.get<{ edge: { id: string; name: string }[] }>('/api/voices').then((x) => setEdge(x.edge)).catch(() => {}); }, []);
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="providers">
        {PROVIDERS.map(([k, name, sub, Icon]) => (
          <button type="button" key={k} className={`provider ${value.provider === k ? 'on' : ''}`} onClick={() => onChange({ ...value, provider: k })}>
            <span className="pi"><Icon />{name}</span><small>{sub}</small>
          </button>
        ))}
      </div>
      {value.provider !== 'none' && (
        <div className="grid2">
          {value.provider === 'edge' ? (
            <Field label="音色">
              <select value={value.voice} onChange={(e) => onChange({ ...value, voice: e.target.value })}>
                {edge.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                {value.voice && !edge.some((v) => v.id === value.voice) && <option value={value.voice}>{value.voice}</option>}
              </select>
            </Field>
          ) : (
            <Field label="音色（voice）"><input value={value.openai_voice || ''} onChange={(e) => onChange({ ...value, openai_voice: e.target.value })} /></Field>
          )}
          <Field label={<>语速 <span className="mono muted">{Number(value.speed || 1).toFixed(2)}×</span></>}>
            <input type="range" min={0.8} max={1.4} step={0.05} value={value.speed || 1} onChange={(e) => onChange({ ...value, speed: +e.target.value })} />
          </Field>
        </div>
      )}
    </div>
  );
}

export async function playSample(cfg: Partial<Tts>, text?: string) {
  try {
    const blob = await api.post<Blob>('/api/settings/test-tts', { ...cfg, text });
    const a = new Audio(URL.createObjectURL(blob));
    await a.play();
  } catch (e) { toast.err(e); }
}
export default function VoiceStep() {
  const { p, reload, run, busy } = useProject();
  const [v, setV] = useState<VoiceState | null>(null);
  const [cfg, setCfg] = useState<Partial<Tts>>(p.tts);
  const [rec, setRec] = useState('');
  const [playing, setPlaying] = useState('');
  const recorder = useRef<MediaRecorder | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const load = () => api.get<VoiceState>(`${P(p.id)}/voice`).then(setV).catch(toast.err);
  useEffect(() => { load(); }, [p.overview.voice, p.jobs[0]?.id]);
  useEffect(() => { setCfg(p.tts); }, [p.tts.provider, p.tts.voice, p.tts.speed]);
  useEffect(() => () => audio.current?.pause(), []);

  const changed = cfg.provider !== p.tts.provider || cfg.voice !== p.tts.voice || cfg.speed !== p.tts.speed || cfg.openai_voice !== p.tts.openai_voice;
  const saveCfg = async () => {
    try {
      await api.patch(P(p.id), { voice: { provider: cfg.provider, voice: cfg.voice, speed: cfg.speed, openai_voice: cfg.openai_voice } });
      toast.ok('这部片的配音设置已保存');
      await reload();
    } catch (e) { toast.err(e); }
  };
  const play = (key: string, src: string) => {
    audio.current?.pause();
    if (playing === key) { setPlaying(''); return; }
    const a = new Audio(fileUrl(p.id, src) + `?v=${Date.now()}`);
    a.onended = () => setPlaying('');
    audio.current = a;
    setPlaying(key);
    a.play().catch((e) => { setPlaying(''); toast.err(e); });
  };
  const upload = async (r: Row, blob: Blob, name: string) => {
    const fd = new FormData();
    fd.append('file', blob, name);
    try {
      await api.post(`${P(p.id)}/voice/cue?page=${r.page}&i=${r.i}`, fd);
      toast.ok('已用你的录音替换这一句，点「配音」更新时间轴');
      load();
    } catch (e) { toast.err(e); }
  };
  const record = async (r: Row) => {
    const key = `${r.page}-${r.i}`;
    if (rec === key && recorder.current) { recorder.current.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRec('');
        upload(r, new Blob(chunks, { type: mr.mimeType }), 'take.webm');
      };
      recorder.current = mr;
      mr.start();
      setRec(key);
    } catch (e) {
      toast.err(`打不开麦克风：${(e as Error).message}（浏览器只允许 https 或 localhost 录音）`);
    }
  };

  if (!p.overview.script) {
    return <div className="stack"><PageHeader eyebrow="第 4 步" title="配音" /><Empty icon={<Mic />} title="先完成口播">口播写好后，这里逐句合成配音，也可以自己录。</Empty></div>;
  }
  const st = v?.status || p.overview.voice;
  const tag = {
    ok: <span className="tag ok lg"><Check />已配音</span>, stale: <span className="tag warn lg dot">口播改过，需重配</span>,
    none: <span className="tag lg">还没配音</span>, off: <span className="tag lg">不配音</span>,
  }[st];
  const groups: { page: string; rows: Row[] }[] = [];
  for (const r of v?.cues || []) {
    if (groups[groups.length - 1]?.page !== r.page) groups.push({ page: r.page, rows: [] });
    groups[groups.length - 1].rows.push(r);
  }
  const title = (id: string) => { const pg = p.script.PAGES.find((x) => x.id === id); return pg?.title || pg?.section || ''; };

  return (
    <div className="stack">
      <PageHeader eyebrow="第 4 步" title="配音" badge={tag}
        desc="逐句合成，按「方式 + 音色 + 语速 + 文字」缓存：改一句只重配那一句。配音后画面时间轴跟着真实语音走。"
        actions={<>
          {st === 'ok' && <button disabled={busy} onClick={() => run('pages/generate')}>画画面<ArrowRight /></button>}
          <button className="primary" disabled={busy} onClick={() => run('voice/generate')}>
            {st === 'ok' ? <><RefreshCw />重新配音</> : st === 'off' ? '应用（不配音）' : <><AudioLines />开始配音</>}
          </button>
        </>} />

      {v?.stats && (
        <div className="stats">
          <div className="stat"><div className="k">新配</div><div className="v">{v.stats.made}<small>句</small></div></div>
          <div className="stat"><div className="k">复用缓存</div><div className="v">{v.stats.reused}<small>句</small></div></div>
          <div className="stat"><div className="k">自录</div><div className="v">{v.stats.user}<small>句</small></div></div>
          <div className="stat"><div className="k">语音总长</div><div className="v">{v.stats.seconds}<small>秒</small></div></div>
        </div>
      )}

      <Panel title="这部片的配音" icon={<Volume2 />} sub="默认值在「设置」里改；接口地址和 Key 也在那里。"
        foot={<>
          {cfg.provider !== 'none' && <button onClick={() => playSample(cfg, v?.cues[0]?.text)}><Play />试听第一句</button>}
          <span className="grow" />
          {changed && <span className="small warn-text">设置改了，还没保存</span>}
          <button className={changed ? 'primary' : ''} disabled={!changed} onClick={saveCfg}><Check />保存设置</button>
        </>}>
        <VoicePicker value={cfg} onChange={setCfg} />
      </Panel>

      <Panel title="逐句" icon={<AudioLines />} sub={v ? `${v.cues.length} 句 · 点 ● 用麦克风自己录，或上传一段音频替换` : '加载中…'} body="flush">
        {groups.map((g) => (
          <div key={g.page} className="vgroup">
            <div className="vgroup-head"><span className="pid">{g.page}</span>{title(g.page)}</div>
            {g.rows.map((r) => {
              const key = `${r.page}-${r.i}`;
              return (
                <div key={key} className="vrow">
                  <button className={`playbtn ${playing === key ? 'on' : ''}`} disabled={!r.audio} aria-label="播放" onClick={() => play(key, r.audio)}>
                    {playing === key ? <Pause fill="currentColor" /> : <Play fill="currentColor" />}
                  </button>
                  <div className="txt">{r.text}</div>
                  {r.own && <span className="tag ok"><Mic />自录</span>}
                  <span className="dur">{r.d ? `${r.d.toFixed(1)}s` : '—'}</span>
                  <div className="acts">
                    <button className={`small rec ${rec === key ? 'on' : 'ghost'}`} onClick={() => record(r)} title={rec === key ? '停止录音' : '自己录这一句'}>
                      {rec === key ? <><Square fill="currentColor" />停止</> : <Mic />}
                    </button>
                    <label className="btn ghost small" title="上传音频替换这一句">
                      <Upload /><input type="file" hidden accept="audio/*" onChange={(e) => e.target.files?.[0] && upload(r, e.target.files[0], e.target.files[0].name)} />
                    </label>
                    {r.own && <button className="ghost icon small danger" title="删掉自录，改回合成" onClick={() => api.del(`${P(p.id)}/voice/cue?page=${r.page}&i=${r.i}`).then(load).catch(toast.err)}><X /></button>}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </Panel>
    </div>
  );
}
