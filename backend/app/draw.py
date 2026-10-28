"""Stage 4: pages. Each page is written by the model, then checked in the browser (layout lint + contact sheet) and,
with a vision model, looked at by a reviewer; problems go back to the model, a few rounds at most."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from . import engine, film, llm, prompts, settings, store, styles, thumbs
from .jobs import Job, manager
from .llm import Msg

_logo_locks: dict[str, asyncio.Lock] = {}


def must_fix(issues: list[dict]) -> list[dict]:
    """What a viewer sees broken: every error, and text too small to read."""
    return [i for i in issues if i.get("level") == "error" or i.get("kind") == "small-text"]


def clean_code(code: str) -> str:
    code = code.strip("\n")
    code = re.sub(r"^```\w*\s*\n", "", code)
    code = re.sub(r"\n```\s*$", "", code)
    return code.rstrip() + "\n"


async def page_timing(d: Path, pid: str) -> dict:
    tl = await engine.timeline(d)
    t = next((x for x in tl.get("pages", []) if x["id"] == pid), None)
    if not t:
        raise RuntimeError(f"口播里没有 {pid} 这一页")
    t["voiced"] = tl.get("voiced")
    return t


async def build_logos(d: Path, pid: str) -> None:
    """One extras/logos.js for every logo any page asked for."""
    lk = _logo_locks.setdefault(pid, asyncio.Lock())
    async with lk:
        p = store.get(pid)
        names = sorted({n for st in (p.get("pages") or {}).values() for n in (st.get("logos") or [])})
        if names == sorted(p.get("logos") or []) and (d / "extras" / "logos.js").exists():
            return
        if names:
            (d / "extras").mkdir(exist_ok=True)
            await engine.logos(d, names)
        store.update(pid, {"logos": names})


async def save_code(job: Job | None, d: Path, proj: str, page_id: str, code: str) -> tuple[bool, str]:
    """Write pages/<id>.js, register what it declares. → (ok, problem)"""
    code = clean_code(code)
    if not re.search(r"ENGINE\.visual\(\s*['\"]" + re.escape(page_id) + r"['\"]", code):
        return False, f"the file must define the page with ENGINE.visual('{page_id}', (P) => {{ … }})"
    f = film.page_dir(d) / f"{page_id}.js"
    f.parent.mkdir(exist_ok=True)
    f.write_text(code, "utf-8")
    extras, logos = film.parse_declares(code)
    store.set_page(proj, page_id, extras=extras, logos=logos)
    if logos:
        try:
            await build_logos(d, proj)
        except engine.ToolError as e:
            if job:
                job.log(f"{page_id}: {e}", "warn")
    await film.apply_meta(d, proj)
    err = await engine.syntax_check(f)
    return (False, f"syntax error:\n{err}") if err else (True, "")


async def run_check(d: Path, proj: str, page_id: str, sb: dict | None, rnd: int, determinism: bool = False) -> dict:
    t = await page_timing(d, page_id)
    sbp = next((x for x in (sb or {}).get("pages", []) if x.get("id") == page_id), None)
    last = bool(sb and sb.get("pages") and sb["pages"][-1].get("id") == page_id)
    times = prompts.sheet_times(sbp, t, last)
    p = store.get(proj)
    async with manager.browser:
        res = await engine.check_page(d, page_id, f"{page_id}-r{rnd}-{int(time.time()) % 100000}",
                                      [x["t"] for x in times], webgl=styles.is_webgl(p["style"]), determinism=determinism)
    res["times"] = times
    res["timing"] = t
    return res


async def review(sb: dict, proj: str, page_id: str, t: dict, rnd: int, issues: list[dict], times: list[dict],
                 sheet: Path, convo: list[Msg], system: str, change: str, log) -> dict | None:
    convo.append(Msg("user", prompts.reviewer_prompt(sb, page_id, t, rnd, issues, times, change), [sheet]))
    # only the newest sheet travels: older rounds keep their words
    for m in convo[:-1]:
        m.images = []
    try:
        r = await llm.chat(system, convo, review=True, max_tokens=2000, pid=proj, log=log)
        convo.append(Msg("assistant", r.text))
        v = llm.json_block(r.text)
        if isinstance(v, dict) and "pass" in v:
            probs = [x for x in (v.get("problems") or []) if isinstance(x, dict)][:5]
            passed = bool(v["pass"]) or not probs   # a fail with nothing to fix is a pass
            return {"pass": passed, "problems": [] if passed else probs}
    except (llm.LLMError, ValueError) as e:
        log(f"{page_id}: 审片没给出结论（{str(e)[:100]}），只按机器检查", "warn")
    return None


async def draw_one(job: Job, page_id: str, *, change: str = "", fresh: bool = True, check_only: bool = False) -> str:
    """Write (or change, or only check) one page and take it through the check rounds. → final status"""
    proj = job.pid
    d = store.pdir(proj)
    p = store.get(proj)
    cfg = settings.load()
    vision = bool(cfg["llm"].get("vision"))
    use_review = vision and cfg["pipeline"].get("review", True)
    rounds = max(1, int(cfg["pipeline"].get("page_rounds") or 3))
    sb = film.read_storyboard(d) or {"title": p["title"], "pages": []}
    system = prompts.page_system(p["style"], cfg.get("preferences", ""))
    rsystem = prompts.reviewer_system(p["style"], p.get("lang", "zh")) if use_review else ""
    rconvo: list[Msg] = []
    t = await page_timing(d, page_id)
    current = film.page_code(d, page_id)
    first = prompts.page_prompt(sb, page_id, t, p)
    if change and not current:
        first += f"\n\nThe user also asks: {change}"
    msgs: list[Msg] = [Msg("user", first)]

    async def ask(extra: Msg | None = None, label: str = "") -> str | None:
        """→ the new code, or None when the model flagged the problems instead"""
        if extra:
            msgs.append(extra)
        async with manager.llm:
            store.set_page(proj, page_id, status="drawing" if not label else "fixing")
            job.log(f"{page_id}: {label or '在画'}…")
            r = await llm.chat(system, msgs, pid=proj, log=job.log)
        msgs.append(Msg("assistant", r.text))
        for m in msgs[:-1]:
            m.images = []
        flag = re.search(r"^\s*@flag\s+(.+)$", r.text, re.M)
        code = llm.code_block(r.text, ("js", "javascript"))
        if flag and not code:
            store.set_page(proj, page_id, note=flag.group(1).strip()[:300])
            job.log(f"{page_id}: 保留现状：{flag.group(1).strip()[:120]}")
            return None
        if not code:
            if r.truncated:
                msgs.append(Msg("user", "Your answer was cut off by the length limit. Write the page shorter (fewer lines, "
                                        "helpers instead of repetition) and answer with the complete file in one ```js block."))
            else:
                msgs.append(Msg("user", "Answer with the complete page file in one ```js code block."))
            async with manager.llm:
                r = await llm.chat(system, msgs, pid=proj, log=job.log)
            msgs.append(Msg("assistant", r.text))
            code = llm.code_block(r.text, ("js", "javascript"))
            if not code:
                raise RuntimeError(f"{page_id}: 模型没有给出页面代码")
        say = llm.outside_blocks(r.text).strip()
        if say:
            store.set_page(proj, page_id, say=say[:300])
        return code

    if not check_only:
        if change and current:
            msgs.append(Msg("assistant", f"```js\n{current}\n```"))
            code = await ask(Msg("user", prompts.revise_prompt(page_id, current, change)), "按要求修改")
        elif current and not fresh:
            msgs.append(Msg("assistant", f"```js\n{current}\n```"))
            code = None
        else:
            code = await ask()
        if code:
            ok, why = await save_code(job, d, proj, page_id, code)
            if not ok:
                code = await ask(Msg("user", f"The server could not use that file: {why}\nAnswer with the corrected complete file."), "修正语法")
                if code:
                    ok, why = await save_code(job, d, proj, page_id, code)
                if not ok:
                    store.set_page(proj, page_id, status="failed", note=why[:400])
                    return "failed"
    elif current:
        msgs.append(Msg("assistant", f"```js\n{current}\n```"))
    if film.page_code(d, page_id) is None:
        store.set_page(proj, page_id, status="failed", note="还没有页面代码")
        return "failed"

    status = "done"
    for rnd in range(1, rounds + 1):
        store.set_page(proj, page_id, status="checking", rounds=rnd)
        res = await run_check(d, proj, page_id, sb, rnd)
        issues = res.get("issues") or []
        crash = res.get("crash") or ""
        sheet = d / res["sheet"] if res.get("sheet") else None
        errors = must_fix(issues)
        verdict = None
        if use_review and sheet and sheet.exists() and not crash and not errors:
            store.set_page(proj, page_id, status="reviewing")
            async with manager.llm:
                verdict = await review(sb, proj, page_id, res["timing"], rnd, issues, res["times"], sheet, rconvo,
                                       rsystem, change, job.log)
        problems = (verdict or {}).get("problems") or []
        store.set_page(proj, page_id, issues=issues, problems=problems,
                       sheet=res.get("sheet") or "", crash=crash[:2000], times=[x["local"] for x in res["times"]])
        if not crash and not errors and not problems:
            job.log(f"{page_id}: ✓ 通过（第 {rnd} 轮）", "ok")
            status = "done"
            break
        what = "运行出错" if crash else (f"{len(errors)} 处必改" if errors else f"审片提了 {len(problems)} 处")
        job.log(f"{page_id}: 第 {rnd} 轮检查：{what}", "warn")
        if rnd == rounds:
            status = "flagged"
            break
        img = [sheet] if (vision and sheet and sheet.exists()) else []
        code = await ask(Msg("user", prompts.fix_prompt(rnd, errors, problems, res["times"], crash, change, bool(img)), img),
                         f"第 {rnd} 轮修改")
        if code is None:
            status = "flagged"
            break
        ok, why = await save_code(job, d, proj, page_id, code)
        if not ok:
            code = await ask(Msg("user", f"The server could not use that file: {why}\nAnswer with the corrected complete file."), "修正语法")
            if not code or not (await save_code(job, d, proj, page_id, code))[0]:
                status = "failed"
                break
    store.set_page(proj, page_id, status=status)
    return status


async def _stills(job: Job, d: Path) -> None:
    try:
        await thumbs.film(d, job.pid, job.log)
    except Exception as e:  # noqa: BLE001 - stills are for the interface only
        job.log(f"缩略图没生成：{str(e)[:200]}", "warn")


async def _pages_to_draw(d: Path, proj: str, only: list[str] | None, redo: bool) -> list[str]:
    pages = await film.read_pages(d)
    if not pages:
        raise RuntimeError("还没有口播：先完成「口播」一步")
    ids = [pg["id"] for pg in pages]
    if only:
        return [i for i in ids if i in only]
    st = store.get(proj).get("pages") or {}
    if redo:
        return ids
    return [i for i in ids if film.page_code(d, i) is None or (st.get(i) or {}).get("status") in ("failed", None, "queued")]


async def pages_job(job: Job, only: list[str] | None = None, redo: bool = False) -> str:
    d = store.pdir(job.pid)
    todo = await _pages_to_draw(d, job.pid, only, redo)
    if not todo:
        return "所有页面都画好了"
    for i in todo:
        store.set_page(job.pid, i, status="queued", note="")
    job.log(f"要画 {len(todo)} 页：{' '.join(todo)}")
    job.set_progress(done=0, total=len(todo))
    results: dict[str, str] = {}

    async def one(i: str) -> None:
        try:
            results[i] = await draw_one(job, i, fresh=True)
        except asyncio.CancelledError:
            store.set_page(job.pid, i, status="failed", note="已取消")
            raise
        except Exception as e:  # noqa: BLE001 - one page failing must not stop the others
            results[i] = "failed"
            store.set_page(job.pid, i, status="failed", note=str(e)[:400])
            job.log(f"{i}: ✗ {e}", "error")
        job.set_progress(done=len(results), total=len(todo))

    await asyncio.gather(*(one(i) for i in todo))
    await film.apply_meta(d, job.pid)
    await _stills(job, d)
    n = {s: sum(1 for v in results.values() if v == s) for s in ("done", "flagged", "failed")}
    if n["failed"] == len(todo):
        raise RuntimeError("所有页面都失败了，看上面的日志")
    return f"通过 {n['done']} 页" + (f"，需关注 {n['flagged']} 页" if n["flagged"] else "") + (f"，失败 {n['failed']} 页" if n["failed"] else "")


async def page_job(job: Job, page_id: str, change: str = "", mode: str = "redraw") -> str:
    """mode: redraw (from scratch) | change (apply `change`) | check (check and fix the page as it is)"""
    job.set_progress(page=page_id)
    st = await draw_one(job, page_id, change=change, fresh=mode == "redraw", check_only=mode == "check")
    await _stills(job, store.pdir(job.pid))
    return {"done": f"{page_id} 通过", "flagged": f"{page_id} 还有问题，需要你看一下", "failed": f"{page_id} 失败"}[st]


async def film_check_job(job: Job, fix: bool = False, determinism: bool = False) -> str:
    """Lint every page (and optionally fix the ones with must-fix findings), plus an overview sheet."""
    d = store.pdir(job.pid)
    p = store.get(job.pid)
    webgl = styles.is_webgl(p["style"])
    await film.apply_meta(d, job.pid)
    tl = await engine.timeline(d)
    job.log(f"全片 {len(tl['pages'])} 页 · {tl['duration']:.0f} 秒 · 逐页检查…")
    async with manager.browser:
        issues = await engine.lint_all(d, webgl=webgl, determinism=determinism)
    by_page: dict[str, list[dict]] = {}
    for i in issues:
        by_page.setdefault(i.get("page") or "?", []).append(i)
    bad = [pid for pid, xs in by_page.items() if must_fix(xs)]
    times = []
    for t in tl["pages"]:
        times += [t["start"] + (t["speechEnd"] - t["start"]) * 0.55, max(t["start"] + 0.5, t["end"] - 0.4)]
    sheet = ""
    try:
        async with manager.browser:
            f = await engine.snap(d, f"film-{int(time.time()) % 100000}", times, webgl=webgl, tile=320)
        sheet = str(f.relative_to(d))
    except engine.ToolError as e:
        job.log(str(e), "warn")
    store.update(job.pid, {"film_check": {"at": time.time(), "issues": issues, "bad": bad, "sheet": sheet,
                                          "duration": tl["duration"]}})
    for pid, xs in by_page.items():
        store.set_page(job.pid, pid, issues=xs)
    job.log(f"检查完：{len(issues)} 条，必改 {sum(len(must_fix(x)) for x in by_page.values())} 条，涉及 {len(bad)} 页")
    if fix and bad:
        job.log(f"自动修：{' '.join(bad)}")
        for pid in bad:
            await draw_one(job, pid, check_only=True)
    await _stills(job, d)
    return f"{len(bad)} 页有必改问题" if bad else "全片没有必改问题"
