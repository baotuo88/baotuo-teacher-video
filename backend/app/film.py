"""A film's derived state: script.js META (owned by the server), stage status, the storyboard file."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from . import config, engine, settings, store, styles, voice

_locks: dict[str, asyncio.Lock] = {}

# META keys the server writes; anything else in META (look, mark, cover …) is kept as it is
OWNED = {"style", "lang", "title", "name", "gap", "pace", "extras", "libs", "voice", "webgl", "vendor", "publish"}
KATEX = ["katex/dist/katex.min.css", "katex/dist/katex.min.js"]


def lock(pid: str) -> asyncio.Lock:
    if pid not in _locks:
        _locks[pid] = asyncio.Lock()
    return _locks[pid]


def tts_cfg(p: dict) -> dict:
    return voice.cfg_for(p, settings.load()["tts"])


def voiced(p: dict) -> bool:
    return tts_cfg(p).get("provider") != "none"


def file_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", (title or "video").strip())[:40].strip("-") or "video"


def read_storyboard(d: Path) -> dict | None:
    f = d / "storyboard.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text("utf-8"))
    except json.JSONDecodeError:
        return None


def write_storyboard(d: Path, sb: dict) -> None:
    (d / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), "utf-8")


def page_dir(d: Path) -> Path:
    return d / "pages"


def page_code(d: Path, pid: str) -> str | None:
    f = page_dir(d) / f"{pid}.js"
    return f.read_text("utf-8") if f.exists() else None


EXTRAS_RE = re.compile(r"^\s*//\s*@extras\s+(.+)$", re.M)
LOGOS_RE = re.compile(r"^\s*//\s*@logos\s+(.+)$", re.M)


def parse_declares(code: str) -> tuple[list[str], list[str]]:
    """`// @extras gauges.js` and `// @logos openai` lines → (engine/lib paths, logo names)."""
    ex: list[str] = []
    for m in EXTRAS_RE.finditer(code):
        for n in re.split(r"[,\s]+", m.group(1)):
            n = n.strip().removeprefix("engine/lib/").removeprefix("lib/")
            if n and not n.endswith(".js"):
                n += ".js"
            if n and re.match(r"^[\w-]+\.js$", n) and (config.ENGINE_DIR / "lib" / n).exists():
                ex.append(f"engine/lib/{n}")
    lg: list[str] = []
    for m in LOGOS_RE.finditer(code):
        lg += [n.strip() for n in re.split(r"[,\s]+", m.group(1)) if re.match(r"^[\w:.-]+$", n.strip())]
    return list(dict.fromkeys(ex)), list(dict.fromkeys(lg))


async def read_pages(d: Path) -> list:
    try:
        return (await engine.read_script(d))["PAGES"]
    except engine.ToolError:
        return []


def bgm_sfx(p: dict, pages: list) -> dict | None:
    b = p.get("bgm")
    if not b or not pages:
        return None
    return {"f": f"assets/{b['file']}", "at": 0, "until": {"page": pages[-1]["id"], "at": "end"}, "loop": True,
            "vol": float(b.get("vol", -20)), "fin": 1.5, "fout": 2.5, "duck": float(b.get("duck", 6)), "bgm": True}


async def apply_meta(d: Path, pid: str, pages: list | None = None, title: str | None = None) -> dict:
    """Rewrite script.js with the server's META over what is there (and the given pages, when given)."""
    async with lock(pid):
        p = store.get(pid)
        cur = await engine.read_script(d) if (d / "script.js").exists() else {"META": {}, "PAGES": []}
        meta_cur, pages = cur["META"], (pages if pages is not None else cur["PAGES"])
        base = p.get("meta_base") or {}
        style = p["style"]
        page_states = p.get("pages") or {}
        live = {pg["id"] for pg in pages}
        extras = list(styles.extras(style)) + list(base.get("extras") or [])
        uses_tex = False
        for pg_id in sorted(live):
            extras += (page_states.get(pg_id) or {}).get("extras") or []
            code = page_code(d, pg_id) or ""
            uses_tex = uses_tex or "P.tex(" in code
        if (d / "extras" / "logos.js").exists() and p.get("logos"):
            extras.append("extras/logos.js")
        libs = list(base.get("libs") or []) + (KATEX if uses_tex else [])
        meta = {k: v for k, v in meta_cur.items() if k not in OWNED}
        t = title or meta_cur.get("title") or p["title"]
        meta.update({
            "style": style, "lang": p.get("lang", "zh"), "title": t,
            "name": file_name(title) if title else (meta_cur.get("name") or file_name(t)),
            "gap": base.get("gap", 0.8), "pace": base.get("pace", {"maxHold": 1.0, "gap": 0.8}),
            "extras": list(dict.fromkeys(extras)), "libs": list(dict.fromkeys(libs)),
        })
        if styles.is_webgl(style) or base.get("webgl"):
            meta["webgl"] = True
            meta["vendor"] = list(dict.fromkeys(["three", *(base.get("vendor") or [])]))
        elif base.get("vendor"):
            meta["vendor"] = base["vendor"]
        if p.get("publish"):
            meta["publish"] = p["publish"]
        # the narration is loaded only while voice.js matches every cue: a stale one would leave lines silent
        if (d / "voice.js").exists() and p.get("voice_sig") and p["voice_sig"] == voice.signature(pages) and voiced(p):
            meta["voice"] = {"speaker": p.get("voice_speaker") or "narrator"}
        # background music: one looping bed on the first page, until the film's end
        pages = [dict(pg) for pg in pages]
        for pg in pages:
            if pg.get("sfx"):
                pg["sfx"] = [s for s in pg["sfx"] if not s.get("bgm")]
                if not pg["sfx"]:
                    pg.pop("sfx")
        bed = bgm_sfx(p, pages)
        if bed:
            pages[0]["sfx"] = [bed, *(pages[0].get("sfx") or [])]
        engine.write_script(d, meta, pages)
        return {"META": meta, "PAGES": pages}


def voice_status(d: Path, p: dict, pages: list) -> str:
    if not voiced(p):
        return "off"
    if not (d / "voice.js").exists() or not p.get("voice_sig"):
        return "none"
    return "ok" if p["voice_sig"] == voice.signature(pages) else "stale"


def outputs(d: Path) -> list[dict]:
    out = d / "out"
    if not out.exists():
        return []
    files = []
    for f in sorted(out.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix in (".mp4", ".srt", ".md") and not f.name.endswith(".tmp.mp4"):
            files.append({"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
    return files


async def overview(d: Path, p: dict) -> dict:
    """Everything the workspace shows at once."""
    try:
        data = await engine.read_script(d)
        script_err = ""
    except engine.ToolError as e:
        data, script_err = {"META": {}, "PAGES": []}, str(e)
    pages = data["PAGES"]
    sb = read_storyboard(d)
    ids = [pg["id"] for pg in pages] or [pg.get("id") for pg in (sb or {}).get("pages", [])]
    drawn = [i for i in ids if (page_dir(d) / f"{i}.js").exists()]
    films = [f for f in outputs(d) if f["name"].endswith(".mp4")]
    latest_src = max([f.stat().st_mtime for f in [d / "script.js", d / "voice.js", *page_dir(d).glob("*.js")] if f.exists()] or [0])
    return {
        "storyboard": bool(sb), "storyboard_status": p.get("storyboard_status"),
        "script": bool(pages) and (d / "script.js").exists() and p.get("script_written", False),
        "script_error": script_err,
        "pages_total": len(ids), "pages_drawn": len(drawn),
        "voice": voice_status(d, p, pages),
        "film": bool(films), "film_stale": bool(films) and films[0]["mtime"] < latest_src,
        "title": data["META"].get("title") or p["title"],
    }
