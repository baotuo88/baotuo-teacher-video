"""Projects: list, create, read, update, delete, export / import; materials and the user's pictures and music."""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from . import auth, config, engine, examples, film, materials, store, styles, thumbs, voice, zh
from .jobs import manager

router = APIRouter(prefix="/api/projects")

EDITABLE = {"title", "topic", "audience", "notes", "duration", "style", "lang", "kind", "repo", "voice", "cover"}


def _card(p: dict) -> dict:
    d = config.PROJECTS_DIR / p["id"]
    tv = p.get("thumbs") or {}
    first = p.get("cover") if p.get("cover") in tv else (sorted(tv)[0] if tv else "")
    thumb = f"out/thumbs/{first}.jpg?v={tv[first]}" if first else ""
    films = [f for f in film.outputs(d) if f["name"].endswith(".mp4")] if d.exists() else []
    job = manager.current(p["id"])
    return {"id": p["id"], "title": p["title"], "style": p["style"], "style_name": styles.name(p["style"]),
            "duration": p["duration"], "updated": p["updated"], "created": p["created"], "thumb": thumb,
            "pages": len(p.get("pages") or {}), "film": films[0]["name"] if films else "",
            "storyboard_status": p.get("storyboard_status"), "job": job.summary() if job else None}


@router.get("")
def list_projects() -> list[dict]:
    return [_card(p) for p in store.list_projects()]


@router.post("")
async def create(payload: dict = Body(...)) -> dict:
    if payload.get("example"):
        p = examples.create_from(str(payload["example"]))
        d = store.pdir(p["id"])
        await film.apply_meta(d, p["id"])
        thumbs.kick_film(d, p["id"])
        return p
    style = payload.get("style") or "whiteboard"
    if not styles.exists(style):
        raise HTTPException(400, f"没有这个风格：{style}")
    fields = {k: payload[k] for k in EDITABLE if k in payload}
    fields["duration"] = max(20, min(600, int(payload.get("duration") or 90)))
    p = store.create(fields)
    d = store.pdir(p["id"])
    # material that came with the request
    if (payload.get("text") or "").strip():
        materials.save_text(d / "materials", payload.get("text_title") or "素材", payload["text"])
    url = (payload.get("url") or "").strip()
    if url:
        try:
            title, text = await materials.fetch_url(url)
            materials.save_text(d / "materials", title, text)
        except Exception as e:  # noqa: BLE001 - the project stays; the user can add the material again
            store.update(p["id"], {"notes": (p.get("notes") or "") + f"\n（素材网址没能读取：{e}）"})
    return store.get(p["id"])


@router.post("/import")
async def import_zip(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(400, "不是 zip 文件")
    names = z.namelist()
    root = ""
    if "script.js" not in names:
        tops = {n.split("/", 1)[0] for n in names if "/" in n}
        root = next((t + "/" for t in tops if f"{t}/script.js" in names), "")
        if not root:
            raise HTTPException(400, "zip 里没有 script.js")
    pj = {}
    if f"{root}.studio/project.json" in names:
        try:
            pj = json.loads(z.read(f"{root}.studio/project.json"))
        except json.JSONDecodeError:
            pj = {}
    p = store.create({k: pj[k] for k in store.DEFAULT_PROJECT if k in pj and k not in ("id", "jobs", "created", "updated")})
    d = store.pdir(p["id"])
    for n in names:
        rel = n[len(root):]
        if not rel or n.endswith("/") or rel.startswith((".studio/", "engine", "out/")):
            continue
        if ".." in Path(rel).parts or rel.startswith("/"):
            continue
        target = d / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(n))
    store.update(p["id"], lambda x: x.update({"jobs": [], "id": p["id"]}))
    await film.apply_meta(d, p["id"])
    return store.get(p["id"])


@router.get("/{pid}")
async def get_project(pid: str) -> dict:
    d = store.pdir(pid)
    store.link_engine(d)
    p = store.get(pid)
    try:
        data = await engine.read_script(d)
    except engine.ToolError:
        data = {"META": {}, "PAGES": []}
    job = manager.current(pid)
    return {
        **p,
        # the checkers write English for the model; the interface shows `zh`
        "storyboard_issues": zh.add(p.get("storyboard_issues"), "storyboard"),
        "pages": {k: {**v, "issues": zh.add(v.get("issues"), "page")} for k, v in (p.get("pages") or {}).items()},
        "film_check": {**p["film_check"], "issues": zh.add(p["film_check"].get("issues"), "page")} if p.get("film_check") else None,
        "style_name": styles.name(p["style"]),
        "webgl": styles.is_webgl(p["style"]),
        "overview": await film.overview(d, p),
        "storyboard": film.read_storyboard(d),
        "script": data,
        "materials": materials.listing(d),
        "assets_files": sorted(f.name for f in (d / "assets").glob("*") if f.is_file()) if (d / "assets").exists() else [],
        "outputs": film.outputs(d),
        "job": job.summary() if job else None,
        "tts": film.tts_cfg(p) | {"openai_api_key": ""},
        "preview": f"/preview/{pid}/{auth.preview_token(pid)}/index.html",
    }


@router.patch("/{pid}")
async def patch(pid: str, payload: dict = Body(...)) -> dict:
    d = store.pdir(pid)
    fields = {k: v for k, v in payload.items() if k in EDITABLE}
    if "style" in fields and not styles.exists(fields["style"]):
        raise HTTPException(400, "没有这个风格")
    if "duration" in fields:
        fields["duration"] = max(20, min(600, int(fields["duration"] or 90)))
    if "voice" in fields:
        fields["voice"] = {k: v for k, v in (fields["voice"] or {}).items()
                           if k in ("provider", "voice", "speed", "openai_model", "openai_voice")}
    store.update(pid, fields)
    if (d / "script.js").exists() and ({"style", "lang", "title", "voice"} & fields.keys()):
        await film.apply_meta(d, pid, title=fields.get("title"))
    if "cover" in fields:
        cover = d / "cover.json"
        if fields["cover"]:
            cover.write_text(json.dumps({"page": fields["cover"]}), "utf-8")
        else:
            cover.unlink(missing_ok=True)
    return store.get(pid)


@router.delete("/{pid}")
def delete(pid: str) -> dict:
    if manager.current(pid):
        raise HTTPException(409, "项目有任务在跑，先取消")
    store.delete(pid)
    return {"ok": True}


@router.get("/{pid}/export")
def export(pid: str) -> FileResponse:
    d = store.pdir(pid)
    p = store.get(pid)
    tmp = Path(tempfile.mkstemp(suffix=".zip")[1])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in d.rglob("*"):
            rel = f.relative_to(d)
            top = rel.parts[0]
            if top in ("engine", "engine_modules") or (top == "out" and len(rel.parts) > 1 and rel.parts[1] in ("chunks", "subs", "sound", "snap")):
                continue
            if top == ".studio" and rel.as_posix() != ".studio/project.json":
                continue
            if f.is_file() and not f.is_symlink():
                z.write(f, rel.as_posix())
    name = film.file_name(p["title"]) + ".zip"
    return FileResponse(tmp, filename=name, media_type="application/zip", background=BackgroundTask(tmp.unlink))


# ── materials ──

@router.post("/{pid}/materials/text")
def add_text(pid: str, payload: dict = Body(...)) -> dict:
    d = store.pdir(pid)
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "内容是空的")
    f = materials.save_text(d / "materials", payload.get("title") or "素材", text)
    return {"name": f.name}


@router.post("/{pid}/materials/url")
async def add_url(pid: str, payload: dict = Body(...)) -> dict:
    d = store.pdir(pid)
    try:
        title, text = await materials.fetch_url(str(payload.get("url") or ""))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"读取失败：{e}")
    f = materials.save_text(d / "materials", title, text)
    return {"name": f.name, "chars": len(text)}


@router.post("/{pid}/materials/file")
async def add_file(pid: str, file: UploadFile = File(...)) -> dict:
    d = store.pdir(pid)
    data = await file.read()
    name = file.filename or "file"
    if Path(name).suffix.lower() in materials.IMAGE_EXT:
        return await _save_asset(d, pid, name, data, "")
    try:
        text = materials.file_text(name, data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    if not text.strip():
        raise HTTPException(400, "没有读出文字（扫描版 PDF？）")
    f = materials.save_text(d / "materials", Path(name).stem, text)
    return {"name": f.name, "chars": len(text)}


@router.put("/{pid}/materials/{name}")
def edit_material(pid: str, name: str, payload: dict = Body(...)) -> dict:
    d = store.pdir(pid)
    f = store.safe_path(d / "materials", name)
    f.write_text(str(payload.get("text") or ""), "utf-8")
    return {"ok": True}


@router.get("/{pid}/materials/{name}")
def read_material(pid: str, name: str) -> dict:
    d = store.pdir(pid)
    return {"name": name, "text": store.safe_path(d / "materials", name).read_text("utf-8", "replace")}


@router.delete("/{pid}/materials/{name}")
def del_material(pid: str, name: str) -> dict:
    d = store.pdir(pid)
    store.safe_path(d / "materials", name).unlink()
    return {"ok": True}


# ── the user's pictures and background music ──

def _asset_name(name: str) -> str:
    stem = re.sub(r"[^\w-]+", "-", Path(name).stem).strip("-")[:40] or "image"
    return stem + Path(name).suffix.lower()


async def _save_asset(d: Path, pid: str, name: str, data: bytes, desc: str) -> dict:
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(400, "图片太大（> 30MB）")
    ext = Path(name).suffix.lower()
    if ext not in materials.IMAGE_EXT:
        raise HTTPException(400, "只支持 png / jpg / webp / gif")
    (d / "assets").mkdir(exist_ok=True)
    f = materials.unique(d / "assets", _asset_name(name))
    f.write_bytes(data)
    store.update(pid, lambda x: x.setdefault("assets", {}).__setitem__(f.name, desc))
    return {"name": f.name, "asset": True}


@router.post("/{pid}/assets")
async def add_asset(pid: str, file: UploadFile = File(...), desc: str = Form("")) -> dict:
    d = store.pdir(pid)
    return await _save_asset(d, pid, file.filename or "image.png", await file.read(), desc.strip()[:300])


@router.patch("/{pid}/assets/{name}")
def describe_asset(pid: str, name: str, payload: dict = Body(...)) -> dict:
    store.safe_path(store.pdir(pid) / "assets", name)
    store.update(pid, lambda x: x.setdefault("assets", {}).__setitem__(name, str(payload.get("desc") or "")[:300]))
    return {"ok": True}


@router.delete("/{pid}/assets/{name}")
def del_asset(pid: str, name: str) -> dict:
    store.safe_path(store.pdir(pid) / "assets", name).unlink()
    store.update(pid, lambda x: x.setdefault("assets", {}).pop(name, None))
    return {"ok": True}


@router.post("/{pid}/bgm")
async def set_bgm(pid: str, file: UploadFile = File(...), vol: float = Form(-20)) -> dict:
    d = store.pdir(pid)
    (d / "assets").mkdir(exist_ok=True)
    src = d / ".studio" / "uploads" / ("bgm" + Path(file.filename or "a.mp3").suffix.lower())
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(await file.read())
    dst = d / "assets" / "bgm.m4a"
    code, out, err = await engine.run([config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn",
                                       "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "160k", str(dst)], d, 300)
    src.unlink(missing_ok=True)
    if code:
        raise HTTPException(400, f"音乐文件读不了：{err[-300:]}")
    store.update(pid, {"bgm": {"file": "bgm.m4a", "vol": max(-40.0, min(0.0, float(vol))), "name": file.filename}})
    await film.apply_meta(d, pid)
    return {"ok": True}


@router.patch("/{pid}/bgm")
async def bgm_volume(pid: str, payload: dict = Body(...)) -> dict:
    d = store.pdir(pid)
    p = store.get(pid)
    if not p.get("bgm"):
        raise HTTPException(400, "还没有背景音乐")
    b = dict(p["bgm"])
    b["vol"] = max(-40.0, min(0.0, float(payload.get("vol", b.get("vol", -20)))))
    store.update(pid, {"bgm": b})
    await film.apply_meta(d, pid)
    return {"ok": True}


@router.delete("/{pid}/bgm")
async def del_bgm(pid: str) -> dict:
    d = store.pdir(pid)
    (d / "assets" / "bgm.m4a").unlink(missing_ok=True)
    store.update(pid, {"bgm": None})
    await film.apply_meta(d, pid)
    return {"ok": True}
