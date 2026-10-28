"""Narration: one take per cue → audio/*.wav + voice.js (SCRIPT.VOICE), which the engine's timeline follows.

Backends: edge (Microsoft Edge read-aloud, free, no key), openai (any OpenAI-compatible /audio/speech, e.g. SiliconFlow
CosyVoice, OpenAI), and the user's own takes per cue (uploaded or recorded in the browser). Takes are cached by
backend + voice + speed + text, so changing one line re-voices only that line.

The edge host switch (api.msedgeservices.com, with the legacy host as fallback) follows whiteboard-teacher-video's
scripts/edge_tts_speak.py (MIT, liangdabiao)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import wave
from pathlib import Path

import httpx

from . import config, engine

EDGE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓（女，温暖，讲解首选）"},
    {"id": "zh-CN-YunxiNeural", "name": "云希（男，阳光青年）"},
    {"id": "zh-CN-YunjianNeural", "name": "云健（男，浑厚有力）"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊（女，活泼）"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬（男，新闻播报）"},
    {"id": "zh-CN-YunxiaNeural", "name": "云夏（男，少年）"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北（女，东北话）"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮（女，陕西话）"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻（女，台湾）"},
    {"id": "zh-HK-HiuMaanNeural", "name": "曉曼（女，粤语）"},
    {"id": "en-US-AvaMultilingualNeural", "name": "Ava (female, en-US)"},
    {"id": "en-US-AndrewMultilingualNeural", "name": "Andrew (male, en-US)"},
    {"id": "en-US-EmmaMultilingualNeural", "name": "Emma (female, en-US)"},
    {"id": "en-US-BrianMultilingualNeural", "name": "Brian (male, en-US)"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (female, en-GB)"},
]

# trim silence at both ends (a take's own lead-in delays the voice against the picture), keep ~50 ms
TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
        "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")


class VoiceError(RuntimeError):
    pass


def cfg_for(project: dict, tts: dict) -> dict:
    c = dict(tts)
    c.update({k: v for k, v in (project.get("voice") or {}).items() if v not in (None, "")})
    return c


def signature(pages: list) -> str:
    """What voice.js must match: every cue's text, page by page."""
    texts = [[engine.cue_text(c) for c in p.get("cues", [])] for p in pages]
    return hashlib.sha1(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()[:16]


def take_key(c: dict, text: str) -> str:
    if c["provider"] == "edge":
        who = f"edge|{c['voice']}"
    else:
        who = f"openai|{c['openai_base_url']}|{c['openai_model']}|{c['openai_voice']}"
    return hashlib.md5(f"{who}|{c['speed']}|{text}".encode()).hexdigest()[:12]


def override_key(pid: str, text: str) -> str:
    return hashlib.md5(f"{pid}|{text}".encode()).hexdigest()[:10]


def override_file(d: Path, page_id: str, text: str) -> Path:
    return d / "audio" / f"user-{page_id}-{override_key(page_id, text)}.wav"


def wav_seconds(f: Path) -> float:
    with wave.open(str(f), "rb") as w:
        return w.getnframes() / float(w.getframerate())


async def to_wav(src: Path, dst: Path, trim: bool = True) -> None:
    args = [config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
    if trim:
        args += ["-af", TRIM]
    args += ["-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(dst)]
    code, out, err = await engine.run(args, dst.parent, 180)
    if code or not dst.exists():
        raise VoiceError(f"音频转换失败：{err[-400:]}")


# ── backends ──

_edge = {"hosts": None, "i": 0, "fails": 0}
_edge_lock = asyncio.Lock()


def _edge_hosts() -> list[str]:
    import edge_tts.communicate as communicate
    from edge_tts.constants import TRUSTED_CLIENT_TOKEN
    if _edge["hosts"] is None:
        new = ("wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
               f"?TrustedClientToken={TRUSTED_CLIENT_TOKEN}&Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}")
        _edge["hosts"] = [new, communicate.WSS_URL]
        communicate.WSS_URL = new
    return _edge["hosts"]


async def _edge_once(text: str, voice: str, rate: str, out: Path) -> int:
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, connect_timeout=20, receive_timeout=60)
    n = 0
    with out.open("wb") as f:
        async for chunk in comm.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                f.write(chunk["data"])
                n += len(chunk["data"])
    return n


async def edge_synth(text: str, voice: str, speed: float, out: Path) -> None:
    """edge-tts reads its host from a module global, shared by every take in flight: the host is switched only under a
    lock, and only after repeated failures (the new host refuses a handshake now and then; edge-tts#490)."""
    import edge_tts.communicate as communicate
    hosts = _edge_hosts()
    pct = round((speed - 1) * 100)
    rate = f"{'+' if pct >= 0 else ''}{pct}%"
    errors = []
    for attempt in range(6):
        try:
            # a hard cap: a stalled stream does not always trip edge-tts's own receive timeout
            if await asyncio.wait_for(_edge_once(text, voice, rate, out), 40) > 512:
                _edge["fails"] = 0
                return
            errors.append("空音频")
        except asyncio.TimeoutError:
            errors.append("超时")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e)[:160])
        async with _edge_lock:
            _edge["fails"] += 1
            if _edge["fails"] >= 4:
                _edge["i"] = (_edge["i"] + 1) % len(hosts)
                communicate.WSS_URL = hosts[_edge["i"]]
                _edge["fails"] = 0
        await asyncio.sleep(1.0 + attempt)
    out.unlink(missing_ok=True)
    raise VoiceError("Edge 配音失败：" + " | ".join(errors[-3:]))


async def openai_synth(text: str, c: dict, out: Path) -> None:
    if not c.get("openai_api_key"):
        raise VoiceError("没有填配音接口的 API Key（设置 → 配音）")
    url = c["openai_base_url"].rstrip("/") + "/audio/speech"
    body = {"model": c["openai_model"], "input": text, "voice": c["openai_voice"], "response_format": "mp3",
            "speed": float(c.get("speed") or 1.0)}
    last = ""
    for attempt in range(4):
        try:
            async with httpx.AsyncClient(timeout=120) as cl:
                r = await cl.post(url, json=body, headers={"authorization": f"Bearer {c['openai_api_key']}"})
            if r.status_code == 200 and len(r.content) > 512:
                out.write_bytes(r.content)
                return
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except httpx.HTTPError as e:
            last = str(e)
        await asyncio.sleep(2 * (attempt + 1))
    raise VoiceError(f"配音接口失败：{last}")


async def synth(text: str, c: dict, wav: Path) -> None:
    tmp = wav.with_suffix(".src.mp3")
    if c["provider"] == "edge":
        await edge_synth(text, c["voice"], float(c.get("speed") or 1.0), tmp)
    elif c["provider"] == "openai":
        await openai_synth(text, c, tmp)
    else:
        raise VoiceError(f"未知配音方式 {c['provider']}")
    try:
        await to_wav(tmp, wav)
    finally:
        tmp.unlink(missing_ok=True)


def speak_text(text: str) -> str:
    """What is said: the cue without markup a voice would read out (subtitle-only marks)."""
    return re.sub(r"[{}*`]", "", text).strip()


# ── whole film ──

async def voice_film(d: Path, pid: str, project: dict, tts: dict, log, progress) -> dict:
    """Voice every cue (cached), write voice.js. → { made, reused, user, seconds }"""
    c = cfg_for(project, tts)
    data = await engine.read_script(d)
    pages = data["PAGES"]
    cues = [(pi, ci, p["id"], engine.cue_text(cue)) for pi, p in enumerate(pages) for ci, cue in enumerate(p.get("cues", []))]
    if not cues:
        raise VoiceError("口播还没写：先完成「口播」一步")
    (d / "audio").mkdir(exist_ok=True)
    result: dict[tuple[int, int], dict] = {}
    counts = {"made": 0, "reused": 0, "user": 0}
    sem = asyncio.Semaphore(max(1, int(c.get("concurrency") or 4)))
    done = 0

    async def one(pi: int, ci: int, page_id: str, text: str) -> None:
        nonlocal done
        own = override_file(d, page_id, text)
        if own.exists():
            f, kind = own, "user"
        else:
            f = d / "audio" / f"{page_id}-c{ci:02d}-{take_key(c, text)}.wav"
            if f.exists() and f.stat().st_size > 1024:
                kind = "reused"
            else:
                async with sem:
                    await synth(speak_text(text) or text, c, f)
                kind = "made"
                log(f"  {page_id} c{ci:02d} {wav_seconds(f):.1f}s  {text[:24]}")
        counts[kind] += 1
        result[(pi, ci)] = {"t": text, "f": f"audio/{f.name}", "d": round(wav_seconds(f), 3), "o": 0}
        done += 1
        progress(done=done, total=len(cues))

    await asyncio.gather(*(one(*x) for x in cues))
    voice_pages = [[result[(pi, ci)] for ci in range(len(p.get("cues", [])))] for pi, p in enumerate(pages)]
    speaker = c["voice"] if c["provider"] == "edge" else c.get("openai_voice", "")
    (d / "voice.js").write_text(
        "/* Narration timing, one take per cue (written by baotuo-teacher-video; do not edit by hand). */\n"
        "SCRIPT.VOICE = " + json.dumps({"speaker": speaker, "provider": c["provider"], "pages": voice_pages},
                                       ensure_ascii=False) + ";\n", "utf-8")
    # drop takes nothing points at any more (the user's own takes stay)
    used = {x["f"].split("/", 1)[1] for pg in voice_pages for x in pg}
    for f in (d / "audio").glob("*.wav"):
        if f.name not in used and not f.name.startswith("user-"):
            f.unlink(missing_ok=True)
    counts["seconds"] = round(sum(x["d"] for pg in voice_pages for x in pg), 1)
    counts["speaker"] = speaker
    return counts


async def sample(c: dict, text: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    await synth(text, c, out)
    return out
