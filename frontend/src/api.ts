// Thin fetch helpers and the shapes the backend returns.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin' };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { 'content-type': 'application/json' };
  }
  const r = await fetch(url, init);
  if (r.status === 401 && !url.startsWith('/api/auth')) {
    window.dispatchEvent(new Event('btv-login'));
  }
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      msg = await r.text().catch(() => msg);
    }
    throw new ApiError(r.status, msg);
  }
  const ct = r.headers.get('content-type') || '';
  return (ct.includes('json') ? r.json() : r.blob()) as Promise<T>;
}

export const api = {
  get: <T,>(u: string) => call<T>('GET', u),
  post: <T,>(u: string, b?: unknown) => call<T>('POST', u, b ?? {}),
  put: <T,>(u: string, b?: unknown) => call<T>('PUT', u, b),
  patch: <T,>(u: string, b?: unknown) => call<T>('PATCH', u, b),
  del: <T,>(u: string) => call<T>('DELETE', u),
};

export const P = (pid: string) => `/api/projects/${pid}`;
/** A project file; `rel` may carry its own query (a cache-busting `?v=`), which stays a query. */
export const fileUrl = (pid: string, rel: string, download = false) => {
  const [path, query] = rel.split('?');
  const qs = [query, download ? 'download=1' : ''].filter(Boolean).join('&');
  return `/files/${pid}/${path.split('/').map(encodeURIComponent).join('/')}${qs ? `?${qs}` : ''}`;
};
/** A sample film's still (the server makes it on first ask; 404 until then). */
export const exampleThumb = (eid: string) => `/api/examples/${encodeURIComponent(eid)}/thumb`;
/** A drawn page's clean still, or '' before it has one. */
export const pageThumb = (p: { id: string; thumbs?: Record<string, number> }, page: string) =>
  p.thumbs?.[page] ? fileUrl(p.id, `out/thumbs/${page}.jpg?v=${p.thumbs[page]}`) : '';
export const coverThumb = (p: { id: string; cover?: string; thumbs?: Record<string, number> }) => {
  const t = p.thumbs || {};
  const id = p.cover && t[p.cover] ? p.cover : Object.keys(t).sort()[0];
  return id ? pageThumb(p, id) : '';
};

export interface JobSummary {
  id: string; kind: string; label: string; status: 'running' | 'done' | 'failed' | 'cancelled';
  started: number; ended: number | null; error: string; result: string;
  progress: { done?: number; total?: number; phase?: string; page?: string };
}
export interface JobLog extends JobSummary { lines: { t: number; level: string; msg: string }[]; next: number }

export interface Style { id: string; name: string; tagline: string; fit: string[]; swatch: string[]; webgl: boolean; example: boolean; classic: boolean }
export interface Example { id: string; title: string; style: string; style_name?: string; pages: number; source: string }

export interface Card {
  id: string; title: string; style: string; style_name: string; duration: number; updated: number; created: number;
  thumb: string; pages: number; film: string; storyboard_status: string; job: JobSummary | null;
}

export type Cue = string | { t: string; hold?: number };
export interface ScriptPage { id: string; section?: string; title?: string; cues: Cue[]; sfx?: unknown[] }
export interface Beat { at: string; object: string; action: string; camera?: string; text?: string }
export interface SbPage { id: string; section: string; say: string; core?: boolean; beats: Beat[] }
export interface Storyboard { title: string; summary: string; durationSec: number; style: string; cast?: string; pages: SbPage[] }
export interface Issue { level: string; page?: string; beat?: number; msg: string; zh?: string; kind?: string; local?: number }
export interface PageState {
  status?: string; rounds?: number; issues?: Issue[]; problems?: { at: number; what: string; fix: string }[];
  sheet?: string; note?: string; say?: string; crash?: string; updated?: number; times?: number[];
}
export interface Output { name: string; size: number; mtime: number }

export interface Project {
  id: string; title: string; topic: string; audience: string; notes: string; kind: string; repo: string;
  style: string; style_name: string; lang: string; duration: number; webgl: boolean;
  storyboard_status: string; storyboard_issues: Issue[]; storyboard_report: string;
  script_report: string; script_issues: string[]; script_written: boolean;
  voice: Record<string, unknown>; pages: Record<string, PageState>;
  film_check: { at: number; issues: Issue[]; bad: string[]; sheet: string; duration: number } | null;
  assets: Record<string, string>; assets_files: string[]; bgm: { file: string; vol: number; name?: string } | null;
  publish: { titles: Record<string, string>; description: string; tags: string[] } | null;
  cover: string; thumbs: Record<string, number>; renders:{ at: number; fps: number; subs: boolean; seconds: number; files: string[] }[];
  usage: { input: number; output: number; calls: number }; jobs: JobSummary[]; imported: string;
  overview: {
    storyboard: boolean; storyboard_status: string; script: boolean; script_error: string; pages_total: number;
    pages_drawn: number; voice: 'off' | 'none' | 'ok' | 'stale'; film: boolean; film_stale: boolean; title: string;
  };
  storyboard: Storyboard | null;
  script: { META: Record<string, unknown>; PAGES: ScriptPage[] };
  materials: { name: string; chars: number; preview: string }[];
  outputs: Output[];
  job: JobSummary | null;
  tts: Tts;
  preview: string;
}

export interface Tts {
  provider: 'edge' | 'openai' | 'none'; voice: string; speed: number;
  openai_base_url: string; openai_api_key: string; openai_model: string; openai_voice: string; concurrency: number;
}
export interface Settings {
  llm: { provider: 'anthropic' | 'openai'; base_url: string; api_key: string; auth: string; model: string;
    review_model: string; vision: boolean; max_tokens: number; temperature: number | null; timeout: number };
  tts: Tts;
  render: { fps: number; workers: number };
  pipeline: { page_concurrency: number; check_concurrency: number; page_rounds: number; review: boolean };
  preferences: string;
}

export interface Timeline { voiced: boolean; duration: number; pages: { id: string; start: number; end: number; speechEnd: number }[] }

export const cueText =(c: Cue) => (typeof c === 'string' ? c : c.t);
export const fmtTime = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
export const fmtDate = (t: number) => new Date(t * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
export const fmtAgo = (t: number) => {
  const s = Date.now() / 1000 - t;
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} 天前`;
  return fmtDate(t);
};
export const fmtSize =(b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`);
