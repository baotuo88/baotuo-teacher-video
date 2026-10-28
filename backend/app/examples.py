"""Sample films: every style's benchmark film from the engine, and the films bundled in backend/examples/."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException

from . import config, store, styles


def _meta(script: Path) -> dict:
    """META.title / name / style of a sample's script.js (read with node: it is JavaScript)."""
    js = config.ROOT / "backend" / "app" / "js" / "read-script.mjs"
    try:
        out = subprocess.run([config.NODE, str(js), str(script.parent)], capture_output=True, text=True, timeout=20).stdout
        data = json.loads(out.strip().splitlines()[-1])
        return {"meta": data.get("META") or {}, "pages": len(data.get("PAGES") or [])}
    except (subprocess.SubprocessError, json.JSONDecodeError, IndexError, OSError):
        return {"meta": {}, "pages": 0}


_cache: list[dict] | None = None


def listing() -> list[dict]:
    global _cache
    if _cache is not None:
        return _cache
    out = []
    if config.EXAMPLES_DIR.exists():
        for d in sorted(config.EXAMPLES_DIR.iterdir()):
            if (d / "script.js").exists():
                m = _meta(d / "script.js")
                out.append({"id": f"app:{d.name}", "title": m["meta"].get("title") or d.name,
                            "style": m["meta"].get("style", "study"), "pages": m["pages"], "source": "app"})
    for s in styles.all_styles():
        f = config.ENGINE_DIR / "styles" / s["id"] / "example" / "script.js"
        if f.exists():
            m = _meta(f)
            out.append({"id": f"style:{s['id']}", "title": m["meta"].get("title") or s["name"], "style": s["id"],
                        "style_name": s["name"], "pages": m["pages"], "source": "style"})
    _cache = out
    return out


def source_dir(eid: str) -> Path:
    kind, _, name = eid.partition(":")
    if not re.match(r"^[a-z0-9-]+$", name):
        raise HTTPException(404, "没有这个样片")
    d = (config.EXAMPLES_DIR / name) if kind == "app" else (config.ENGINE_DIR / "styles" / name / "example") if kind == "style" else None
    if not d or not (d / "script.js").exists():
        raise HTTPException(404, "没有这个样片")
    return d


def _copy_dir(src: Path, dst: Path) -> None:
    """Contents only, no metadata (copystat fails on some filesystems and mounts)."""
    for f in src.rglob("*"):
        if f.is_file() and not f.is_symlink():
            t = dst / f.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, t)


def create_from(eid: str) -> dict:
    src = source_dir(eid)
    m = _meta(src / "script.js")["meta"]
    style = m.get("style") or "study"
    if not styles.exists(style):
        style = "study"
    p = store.create({"title": m.get("title") or "样片", "style": style, "lang": m.get("lang") or "zh",
                      "imported": eid, "storyboard_status": "approved", "script_written": True})
    d = config.PROJECTS_DIR / p["id"]
    for name in ("script.js", "storyboard.json"):
        if (src / name).exists():
            shutil.copyfile(src / name, d / name)
    for sub in ("pages", "materials", "extras", "assets"):
        if (src / sub).is_dir():
            _copy_dir(src / sub, d / sub)
    keep = {k: m[k] for k in ("extras", "libs", "vendor", "webgl", "gap", "pace") if k in m}
    # a style sample's "../kit.js" only resolves beside the sample; the film gets the style's kit from its style anyway
    if keep.get("extras"):
        keep["extras"] = [x for x in keep["extras"] if not str(x).startswith("../")]
    # a sample's voice.js is not shipped: its META.voice would point at nothing
    pages = {f.stem: {"status": "done", "rounds": 0} for f in (d / "pages").glob("*.js")}
    store.update(p["id"], {"meta_base": keep, "pages": pages, "duration": 90 if not m.get("duration") else m["duration"]})
    return store.get(p["id"])
