"""Projects on disk. A project is a Frametell episode directory plus `.studio/` for this app's own state:

  <id>/index.html script.js voice.js pages/ audio/ assets/ materials/ out/   ← the engine's episode
  <id>/engine → ENGINE_DIR, <id>/engine_modules → ENGINE_DIR/node_modules   ← links the engine needs
  <id>/.studio/project.json                                                 ← brief, stage, page states, jobs
  <id>/.studio/jobs/<job>.log                                               ← job logs
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import config

ID_RE = re.compile(r"^[a-z0-9]{10}$")
_lock = threading.Lock()

DEFAULT_PROJECT: dict[str, Any] = {
    "id": "",
    "title": "",
    "topic": "",
    "audience": "",
    "notes": "",
    "kind": "explainer",        # explainer | github
    "repo": "",                 # github kind: the repository URL
    "style": "whiteboard",
    "lang": "zh",
    "duration": 90,
    "created": 0,
    "updated": 0,
    "storyboard_status": "none",  # none | draft | approved
    "storyboard_issues": [],
    "storyboard_report": "",
    "script_report": "",
    "script_issues": [],
    "voice": {},                  # overrides of settings.tts for this film
    "voice_sig": "",              # signature of the cues voice.js was made for
    "voice_speaker": "",
    "voice_stats": None,
    "script_written": False,
    "thumbs": {},                 # page id → version of out/thumbs/<page>.jpg
    "logos": [],                  # brand logos the pages asked for (extras/logos.js)
    "pages": {},                  # id → { status, rounds, issues, problems, sheet, note, extras, logos, updated }
    "film_check": None,
    "assets": {},                 # file name → description
    "bgm": None,                  # { file, vol }
    "meta_base": {},              # META keys an imported film brought (extras, libs, vendor, webgl, look …)
    "imported": "",               # example id when made from a sample film
    "publish": None,
    "cover": "",
    "renders": [],
    "usage": {"input": 0, "output": 0, "calls": 0},
    "jobs": [],
}


def new_id() -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def pdir(pid: str) -> Path:
    if not ID_RE.match(pid or ""):
        raise HTTPException(404, "没有这个项目")
    d = config.PROJECTS_DIR / pid
    if not (d / ".studio" / "project.json").exists():
        raise HTTPException(404, "没有这个项目")
    return d


def _pfile(pid: str) -> Path:
    return config.PROJECTS_DIR / pid / ".studio" / "project.json"


def _read(pid: str) -> dict:
    f = _pfile(pid)
    data = json.loads(f.read_text("utf-8"))
    out = copy.deepcopy(DEFAULT_PROJECT)
    out.update(data)
    return out


def _write(pid: str, data: dict) -> None:
    f = _pfile(pid)
    data["updated"] = time.time()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(f)


def get(pid: str) -> dict:
    pdir(pid)
    with _lock:
        return _read(pid)


def update(pid: str, fn: Callable[[dict], Any] | dict) -> dict:
    """Read-modify-write under one lock: `fn` mutates the dict (or a dict is merged in)."""
    pdir(pid)
    with _lock:
        data = _read(pid)
        if callable(fn):
            fn(data)
        else:
            data.update(fn)
        _write(pid, data)
        return data


def set_page(pid: str, page_id: str, **fields: Any) -> None:
    def f(d: dict) -> None:
        cur = d["pages"].setdefault(page_id, {})
        cur.update(fields)
        cur["updated"] = time.time()
    update(pid, f)


def list_projects() -> list[dict]:
    out = []
    if not config.PROJECTS_DIR.exists():
        return out
    for d in config.PROJECTS_DIR.iterdir():
        if ID_RE.match(d.name) and (d / ".studio" / "project.json").exists():
            try:
                with _lock:
                    out.append(_read(d.name))
            except (json.JSONDecodeError, OSError):
                continue
    out.sort(key=lambda p: p.get("updated", 0), reverse=True)
    return out


INDEX_HTML = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="engine-modules" content="engine_modules/">
<title>{title}</title>
<script src="script.js"></script>
<script src="engine/boot.js"></script>
</head>
<body></body>
</html>
"""


def link_engine(d: Path) -> None:
    """(Re)create the engine links; the engine may live elsewhere after a rebuild or a move."""
    targets = {"engine": config.ENGINE_DIR, "engine_modules": (config.ENGINE_DIR / "node_modules").resolve()}
    for name, target in targets.items():
        at = d / name
        try:
            if at.is_symlink():
                if Path(os.readlink(at)) == target:
                    continue
                at.unlink()
            elif at.exists():
                shutil.rmtree(at)
        except OSError:
            pass
        at.symlink_to(target, target_is_directory=True)


def create(fields: dict) -> dict:
    config.ensure_dirs()
    pid = new_id()
    d = config.PROJECTS_DIR / pid
    for sub in ("pages", "audio", "assets", "materials", "out", ".studio/jobs", ".studio/uploads"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    data = copy.deepcopy(DEFAULT_PROJECT)
    data.update({k: v for k, v in fields.items() if k in DEFAULT_PROJECT})
    data["id"] = pid
    data["title"] = (data["title"] or data["topic"] or "未命名视频").strip()[:80]
    data["created"] = time.time()
    lang = "en" if data["lang"] == "en" else "zh-CN"
    from html import escape
    (d / "index.html").write_text(INDEX_HTML.format(lang=lang, title=escape(data["title"])), "utf-8")
    (d / ".gitignore").write_text("engine\nengine_modules\nout/\n.studio/\n", "utf-8")
    link_engine(d)
    _pfile(pid).write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    return data


def delete(pid: str) -> None:
    d = pdir(pid)
    # unlink the engine links first: a recursive delete must never walk into the engine
    for name in ("engine", "engine_modules"):
        at = d / name
        if at.is_symlink():
            at.unlink()
    shutil.rmtree(d)


def safe_path(root: Path, rel: str, allow_links: bool = False) -> Path:
    """`rel` inside `root`, or 404. With `allow_links`, the engine links may be followed (the engine and its modules)."""
    if not rel or "\x00" in rel or rel.startswith("/") or "\\" in rel:
        raise HTTPException(404)
    parts = Path(rel).parts
    if any(p in ("..", "") for p in parts) or (parts and parts[0] == ".studio"):
        raise HTTPException(404)
    target = (root / rel)
    real = target.resolve()
    roots = [root.resolve()]
    if allow_links:
        roots += [config.ENGINE_DIR.resolve(), (config.ENGINE_DIR / "node_modules").resolve()]
    if not any(real == r or r in real.parents for r in roots):
        raise HTTPException(404)
    if not allow_links and parts and parts[0] in ("engine", "engine_modules"):
        raise HTTPException(404)
    if not real.is_file():
        raise HTTPException(404)
    return real
