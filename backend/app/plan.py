"""Stages 1–2: storyboard and narration, written by the model as JSON; files written and checked by the server."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import engine, film, llm, materials, prompts, settings, store, zh
from .jobs import Job, Stop
from .llm import Msg

STORYBOARD_FIXES = 2
SCRIPT_FIXES = 2


def _prefs() -> str:
    return settings.load().get("preferences", "")


def normalize_storyboard(sb: dict, p: dict) -> dict:
    if "pages" not in sb and isinstance(sb.get("storyboard"), dict):
        sb = sb["storyboard"]
    pages = [x for x in (sb.get("pages") or []) if isinstance(x, dict)]
    for i, pg in enumerate(pages):
        pg["id"] = f"p{i + 1:02d}"
        pg["beats"] = [b for b in (pg.get("beats") or []) if isinstance(b, dict)]
    sb["pages"] = pages
    sb["style"] = p["style"]
    sb["durationSec"] = int(p.get("duration") or 90)
    sb["lang"] = "en" if p.get("lang") == "en" else "zh"
    sb.pop("look", None)
    return sb


def own_storyboard_issues(sb: dict, p: dict) -> list[dict]:
    out = []
    b = prompts.budget(int(p.get("duration") or 90))
    n = len(sb.get("pages") or [])
    if n == 0:
        out.append({"level": "red", "msg": "the storyboard has no pages"})
    if n > b["pages"]:
        out.append({"level": "red", "msg": f"{n} pages is more than the {b['pages']} this length allows: condense"})
    for pg in sb.get("pages") or []:
        if len(pg.get("beats") or []) < 2:
            out.append({"level": "red", "page": pg["id"], "msg": "at least 2 beats per page"})
    return out


async def _storyboard_round(job: Job, d: Path, p: dict, system: str, msgs: list[Msg]) -> tuple[dict, str, list[dict]]:
    """Ask, parse, lint; up to STORYBOARD_FIXES fix rounds. → (storyboard, report, remaining issues)"""
    report = ""
    for rnd in range(STORYBOARD_FIXES + 1):
        r = await llm.chat(system, msgs, pid=p["id"], log=job.log)
        msgs.append(Msg("assistant", r.text))
        try:
            sb = normalize_storyboard(llm.json_block(r.text), p)
        except ValueError as e:
            if rnd == STORYBOARD_FIXES:
                raise
            job.log(f"分镜格式不对，重来一次：{e}", "warn")
            msgs.append(Msg("user", f"I could not read that: {e}. Answer with the whole storyboard as one ```json block."))
            continue
        report = llm.outside_blocks(r.text) or report
        film.write_storyboard(d, sb)
        issues = own_storyboard_issues(sb, p) + await engine.storyboard_lint(d)
        reds = [i for i in issues if i.get("level") == "red"]
        job.log(f"分镜 {len(sb['pages'])} 页 · 检查：{len(reds)} 处必改，{len(issues) - len(reds)} 处建议")
        if not reds or rnd == STORYBOARD_FIXES:
            return sb, report, issues
        for i in reds[:8]:
            job.log(f"  ✗ {i.get('page') or '全片'}：{zh.storyboard(i.get('msg') or '')}", "warn")
        msgs.append(Msg("user", prompts.storyboard_fix_prompt(issues, p.get("lang", "zh"))))
    raise RuntimeError("unreachable")


def _save_storyboard(pid: str, sb: dict, report: str, issues: list[dict]) -> None:
    def f(d: dict) -> None:
        d["storyboard_status"] = "draft"
        d["storyboard_issues"] = issues
        d["storyboard_report"] = report
        if sb.get("title"):
            d["title"] = sb["title"][:80]
    store.update(pid, f)


async def storyboard_job(job: Job) -> str:
    p = store.get(job.pid)
    d = store.pdir(job.pid)
    mats = materials.read_all(d)
    job.log(f"素材 {len(mats)} 份 · 风格 {p['style']} · 目标 {p['duration']} 秒")
    system = prompts.planner_system(p["style"], _prefs())
    msgs = [Msg("user", prompts.storyboard_prompt(p, mats, film.voiced(p)))]
    job.log("导演在写分镜…")
    sb, report, issues = await _storyboard_round(job, d, p, system, msgs)
    _save_storyboard(job.pid, sb, report, issues)
    if report:
        job.log(report, "say")
    return f"{len(sb['pages'])} 页分镜，等你确认"


async def storyboard_revise_job(job: Job, feedback: str) -> str:
    p = store.get(job.pid)
    d = store.pdir(job.pid)
    sb = film.read_storyboard(d)
    if not sb:
        raise RuntimeError("还没有分镜")
    system = prompts.planner_system(p["style"], _prefs())
    msgs = [Msg("user", prompts.storyboard_revise_prompt(json.dumps(sb, ensure_ascii=False, indent=1), feedback, p,
                                                         materials.read_all(d)))]
    job.log(f"按你的意见改分镜：{feedback[:120]}")
    sb, report, issues = await _storyboard_round(job, d, p, system, msgs)
    _save_storyboard(job.pid, sb, report, issues)
    store.update(job.pid, lambda x: x.setdefault("feedback_log", []).append(feedback))
    if report:
        job.log(report, "say")
    return "分镜已按意见修改"


# ── narration ──

def _units(text: str, lang: str) -> int:
    if lang == "en":
        return len(text.split())
    return len(re.findall(r"[一-鿿0-9A-Za-z]", text))


def normalize_pages(raw: dict, sb: dict) -> list[dict]:
    pages = raw.get("pages") if isinstance(raw, dict) else raw
    if not isinstance(pages, list):
        raise ValueError("narration JSON has no pages array")
    sbp = sb.get("pages") or []
    out = []
    for i, pg in enumerate(x for x in pages if isinstance(x, dict)):
        cues = []
        for c in pg.get("cues") or []:
            if isinstance(c, str) and c.strip():
                cues.append(c.strip())
            elif isinstance(c, dict) and str(c.get("t", "")).strip():
                cue = {"t": str(c["t"]).strip()}
                if c.get("hold"):
                    cue["hold"] = round(min(float(c["hold"]), 3.0), 2)
                cues.append(cue)
        ref = sbp[i] if i < len(sbp) else {}
        out.append({"id": f"p{i + 1:02d}", "section": str(pg.get("section") or ref.get("section") or ""),
                    "title": str(pg.get("title") or ref.get("section") or ""), "cues": cues})
    return out


def script_problems(pages: list[dict], sb: dict, duration: float, target: int, lang: str) -> list[str]:
    out = []
    sbp = sb.get("pages") or []
    if len(pages) != len(sbp):
        out.append(f"the narration has {len(pages)} pages but the storyboard has {len(sbp)}: write exactly one per storyboard page, in order")
    limit = 12 if lang == "en" else 16
    for pg, ref in zip(pages, sbp):
        texts = [engine.cue_text(c) for c in pg["cues"]]
        if len(texts) < 2:
            out.append(f"{pg['id']}: at least 2 cues")
        for b in ref.get("beats") or []:
            m = re.match(r"^c(\d+)(?::(.+))?$", str(b.get("at") or "").strip())
            if not m:
                continue
            ci = int(m.group(1))
            if ci >= len(texts):
                out.append(f"{pg['id']}: a beat is at c{ci}, but the page has only {len(texts)} cues")
            elif m.group(2) and m.group(2).strip() not in texts[ci]:
                out.append(f"{pg['id']}: cue {ci} must contain the word \"{m.group(2).strip()}\" verbatim (a beat is tied to it)")
        for t in texts:
            if _units(t, lang) > limit + 8:
                out.append(f"{pg['id']}: the cue \"{t[:30]}\" is too long ({_units(t, lang)}); at most {limit}")
    b = prompts.budget(target)
    if duration > b["estimate"]:
        out.append(f"the narration is estimated at {duration:.0f}s, over the {b['estimate']}s limit for a {target}s film: "
                   "condense (secondary detail, extra examples and repetition give way first)")
    return out


async def script_job(job: Job, feedback: str = "") -> str:
    p = store.get(job.pid)
    d = store.pdir(job.pid)
    sb = film.read_storyboard(d)
    if not sb:
        raise RuntimeError("还没有分镜：先生成分镜")
    if p["storyboard_status"] != "approved":
        store.update(job.pid, {"storyboard_status": "approved"})
    system = prompts.planner_system(p["style"], _prefs())
    msgs = [Msg("user", prompts.script_prompt(json.dumps(sb, ensure_ascii=False, indent=1), p, film.voiced(p), feedback))]
    job.log("导演在写口播…")
    lang = p.get("lang", "zh")
    pages, report, problems, duration = [], "", [], 0.0
    title = sb.get("title") or p["title"]
    for rnd in range(SCRIPT_FIXES + 1):
        r = await llm.chat(system, msgs, pid=job.pid, log=job.log)
        msgs.append(Msg("assistant", r.text))
        try:
            raw = llm.json_block(r.text)
            pages = normalize_pages(raw, sb)
        except ValueError as e:
            if rnd == SCRIPT_FIXES:
                raise
            msgs.append(Msg("user", f"I could not read that: {e}. Answer with the whole narration as one ```json block."))
            continue
        report = llm.outside_blocks(r.text) or report
        title = (raw.get("title") if isinstance(raw, dict) else None) or sb.get("title") or p["title"]
        await film.apply_meta(d, job.pid, pages, title=title)
        tl = await engine.timeline(d)
        duration = float(tl.get("duration") or 0)
        problems = script_problems(pages, sb, duration, int(p["duration"]), lang)
        job.log(f"口播 {sum(len(x['cues']) for x in pages)} 句 · 估算 {duration:.0f} 秒"
                + (f" · {len(problems)} 处要改" if problems else ""))
        if not problems or rnd == SCRIPT_FIXES:
            break
        for x in problems[:6]:
            job.log(f"  · {x}", "warn")
        msgs.append(Msg("user", prompts.script_fix_prompt(problems, lang)))
    try:
        await engine.script_tool(d)
    except engine.ToolError as e:
        job.log(str(e), "warn")
    store.update(job.pid, {"script_written": True, "script_report": report, "script_issues": problems,
                           "title": (title or p["title"])[:80]})
    if report:
        job.log(report, "say")
    return f"口播约 {duration:.0f} 秒"


async def ensure_approved(job: Job, skip_approval: bool) -> None:
    p = store.get(job.pid)
    if p["storyboard_status"] == "approved":
        return
    if skip_approval:
        store.update(job.pid, {"storyboard_status": "approved"})
        job.log("已按设置自动确认分镜")
        return
    raise Stop("分镜已生成，请在「分镜」里看一遍、确认后再继续")
