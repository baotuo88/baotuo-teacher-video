"""Chat with the configured model. Two wire formats: Anthropic Messages and OpenAI-compatible chat/completions.
Plain text in, text out (no tool calls), so any capable model works. Streams, so long answers don't hit proxy timeouts."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import settings, store


class LLMError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    input: int = 0
    output: int = 0
    stop: str = ""
    truncated: bool = False


@dataclass
class Msg:
    role: str                      # user | assistant
    text: str
    images: list[Path] = field(default_factory=list)


def _b64(p: Path) -> tuple[str, str]:
    data = p.read_bytes()
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return mime, base64.b64encode(data).decode()


def _anthropic_body(cfg: dict, model: str, system: str, msgs: list[Msg], max_tokens: int) -> dict:
    out = []
    for m in msgs:
        if m.images and m.role == "user":
            content: list[dict] = []
            for p in m.images:
                mime, b = _b64(p)
                content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b}})
            content.append({"type": "text", "text": m.text})
            out.append({"role": m.role, "content": content})
        else:
            out.append({"role": m.role, "content": m.text})
    body: dict[str, Any] = {
        "model": model, "max_tokens": max_tokens, "stream": True, "messages": out,
        # the system prompt is long and the same for every page of a film: cache it
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
    }
    if cfg.get("temperature") is not None:
        body["temperature"] = cfg["temperature"]
    return body


def _openai_body(cfg: dict, model: str, system: str, msgs: list[Msg], max_tokens: int, tokens_key: str) -> dict:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in msgs:
        if m.images and m.role == "user":
            content: list[dict] = [{"type": "text", "text": m.text}]
            for p in m.images:
                mime, b = _b64(p)
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b}"}})
            out.append({"role": m.role, "content": content})
        else:
            out.append({"role": m.role, "content": m.text})
    body: dict[str, Any] = {"model": model, "messages": out, "stream": True, tokens_key: max_tokens,
                            "stream_options": {"include_usage": True}}
    if cfg.get("temperature") is not None:
        body["temperature"] = cfg["temperature"]
    return body


async def _sse(resp: httpx.Response):
    async for line in resp.aiter_lines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue


async def _call_anthropic(cfg: dict, model: str, system: str, msgs: list[Msg], max_tokens: int) -> Reply:
    base = cfg["base_url"].rstrip("/")
    url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    if cfg.get("auth") == "bearer":
        headers["authorization"] = f"Bearer {cfg['api_key']}"
    else:
        headers["x-api-key"] = cfg["api_key"]
    body = _anthropic_body(cfg, model, system, msgs, max_tokens)
    text, r = [], Reply("")
    timeout = httpx.Timeout(connect=30, read=float(cfg.get("timeout") or 600), write=60, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                raise _http_error(resp.status_code, (await resp.aread()).decode("utf-8", "replace"))
            async for ev in _sse(resp):
                t = ev.get("type")
                if t == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                    text.append(ev["delta"].get("text", ""))
                elif t == "message_start":
                    u = ev.get("message", {}).get("usage", {})
                    r.input = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
                elif t == "message_delta":
                    r.stop = ev.get("delta", {}).get("stop_reason") or r.stop
                    r.output = ev.get("usage", {}).get("output_tokens") or r.output
                elif t == "error":
                    raise LLMError(f"模型报错：{ev.get('error', {}).get('message', ev)}")
    r.text = "".join(text)
    r.truncated = r.stop == "max_tokens"
    return r


async def _call_openai(cfg: dict, model: str, system: str, msgs: list[Msg], max_tokens: int) -> Reply:
    base = cfg["base_url"].rstrip("/")
    url = base + "/chat/completions"
    headers = {"authorization": f"Bearer {cfg['api_key']}", "content-type": "application/json"}
    timeout = httpx.Timeout(connect=30, read=float(cfg.get("timeout") or 600), write=60, pool=30)
    tokens_key, with_usage = "max_tokens", True
    for _ in range(3):
        body = _openai_body(cfg, model, system, msgs, max_tokens, tokens_key)
        if not with_usage:
            body.pop("stream_options", None)
        text, r = [], Reply("")
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code >= 400:
                    msg = (await resp.aread()).decode("utf-8", "replace")
                    # newer OpenAI models take max_completion_tokens only; some servers reject stream_options
                    if resp.status_code in (400, 422) and tokens_key == "max_tokens" and "max_completion_tokens" in msg:
                        tokens_key = "max_completion_tokens"
                        continue
                    if resp.status_code in (400, 422) and with_usage and "stream_options" in msg:
                        with_usage = False
                        continue
                    raise _http_error(resp.status_code, msg)
                async for ev in _sse(resp):
                    if ev.get("error"):
                        raise LLMError(f"模型报错：{ev['error']}")
                    for ch in ev.get("choices") or []:
                        delta = ch.get("delta") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                        if ch.get("finish_reason"):
                            r.stop = ch["finish_reason"]
                    u = ev.get("usage")
                    if u:
                        r.input = u.get("prompt_tokens") or r.input
                        r.output = u.get("completion_tokens") or r.output
        r.text = "".join(text)
        r.truncated = r.stop == "length"
        return r
    raise LLMError("模型不接受 max_tokens 参数")


class _Retry(LLMError):
    pass


def _http_error(status: int, body: str) -> LLMError:
    short = body[:600]
    if status in (408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529):
        return _Retry(f"HTTP {status}：{short}")
    if status in (401, 403):
        return LLMError(f"模型接口拒绝访问（HTTP {status}），检查设置里的 API Key 和地址：{short}")
    if status == 404:
        return LLMError(f"模型接口地址或模型名不对（HTTP 404）：{short}")
    return LLMError(f"模型接口报错 HTTP {status}：{short}")


async def chat(system: str, msgs: list[Msg], *, review: bool = False, max_tokens: int | None = None,
               pid: str | None = None, log=None) -> Reply:
    cfg = settings.load()["llm"]
    if not cfg.get("api_key"):
        raise LLMError("还没配置大模型：到「设置」里填 API Key")
    model = (cfg.get("review_model") or cfg["model"]) if review else cfg["model"]
    mt = int(max_tokens or cfg.get("max_tokens") or 16000)
    call = _call_anthropic if cfg["provider"] == "anthropic" else _call_openai
    delay = 4.0
    for attempt in range(5):
        try:
            r = await call(cfg, model, system, msgs, mt)
            # some relays now and then end a stream at once with no text: ask again
            if not r.text.strip() and not r.truncated:
                raise _Retry(f"空回答（stop={r.stop or '?'}）")
            break
        except (_Retry, httpx.TransportError) as e:
            if attempt == 4:
                raise LLMError(f"模型接口多次失败：{e}") from e
            if log:
                log(f"模型接口暂时出错，{int(delay)} 秒后重试：{str(e)[:160]}", "warn")
            await asyncio.sleep(delay)
            delay *= 2
    if pid:
        def add(d: dict) -> None:
            u = d.setdefault("usage", {"input": 0, "output": 0, "calls": 0})
            u["input"] = u.get("input", 0) + r.input
            u["output"] = u.get("output", 0) + r.output
            u["calls"] = u.get("calls", 0) + 1
        try:
            store.update(pid, add)
        except Exception:  # noqa: BLE001
            pass
    if not r.text.strip():
        raise LLMError(f"模型返回了空内容（stop={r.stop or '?'}）")
    return r


# ── answers ────────────────────────────────────────────────────────

FENCE = re.compile(r"```([\w+-]*)[^\n]*\n(.*?)(?:\n```|\Z)", re.S)


def code_block(text: str, langs: tuple[str, ...] = ()) -> str | None:
    """The longest fenced block (of one of `langs` when given)."""
    blocks = [(m.group(1).lower(), m.group(2)) for m in FENCE.finditer(text)]
    if langs:
        pick = [b for lang, b in blocks if lang in langs] or [b for lang, b in blocks if not lang]
    else:
        pick = [b for _, b in blocks]
    return max(pick, key=len) if pick else None


def json_block(text: str):
    """The JSON object in a ```json block, or the outermost {...} in the text."""
    src = code_block(text, ("json", "js", "javascript"))
    cands = [src] if src else []
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        cands.append(text[i:j + 1])
    last_err = None
    for c in cands:
        try:
            return json.loads(c)
        except json.JSONDecodeError as e:
            last_err = e
            # tolerate trailing commas, a common slip
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", c))
            except json.JSONDecodeError:
                continue
    raise ValueError(f"回答里没有合法的 JSON：{last_err}")


def outside_blocks(text: str) -> str:
    """The words for the user: what follows the last code block (some models think aloud before it), else all prose."""
    ends = [m.end() for m in FENCE.finditer(text)]
    if ends:
        after = text[ends[-1]:].strip()
        if after:
            return after
    return FENCE.sub("", text).strip()


async def test(cfg_override: dict | None = None) -> dict:
    """A tiny call to check the settings work."""
    s = settings.load()
    if cfg_override:
        s["llm"].update({k: v for k, v in cfg_override.items() if v not in (None, "") and "•" not in str(v)})
    cfg = s["llm"]
    if not cfg.get("api_key"):
        raise LLMError("没有 API Key")
    call = _call_anthropic if cfg["provider"] == "anthropic" else _call_openai
    r = Reply("")
    for _ in range(3):
        r = await call(cfg, cfg["model"], "You answer in one short line.", [Msg("user", "回复：连接成功")], 300)
        if r.text.strip():
            break
    if not r.text.strip():
        raise LLMError("接口通了，但模型连续返回空内容")
    return {"ok": True, "model": cfg["model"], "reply": r.text.strip().split("\n\n")[-1][-200:]}
