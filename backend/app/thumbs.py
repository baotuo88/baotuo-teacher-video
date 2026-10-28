"""Clean stills for the interface: one per page of a film (out/thumbs/<page>.jpg), and one per sample film / style
(data/cache/thumbs/<example>.jpg). One browser draws all of a film's stills into a sheet, then ffmpeg cuts it up."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from . import config, engine, examples, store, styles
from .jobs import manager

TILE_W, TILE_H, PAD, COLS = 640, 360, 6, 3       # the engine's contact sheet: 3 per row, 6 px apart
_running: set[str] = set()


def settled(t: dict, last: bool) -> float:
    """A page fully drawn and at rest."""
    return max(t["speechEnd"], t["end"] - 1.2) if last else max(t["start"] + 0.5, t["end"] - 0.4)


async def _crop(sheet: Path, i: int, out: Path) -> None:
    x, y = (i % COLS) * (TILE_W + PAD), (i // COLS) * (TILE_H + PAD)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.jpg")
    code, _, err = await engine.run([config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(sheet),
                                     "-vf", f"crop={TILE_W}:{TILE_H}:{x}:{y}", "-q:v", "3", str(tmp)], out.parent, 60)
    if code:
        raise engine.ToolError(f"缩略图裁切失败：{err[-300:]}")
    tmp.replace(out)


async def film(d: Path, pid: str, log=None) -> int:
    """Every drawn page's still. → how many were made"""
    if pid in _running:
        return 0
    _running.add(pid)
    try:
        tl = await engine.timeline(d)
        pages = tl.get("pages") or []
        drawn = [i for i, t in enumerate(pages) if (d / "pages" / f"{t['id']}.js").exists()]
        if not drawn:
            return 0
        times = [settled(pages[i], i == len(pages) - 1) for i in drawn]
        p = store.get(pid)
        async with manager.browser:
            code, out, err = await engine.node(d, "snap.mjs", ["--sheet", "thumbs", *[f"{x:.2f}" for x in times]], 600,
                                               webgl=styles.is_webgl(p["style"]),
                                               env_extra={"SNAP_TILE": str(TILE_W), "SNAP_LABEL": "0"})
        sheet = d / "out" / "snap" / "thumbs.jpg"
        if code or not sheet.exists():
            raise engine.ToolError(f"缩略图失败：{(err or out)[-400:]}")
        v = int(time.time())
        made = {}
        for k, i in enumerate(drawn):
            await _crop(sheet, k, d / "out" / "thumbs" / f"{pages[i]['id']}.jpg")
            made[pages[i]["id"]] = v
        store.update(pid, lambda x: x.__setitem__("thumbs", {**(x.get("thumbs") or {}), **made}))
        if log:
            log(f"缩略图更新了 {len(made)} 张")
        return len(made)
    finally:
        _running.discard(pid)


def kick_film(d: Path, pid: str) -> None:
    """Make the film's stills in the background (never fails the caller)."""
    async def go() -> None:
        try:
            await film(d, pid)
        except Exception:  # noqa: BLE001
            pass
    asyncio.create_task(go())


# ── sample films (the style picker's pictures) ──

def cache_dir() -> Path:
    return config.DATA_DIR / "cache"


def example_thumb(eid: str) -> Path:
    return cache_dir() / "thumbs" / (eid.replace(":", "-") + ".jpg")


async def example(eid: str) -> Path | None:
    out = example_thumb(eid)
    if out.exists():
        return out
    if eid in _running:
        return None
    _running.add(eid)
    try:
        src = examples.source_dir(eid)
        work = cache_dir() / "src" / eid.replace(":", "-")
        rel = re.compile(r"""(['"])\.\./""")
        if not (work / "script.js").exists() or rel.search((work / "script.js").read_text("utf-8")):
            examples._copy_dir(src, work)
            store.link_engine(work)
            (work / "index.html").write_text(store.INDEX_HTML.format(lang="zh-CN", title=eid), "utf-8")
            if eid.startswith("style:"):
                # "../kit.js" means the style's own folder, which the copy is no longer inside
                s = (work / "script.js").read_text("utf-8")
                (work / "script.js").write_text(rel.sub(lambda m: f"{m[1]}engine/styles/{eid[6:]}/", s), "utf-8")
        tl = await engine.timeline(work)
        pages = tl.get("pages") or []
        if not pages:
            return None
        # a few pages past the hook; the busiest still (the biggest jpg) shows the style best, not a bare title page
        picks = list(range(1, len(pages)))[:8] or [0]
        style = eid.split(":", 1)[1] if eid.startswith("style:") else "study"
        times = [f"{settled(pages[i], i == len(pages) - 1):.2f}" for i in picks]
        async with manager.browser:
            code, o, err = await engine.node(work, "snap.mjs", ["--sheet", "thumb", *times], 300,
                                             webgl=styles.is_webgl(style), env_extra={"SNAP_TILE": str(TILE_W), "SNAP_LABEL": "0"})
        sheet = work / "out" / "snap" / "thumb.jpg"
        if code or not sheet.exists():
            return None
        tiles = [work / "out" / "snap" / f"thumb-{k}.jpg" for k in range(len(picks))]
        for k, t in enumerate(tiles):
            await _crop(sheet, k, t)
        best = max(tiles, key=lambda t: t.stat().st_size)
        out.parent.mkdir(parents=True, exist_ok=True)
        best.replace(out)
        return out
    except Exception:  # noqa: BLE001 - a missing picture falls back to the style's swatch
        return None
    finally:
        _running.discard(eid)


async def warm(delay: float = 0) -> None:
    """Stills for films made before there were stills, then every sample's picture; one after another, at low priority."""
    await asyncio.sleep(delay)
    for p in store.list_projects():
        if p.get("pages") and not p.get("thumbs"):
            try:
                await film(store.pdir(p["id"]), p["id"])
            except Exception:  # noqa: BLE001 - stills are for the interface only
                pass
    for x in examples.listing():
        if not example_thumb(x["id"]).exists():
            await example(x["id"])
