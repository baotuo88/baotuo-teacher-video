"""Auth, settings, styles, voices, examples."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request, Response
from fastapi.responses import FileResponse

from . import auth, config, examples, llm, settings, styles, thumbs, voice

router = APIRouter(prefix="/api")


@router.get("/auth/status")
def auth_status(request: Request) -> dict:
    return {"enabled": auth.enabled(), "ok": auth.valid_session(request.cookies.get(auth.COOKIE))}


@router.post("/auth/login")
async def login(response: Response, payload: dict = Body(...)) -> dict:
    if not auth.enabled():
        return {"ok": True}
    if not auth.check_password(str(payload.get("password", ""))):
        await asyncio.sleep(1.0)
        raise HTTPException(401, "密码不对")
    response.set_cookie(auth.COOKIE, auth.new_session(), max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax")
    return {"ok": True}


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.get("/settings")
def get_settings() -> dict:
    return settings.mask(settings.load())


@router.put("/settings")
def put_settings(payload: dict = Body(...)) -> dict:
    return settings.mask(settings.save(payload))


@router.post("/settings/test-llm")
async def test_llm(payload: dict = Body(default={})) -> dict:
    try:
        return await llm.test(payload or None)
    except Exception as e:  # noqa: BLE001 - shown to the user as is
        raise HTTPException(400, str(e)[:600])


@router.post("/settings/test-tts")
async def test_tts(payload: dict = Body(default={})) -> FileResponse:
    """Voice a sample with the given (or saved) settings → the wav."""
    c = dict(settings.load()["tts"])
    c.update({k: v for k, v in (payload or {}).items() if v not in (None, "") and "•" not in str(v) and k != "text"})
    if c.get("provider") == "none":
        raise HTTPException(400, "当前设置为不配音")
    text = str(payload.get("text") or "你好，这是配音试听。我们来聊一个有意思的问题。")[:200]
    key = hashlib.md5(repr(sorted(c.items())).encode() + text.encode()).hexdigest()[:12]
    out = Path(tempfile.gettempdir()) / "btv-samples" / f"{key}.wav"
    if not out.exists():
        try:
            await voice.sample(c, text, out)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e)[:600])
    return FileResponse(out, media_type="audio/wav")


@router.get("/voices")
def voices() -> dict:
    return {"edge": voice.EDGE_VOICES}


@router.get("/styles")
def list_styles() -> list[dict]:
    return styles.all_styles()


@router.get("/examples")
def list_examples() -> list[dict]:
    return examples.listing()


@router.get("/examples/{eid}/thumb")
async def example_thumb(eid: str) -> Response:
    """A sample film's still (the style picker's picture). 404 while it is being made; ask again later."""
    f = thumbs.example_thumb(eid)
    if f.exists():
        return FileResponse(f, media_type="image/jpeg", headers={"cache-control": "public, max-age=604800"})
    examples.source_dir(eid)                       # 404 for an unknown sample
    asyncio.create_task(thumbs.example(eid))
    return Response(status_code=404, headers={"retry-after": "5"})


@router.get("/system")
def system() -> dict:
    ref = config.ENGINE_DIR.parent / "REF"
    return {
        "engine": config.ENGINE_DIR.exists(), "engine_ref": ref.read_text().strip()[:12] if ref.exists() else "",
        "chrome": config.CHROME or "", "ffmpeg": config.FFMPEG, "docker": config.IN_DOCKER,
        "password": auth.enabled(),
    }
