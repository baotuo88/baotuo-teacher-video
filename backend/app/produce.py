"""Stages 3 and 5: narration, render; publishing notes; the one-click run through every stage."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from . import draw, engine, film, llm, plan, prompts, settings, store, styles, thumbs, voice
from .jobs import Job, Stop, manager
from .llm import Msg


async def voice_job(job: Job) -> str:
    d = store.pdir(job.pid)
    p = store.get(job.pid)
    pages = await film.read_pages(d)
    if not pages:
        raise RuntimeError("还没有口播：先完成「口播」一步")
    cfg = film.tts_cfg(p)
    if cfg["provider"] == "none":
        (d / "voice.js").unlink(missing_ok=True)
        store.update(job.pid, {"voice_sig": "", "voice_stats": None})
        await film.apply_meta(d, job.pid)
        await engine.script_tool(d)
        return "这部片不配音（按口播估算时间）"
    n = sum(len(pg.get("cues") or []) for pg in pages)
    who = cfg["voice"] if cfg["provider"] == "edge" else f"{cfg['openai_model']} / {cfg['openai_voice']}"
    job.log(f"配音 {n} 句 · {cfg['provider']} · {who} · 语速 {cfg.get('speed')}")
    stats = await voice.voice_film(d, job.pid, p, settings.load()["tts"], job.log, job.set_progress)
    store.update(job.pid, {"voice_sig": voice.signature(pages), "voice_speaker": stats["speaker"], "voice_stats": stats})
    await film.apply_meta(d, job.pid)
    await engine.script_tool(d)       # 口播脚本.md and 字幕.srt on the real timeline
    thumbs.kick_film(d, job.pid)
    tl = await engine.timeline(d)
    return f"新配 {stats['made']} 句，复用 {stats['reused']} 句，自录 {stats['user']} 句 · 全片 {tl['duration']:.0f} 秒"


async def ensure_voice(job: Job) -> None:
    d = store.pdir(job.pid)
    p = store.get(job.pid)
    st = film.voice_status(d, p, await film.read_pages(d))
    if st in ("none", "stale"):
        job.log("口播改过或还没配音：先配音")
        job.log(await voice_job(job))


_SEG = re.compile(r"seg-[\w.-]+\.mp4$")


async def render_job(job: Job, fps: int | None = None, workers: int | None = None, subs: bool = True,
                     draft: bool = False) -> str:
    d = store.pdir(job.pid)
    p = store.get(job.pid)
    cfg = settings.load()["render"]
    fps = int(fps or (24 if draft else cfg["fps"]))
    workers = int(workers or cfg["workers"])
    pages = await film.read_pages(d)
    if not pages:
        raise RuntimeError("还没有口播")
    await ensure_voice(job)
    missing = [pg["id"] for pg in pages if film.page_code(d, pg["id"]) is None]
    if missing:
        job.log(f"这些页还没有画面，会显示成标题页：{' '.join(missing)}", "warn")
    await film.apply_meta(d, job.pid)
    webgl = styles.is_webgl(p["style"])
    args = ["--fps", str(fps), "--workers", str(workers)] + ([] if subs and not draft else ["--skip-subs"])
    code, out, err = await engine.node(d, "render.mjs", [*args, "--plan"], 120, webgl=webgl)
    plan_line = next((l for l in out.splitlines() if l.startswith("PLAN ")), "")
    segs = json.loads(plan_line[5:])["segments"] if plan_line else []
    total, cached = len(segs), sum(1 for s in segs if s.get("cached"))
    names = {s["file"] for s in segs}
    job.log(f"渲染 {fps}fps · {workers} 路并行 · {total} 段（缓存 {cached} 段）" + ("" if subs and not draft else " · 不烧字幕"))
    job.set_progress(done=cached, total=total, phase="video")
    chunks = d / "out" / "chunks"

    async def poll() -> None:
        while True:
            await asyncio.sleep(2)
            n = sum(1 for f in chunks.glob("seg-*.mp4") if f.name in names) if chunks.exists() else 0
            job.set_progress(done=n, total=total)

    def line(s: str) -> None:
        s = s.strip()
        # per-segment frame counters are the progress bar's job, not the log's
        if not s or s.startswith("frame") or "%" in s[:6] or re.match(r"^\[seg-[\w.-]+\]", s):
            return
        if s.startswith("video:"):
            job.set_progress(phase="audio")
        elif s.startswith("audio:"):
            job.set_progress(phase="subs")
        job.log(s)

    poller = asyncio.create_task(poll())
    t0 = time.time()
    try:
        async with manager.render:
            code, out, err = await engine.node(d, "render.mjs", args, 6 * 3600, webgl=webgl, on_line=line)
    finally:
        poller.cancel()
    if code:
        raise RuntimeError(f"渲染失败：{(err or out)[-800:]}")
    films = [f for f in film.outputs(d) if f["name"].endswith(".mp4")]
    rec = {"at": time.time(), "fps": fps, "subs": subs and not draft, "seconds": round(time.time() - t0),
           "files": [f["name"] for f in films[:2]]}
    store.update(job.pid, lambda x: x.__setitem__("renders", ([rec] + (x.get("renders") or []))[:10]))
    if store.get(job.pid).get("publish"):
        await engine.node(d, "publish.mjs", [], 60)
    return f"成片完成，用时 {rec['seconds']} 秒"


async def publish_job(job: Job) -> str:
    d = store.pdir(job.pid)
    p = store.get(job.pid)
    data = await engine.read_script(d)
    sb = film.read_storyboard(d) or {}
    sections = list(dict.fromkeys(pg.get("section", "") for pg in data["PAGES"] if pg.get("section")))
    narration = "\n".join(engine.cue_text(c) for pg in data["PAGES"] for c in pg.get("cues", []))
    r = await llm.chat("You write publishing notes for explainer videos on Chinese and global video platforms.",
                       [Msg("user", prompts.publish_prompt(data["META"].get("title") or p["title"], sb.get("summary", ""),
                                                           sections, narration, p.get("lang", "zh")))],
                       review=True, max_tokens=3000, pid=job.pid, log=job.log)
    v = llm.json_block(r.text)
    pub = {"titles": {k: str(v.get("titles", {}).get(k, ""))[:100] for k in ("bilibili", "youtube", "douyin", "shipinhao", "xiaohongshu")},
           "description": str(v.get("description", ""))[:2000], "tags": [str(x)[:30] for x in (v.get("tags") or [])][:15]}
    store.update(job.pid, {"publish": pub})
    await film.apply_meta(d, job.pid)
    code, out, err = await engine.node(d, "publish.mjs", [], 60)
    if code:
        raise RuntimeError(f"发布信息生成失败：{(err or out)[-400:]}")
    return "发布文案写好了（out/发布信息.md）"


async def auto_job(job: Job, skip_approval: bool = False, draft: bool = False) -> str:
    """Every stage that is not done yet, in order."""
    d = store.pdir(job.pid)
    p = store.get(job.pid)
    if not film.read_storyboard(d):
        job.log("── ① 分镜")
        job.log(await plan.storyboard_job(job))
    await plan.ensure_approved(job, skip_approval)
    p = store.get(job.pid)
    if not p.get("script_written"):
        job.log("── ② 口播")
        job.log(await plan.script_job(job))
    if film.voiced(store.get(job.pid)):
        job.log("── ③ 配音")
        await ensure_voice(job)
    job.log("── ④ 画面")
    job.log(await draw.pages_job(job))
    job.log("── ⑤ 成片")
    o = await film.overview(d, store.get(job.pid))
    if o["film"] and not o["film_stale"] and not draft:
        job.log("成片已是最新（渲染之后没有改动），不用重渲；要重出请在「成片」页点「重新渲染」")
        return "都已完成，成片是最新的"
    return await render_job(job, draft=draft)
