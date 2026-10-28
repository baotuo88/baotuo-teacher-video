"""The stages of a film (each runs as a background job), the manual edits between them, and jobs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, UploadFile

from . import draw, engine, film, plan, produce, store, thumbs, voice
from .jobs import manager

router = APIRouter(prefix="/api/projects/{pid}")


def _job(pid: str, kind: str, fn, label: str = "") -> dict:
    store.pdir(pid)
    return manager.start(pid, kind, fn, label).summary()


# ── storyboard ──

@router.post("/storyboard/generate")
async def gen_storyboard(pid: str) -> dict:
    return _job(pid, "storyboard", plan.storyboard_job)


@router.post("/storyboard/revise")
async def revise_storyboard(pid: str, payload: dict = Body(...)) -> dict:
    fb = str(payload.get("feedback") or "").strip()
    if not fb:
        raise HTTPException(400, "写一下要怎么改")
    return _job(pid, "storyboard_revise", lambda j: plan.storyboard_revise_job(j, fb))


@router.put("/storyboard")
async def put_storyboard(pid: str, payload: dict = Body(...)) -> dict:
    d = store.pdir(pid)
    p = store.get(pid)
    sb = payload.get("storyboard")
    if not isinstance(sb, dict):
        raise HTTPException(400, "分镜应该是一个 JSON 对象")
    sb = plan.normalize_storyboard(sb, p)
    film.write_storyboard(d, sb)
    issues = plan.own_storyboard_issues(sb, p) + await engine.storyboard_lint(d)
    store.update(pid, {"storyboard_status": "draft", "storyboard_issues": issues})
    return {"storyboard": sb, "issues": issues}


@router.post("/storyboard/approve")
async def approve(pid: str) -> dict:
    d = store.pdir(pid)
    if not film.read_storyboard(d):
        raise HTTPException(400, "还没有分镜")
    store.update(pid, {"storyboard_status": "approved"})
    return {"ok": True}


# ── narration ──

@router.post("/script/generate")
async def gen_script(pid: str, payload: dict = Body(default={})) -> dict:
    fb = str((payload or {}).get("feedback") or "")
    return _job(pid, "script", lambda j: plan.script_job(j, fb))


@router.put("/script")
async def put_script(pid: str, payload: dict = Body(...)) -> dict:
    """{ pages: [...] } (the cue table) or { raw: "script.js source" }."""
    d = store.pdir(pid)
    if manager.current(pid):
        raise HTTPException(409, "有任务在跑，等它结束再改口播")
    if "raw" in payload:
        f = d / "script.js"
        backup = f.read_text("utf-8") if f.exists() else ""
        f.write_text(str(payload["raw"]), "utf-8")
        try:
            data = await engine.read_script(d)
        except engine.ToolError as e:
            f.write_text(backup, "utf-8")
            raise HTTPException(400, str(e))
        pages = data["PAGES"]
    else:
        pages = payload.get("pages")
        if not isinstance(pages, list):
            raise HTTPException(400, "pages 应该是数组")
        for pg in pages:
            if not isinstance(pg, dict) or not str(pg.get("id", "")).strip():
                raise HTTPException(400, "每一页都要有 id")
            pg["cues"] = [c for c in (pg.get("cues") or []) if engine.cue_text(c).strip()]
    await film.apply_meta(d, pid, pages, title=payload.get("title"))
    store.update(pid, {"script_written": True})
    tl = await engine.timeline(d)
    try:
        await engine.script_tool(d)
    except engine.ToolError:
        pass
    return {"duration": tl.get("duration"), "voice": film.voice_status(d, store.get(pid), pages)}


@router.get("/timeline")
async def timeline(pid: str) -> dict:
    return await engine.timeline(store.pdir(pid))


# ── narration audio ──

@router.post("/voice/generate")
async def gen_voice(pid: str) -> dict:
    return _job(pid, "voice", produce.voice_job)


@router.get("/voice")
async def voice_state(pid: str) -> dict:
    d = store.pdir(pid)
    p = store.get(pid)
    pages = await film.read_pages(d)
    vjs: dict = {}
    f = d / "voice.js"
    if f.exists():
        try:
            vjs = json.loads(f.read_text("utf-8").split("SCRIPT.VOICE = ", 1)[1].rstrip().rstrip(";"))
        except (IndexError, json.JSONDecodeError):
            vjs = {}
    vp = vjs.get("pages") or []
    rows = []
    for pi, pg in enumerate(pages):
        for ci, c in enumerate(pg.get("cues") or []):
            t = engine.cue_text(c)
            take = vp[pi][ci] if pi < len(vp) and ci < len(vp[pi]) else None
            rows.append({"page": pg["id"], "i": ci, "text": t,
                         "audio": take["f"] if take and take.get("t") == t else "",
                         "d": take["d"] if take and take.get("t") == t else None,
                         "own": voice.override_file(d, pg["id"], t).exists()})
    return {"status": film.voice_status(d, p, pages), "cues": rows, "stats": p.get("voice_stats"), "tts": film.tts_cfg(p) | {"openai_api_key": ""}}


@router.post("/voice/cue")
async def own_take(pid: str, page: str, i: int, file: UploadFile = File(...)) -> dict:
    """The user's own take for one cue (uploaded, or recorded in the browser)."""
    d = store.pdir(pid)
    pages = await film.read_pages(d)
    pg = next((x for x in pages if x["id"] == page), None)
    if not pg or i < 0 or i >= len(pg.get("cues") or []):
        raise HTTPException(404, "没有这一句")
    text = engine.cue_text(pg["cues"][i])
    tmp = d / ".studio" / "uploads" / f"take{Path(file.filename or 'a.webm').suffix or '.webm'}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(await file.read())
    out = voice.override_file(d, page, text)
    (d / "audio").mkdir(exist_ok=True)
    try:
        await voice.to_wav(tmp, out)
    except voice.VoiceError as e:
        raise HTTPException(400, str(e))
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "d": round(voice.wav_seconds(out), 2)}


@router.delete("/voice/cue")
async def drop_take(pid: str, page: str, i: int) -> dict:
    d = store.pdir(pid)
    pages = await film.read_pages(d)
    pg = next((x for x in pages if x["id"] == page), None)
    if not pg or i >= len(pg.get("cues") or []):
        raise HTTPException(404, "没有这一句")
    voice.override_file(d, page, engine.cue_text(pg["cues"][i])).unlink(missing_ok=True)
    return {"ok": True}


# ── pages ──

@router.post("/pages/generate")
async def gen_pages(pid: str, payload: dict = Body(default={})) -> dict:
    only = (payload or {}).get("only") or None
    redo = bool((payload or {}).get("redo"))
    return _job(pid, "pages", lambda j: draw.pages_job(j, only, redo))


@router.get("/pages/{page}/code")
async def page_code(pid: str, page: str) -> dict:
    d = store.pdir(pid)
    return {"code": film.page_code(d, page) or ""}


@router.put("/pages/{page}/code")
async def put_page_code(pid: str, page: str, payload: dict = Body(...)) -> dict:
    d = store.pdir(pid)
    if manager.current(pid):
        raise HTTPException(409, "有任务在跑，等它结束再改")
    ok, why = await draw.save_code(None, d, pid, page, str(payload.get("code") or ""))
    if not ok:
        raise HTTPException(400, why)
    store.set_page(pid, page, status="edited")
    return {"ok": True}


@router.post("/pages/{page}/redo")
async def redo_page(pid: str, page: str, payload: dict = Body(default={})) -> dict:
    """mode: redraw | change (with `change`) | check"""
    mode = (payload or {}).get("mode") or "redraw"
    change = str((payload or {}).get("change") or "").strip()
    if mode == "change" and not change:
        raise HTTPException(400, "写一下要怎么改")
    return _job(pid, "page", lambda j: draw.page_job(j, page, change, mode), f"{'修改' if mode == 'change' else '检查' if mode == 'check' else '重画'} {page}")


@router.post("/thumbs")
async def refresh_thumbs(pid: str) -> dict:
    thumbs.kick_film(store.pdir(pid), pid)
    return {"ok": True}


@router.post("/check")
async def film_check(pid: str, payload: dict = Body(default={})) -> dict:
    fix = bool((payload or {}).get("fix"))
    det = bool((payload or {}).get("determinism"))
    return _job(pid, "check", lambda j: draw.film_check_job(j, fix, det))


# ── film ──

@router.post("/render")
async def render(pid: str, payload: dict = Body(default={})) -> dict:
    p = payload or {}
    return _job(pid, "render", lambda j: produce.render_job(j, p.get("fps"), p.get("workers"), p.get("subs", True),
                                                            bool(p.get("draft"))))


@router.post("/render/clear-cache")
async def clear_cache(pid: str) -> dict:
    d = store.pdir(pid)
    if manager.current(pid):
        raise HTTPException(409, "有任务在跑")
    for sub in ("chunks", "subs", "sound", "chunks-portrait", "subs-portrait"):
        shutil.rmtree(d / "out" / sub, ignore_errors=True)
    return {"ok": True}


@router.post("/publish")
async def publish(pid: str) -> dict:
    return _job(pid, "publish", produce.publish_job)


@router.post("/auto")
async def auto(pid: str, payload: dict = Body(default={})) -> dict:
    p = payload or {}
    return _job(pid, "auto", lambda j: produce.auto_job(j, bool(p.get("skip_approval")), bool(p.get("draft"))))


@router.delete("/outputs/{name}")
async def del_output(pid: str, name: str) -> dict:
    d = store.pdir(pid)
    store.safe_path(d / "out", name).unlink()
    return {"ok": True}


# ── jobs ──

@router.get("/jobs/{job_id}")
async def job_status(pid: str, job_id: str, since: int = 0) -> dict:
    j = manager.get(job_id)
    if not j or j.pid != pid:
        # a job from before a restart: its log is on disk
        f = store.pdir(pid) / ".studio" / "jobs" / f"{job_id}.log"
        if not f.exists():
            raise HTTPException(404, "没有这个任务")
        lines = f.read_text("utf-8", "replace").splitlines()
        rec = next((x for x in store.get(pid).get("jobs", []) if x.get("id") == job_id), {})
        return {**rec, "lines": [{"t": 0, "level": "info", "msg": l} for l in lines[since:]], "next": len(lines)}
    lines, nxt = j.since(since)
    return {**j.summary(), "lines": lines, "next": nxt}


@router.post("/jobs/{job_id}/cancel")
async def cancel(pid: str, job_id: str) -> dict:
    return {"ok": manager.cancel(job_id)}
