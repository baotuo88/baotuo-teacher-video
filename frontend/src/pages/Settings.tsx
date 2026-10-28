import { useEffect, useState } from 'react';
import { Bot, Check, CircleAlert, CircleCheck, Cpu, Factory, Heart, Play, PlugZap, Server, Volume2 } from 'lucide-react';
import { api, type Settings } from '../api';
import { Field, PageHeader, Panel, Seg, Spinner, Switch, toast } from '../ui';
import { playSample, VoicePicker } from './steps/Voice';

// base URLs only: model names change too often to hard-code, type the one your account has
const PRESETS: { name: string; provider: 'anthropic' | 'openai'; base_url: string; model?: string; vision?: boolean }[] = [
  { name: 'Anthropic 官方', provider: 'anthropic', base_url: 'https://api.anthropic.com', vision: true },
  { name: 'OpenAI', provider: 'openai', base_url: 'https://api.openai.com/v1', vision: true },
  { name: 'DeepSeek', provider: 'openai', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', vision: false },
  { name: '阿里云百炼（通义）', provider: 'openai', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', vision: true },
  { name: 'Kimi（月之暗面）', provider: 'openai', base_url: 'https://api.moonshot.cn/v1', vision: false },
  { name: '智谱 GLM', provider: 'openai', base_url: 'https://open.bigmodel.cn/api/paas/v4', vision: true },
  { name: '硅基流动', provider: 'openai', base_url: 'https://api.siliconflow.cn/v1', vision: false },
  { name: 'OpenRouter', provider: 'openai', base_url: 'https://openrouter.ai/api/v1', vision: true },
];

interface System { engine: boolean; engine_ref: string; chrome: string; ffmpeg: string; docker: boolean; password: boolean }

const Yes = ({ children }: { children: React.ReactNode }) => <span className="ok-text"><CircleCheck />{children}</span>;
const No = ({ children, warn }: { children: React.ReactNode; warn?: boolean }) => <span className={warn ? 'warn-text' : 'err-text'}><CircleAlert />{children}</span>;

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [saved, setSaved] = useState('');
  const [sys, setSys] = useState<System | null>(null);
  const [testing, setTesting] = useState(false);
  const [tested, setTested] = useState<{ ok: boolean; msg: string } | null>(null);
  useEffect(() => {
    api.get<Settings>('/api/settings').then((x) => { setS(x); setSaved(JSON.stringify(x)); }).catch(toast.err);
    api.get<System>('/api/system').then(setSys).catch(() => {});
  }, []);
  if (!s) return <div className="page narrow"><div className="row muted"><Spinner />加载中…</div></div>;
  const dirty = JSON.stringify(s) !== saved;
  const up = <K extends keyof Settings>(k: K, v: Partial<Settings[K]>) => setS({ ...s, [k]: { ...(s[k] as object), ...v } });
  const save = async () => {
    try { const x = await api.put<Settings>('/api/settings', s); setS(x); setSaved(JSON.stringify(x)); toast.ok('设置已保存'); } catch (e) { toast.err(e); }
  };
  const test = async () => {
    setTesting(true);
    setTested(null);
    try {
      const r = await api.post<{ model: string; reply: string }>('/api/settings/test-llm', s.llm);
      setTested({ ok: true, msg: `连接成功（${r.model}）：${r.reply.slice(0, 80)}` });
    } catch (e) { setTested({ ok: false, msg: (e as Error).message }); } finally { setTesting(false); }
  };
  const L = s.llm;

  return (
    <div className="page narrow stack">
      <PageHeader title="设置" desc="对所有视频生效的默认值。每部片的风格、配音还可以在项目里单独改。" sticky={dirty}
        actions={<>
          {dirty && <span className="small warn-text">有未保存的修改</span>}
          <button className="primary" disabled={!dirty} onClick={save}><Check />保存</button>
        </>} />

      <Panel title="大模型" icon={<Bot />} sub="写分镜、口播、每页画面代码和看图审片都靠它。画面代码要求较高，推荐用强一些的模型。"
        foot={<>
          <button disabled={testing} onClick={test}>{testing ? <Spinner small /> : <PlugZap />}{testing ? '测试中…' : '测试连接'}</button>
          {tested && <span className={`small ${tested.ok ? 'ok-text' : 'err-text'} grow ellipsis`} title={tested.msg}>{tested.msg}</span>}
        </>}>
        <div className="col" style={{ gap: 16 }}>
          <Field label="快速填入" as="div" hint="只填接口格式和地址；模型名请按你的账号填写。">
            <div className="chips">
              {PRESETS.map((x) => (
                <button key={x.name} className={`chip small ${L.base_url === x.base_url ? 'on' : ''}`}
                  onClick={() => up('llm', { provider: x.provider, base_url: x.base_url, ...(x.model ? { model: x.model } : {}), vision: x.vision ?? L.vision })}>{x.name}</button>
              ))}
            </div>
          </Field>
          <Field label="接口格式" as="div">
            <Seg value={L.provider} onChange={(v) => up('llm', { provider: v })}
              options={[['anthropic', 'Anthropic Messages'], ['openai', 'OpenAI 兼容']]} />
          </Field>
          <div className="grid2">
            <Field label="接口地址"><input value={L.base_url} onChange={(e) => up('llm', { base_url: e.target.value })} /></Field>
            <Field label="API Key"><input type="password" autoComplete="off" value={L.api_key} placeholder="sk-…" onChange={(e) => up('llm', { api_key: e.target.value })} /></Field>
            <Field label="模型"><input value={L.model} onChange={(e) => up('llm', { model: e.target.value })} /></Field>
            <Field label="审片模型" optional hint="留空同上；可填一个便宜些的视觉模型。"><input value={L.review_model} onChange={(e) => up('llm', { review_model: e.target.value })} /></Field>
            {L.provider === 'anthropic' && (
              <Field label="鉴权方式">
                <select value={L.auth} onChange={(e) => up('llm', { auth: e.target.value })}>
                  <option value="x-api-key">x-api-key（官方）</option><option value="bearer">Authorization: Bearer（多数中转）</option>
                </select>
              </Field>
            )}
            <div className="grid2">
              <Field label="单次最长输出"><input type="number" value={L.max_tokens} onChange={(e) => up('llm', { max_tokens: +e.target.value })} /></Field>
              <Field label="超时（秒）"><input type="number" value={L.timeout} onChange={(e) => up('llm', { timeout: +e.target.value })} /></Field>
            </div>
          </div>
          <Switch checked={L.vision} onChange={(v) => up('llm', { vision: v })} hint="开启后会看每页截图审片，并把截图一起发给它修改；纯文本模型请关掉。">模型能看图</Switch>
        </div>
      </Panel>

      <Panel title="配音" icon={<Volume2 />} sub="默认值，每部片可以单独改"
        foot={<>{s.tts.provider !== 'none' && <button onClick={() => playSample(s.tts)}><Play />试听</button>}</>}>
        <div className="col" style={{ gap: 16 }}>
          <VoicePicker value={s.tts} onChange={(v) => up('tts', v)} />
          {s.tts.provider === 'openai' && (
            <div className="grid3">
              <Field label="接口地址"><input value={s.tts.openai_base_url} onChange={(e) => up('tts', { openai_base_url: e.target.value })} /></Field>
              <Field label="API Key"><input type="password" autoComplete="off" value={s.tts.openai_api_key} onChange={(e) => up('tts', { openai_api_key: e.target.value })} /></Field>
              <Field label="模型"><input value={s.tts.openai_model} onChange={(e) => up('tts', { openai_model: e.target.value })} /></Field>
            </div>
          )}
          <Field label="同时合成几句" hint="Edge 朗读免费、不用 Key（走 api.msedgeservices.com）。硅基流动 CosyVoice：模型填 FunAudioLLM/CosyVoice2-0.5B，音色填 FunAudioLLM/CosyVoice2-0.5B:anna。">
            <input type="number" min={1} max={8} value={s.tts.concurrency} style={{ maxWidth: 160 }} onChange={(e) => up('tts', { concurrency: +e.target.value })} />
          </Field>
        </div>
      </Panel>

      <Panel title="制作" icon={<Factory />} sub="并行数按机器配置调：每个检查或渲染进程是一个 Chrome。">
        <div className="col" style={{ gap: 16 }}>
          <div className="grid3">
            <Field label="同时画几页"><input type="number" min={1} max={10} value={s.pipeline.page_concurrency} onChange={(e) => up('pipeline', { page_concurrency: +e.target.value })} /></Field>
            <Field label="同时检查几页"><input type="number" min={1} max={8} value={s.pipeline.check_concurrency} onChange={(e) => up('pipeline', { check_concurrency: +e.target.value })} /></Field>
            <Field label="每页最多检查几轮"><input type="number" min={1} max={6} value={s.pipeline.page_rounds} onChange={(e) => up('pipeline', { page_rounds: +e.target.value })} /></Field>
            <Field label="默认帧率" as="div"><Seg value={s.render.fps} onChange={(v) => up('render', { fps: v })} options={[[24, '24'], [30, '30'], [60, '60']]} /></Field>
            <Field label="默认渲染并行数"><input type="number" min={1} max={16} value={s.render.workers} onChange={(e) => up('render', { workers: +e.target.value })} /></Field>
          </div>
          <Switch checked={s.pipeline.review} onChange={(v) => up('pipeline', { review: v })} hint="需要模型能看图；关掉更快更省，只靠机器检查。">逐页看图审片</Switch>
        </div>
      </Panel>

      <Panel title="创作偏好" icon={<Heart />} sub="每部片都会遵守的要求，比如语气、配色习惯、结尾方式。">
        <textarea rows={4} value={s.preferences} placeholder="例：口播像朋友聊天，不说「众所周知」；结尾不要总结金句；数字尽量落在物体上" onChange={(e) => setS({ ...s, preferences: e.target.value })} />
      </Panel>

      {sys && (
        <Panel title="运行环境" icon={<Server />}>
          <div className="kv">
            <span>渲染引擎</span><span>{sys.engine ? <Yes>已就位 {sys.engine_ref && <span className="mono muted">frametell@{sys.engine_ref}</span>}</Yes> : <No>没找到</No>}</span>
            <span>浏览器</span><span>{sys.chrome ? <span className="mono small">{sys.chrome}</span> : <No>没找到 Chrome / Chromium</No>}</span>
            <span>ffmpeg</span><span className="mono small">{sys.ffmpeg}</span>
            <span>访问密码</span><span>{sys.password ? <Yes>已开启</Yes> : <No warn>未设置（服务暴露在公网时请设置 APP_PASSWORD）</No>}</span>
            <span>运行方式</span><span className="row gap-s"><Cpu size={14} />{sys.docker ? 'Docker 容器' : '本机'}</span>
          </div>
        </Panel>
      )}
    </div>
  );
}
