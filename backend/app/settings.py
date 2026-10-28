"""Global settings (data/settings.json). Env vars fill in LLM credentials when the file has none."""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from . import config

DEFAULTS: dict[str, Any] = {
    "llm": {
        # "anthropic" (Messages API) or "openai" (any OpenAI-compatible chat/completions endpoint)
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key": "",
        # anthropic only: "x-api-key" (official) or "bearer" (many proxies)
        "auth": "x-api-key",
        "model": "claude-sonnet-5",
        # optional cheaper/faster model for the page reviewer and small tasks; empty = same as model
        "review_model": "",
        # the model can look at screenshots: enables the visual reviewer and sends sheets with fix requests
        "vision": True,
        "max_tokens": 16000,
        "temperature": 0.7,
        "timeout": 600,
    },
    "tts": {
        "provider": "edge",          # edge | openai | none
        "voice": "zh-CN-XiaoxiaoNeural",
        "speed": 1.15,
        "openai_base_url": "https://api.siliconflow.cn/v1",
        "openai_api_key": "",
        "openai_model": "FunAudioLLM/CosyVoice2-0.5B",
        "openai_voice": "FunAudioLLM/CosyVoice2-0.5B:anna",
        "concurrency": 3,
    },
    "render": {
        "fps": 30,
        "workers": 3,
    },
    "pipeline": {
        "page_concurrency": 3,     # pages drawn by the model at once
        "check_concurrency": 2,    # browsers checking pages at once
        "page_rounds": 3,          # check → fix rounds per page
        "review": True,            # visual review of every page (needs vision)
    },
    # what the user wants in every film (passed to every stage)
    "preferences": "",
}

SECRET_FIELDS = [("llm", "api_key"), ("tts", "openai_api_key")]


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif k in out or not isinstance(base, dict):
            out[k] = v
    return out


def _from_env(s: dict) -> dict:
    llm = s["llm"]
    if not llm["api_key"]:
        env = os.environ
        if env.get("LLM_API_KEY"):
            llm["api_key"] = env["LLM_API_KEY"]
            llm["provider"] = env.get("LLM_PROVIDER", llm["provider"])
            llm["base_url"] = env.get("LLM_BASE_URL", llm["base_url"])
            llm["model"] = env.get("LLM_MODEL", llm["model"])
            llm["auth"] = env.get("LLM_AUTH", llm["auth"])
        elif env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"):
            llm["provider"] = "anthropic"
            llm["api_key"] = env.get("ANTHROPIC_API_KEY") or env["ANTHROPIC_AUTH_TOKEN"]
            llm["auth"] = "x-api-key" if env.get("ANTHROPIC_API_KEY") else "bearer"
            llm["base_url"] = env.get("ANTHROPIC_BASE_URL", llm["base_url"])
            llm["model"] = (env.get("LLM_MODEL") or env.get("ANTHROPIC_MODEL") or env.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
                            or llm["model"])
        elif env.get("OPENAI_API_KEY"):
            llm["provider"] = "openai"
            llm["api_key"] = env["OPENAI_API_KEY"]
            llm["base_url"] = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            llm["model"] = env.get("LLM_MODEL", "gpt-5")
    if not s["tts"]["openai_api_key"] and os.environ.get("TTS_API_KEY"):
        s["tts"]["openai_api_key"] = os.environ["TTS_API_KEY"]
    return s


def load() -> dict:
    raw: dict = {}
    if config.SETTINGS_FILE.exists():
        try:
            raw = json.loads(config.SETTINGS_FILE.read_text("utf-8"))
        except json.JSONDecodeError:
            raw = {}
    return _from_env(_merge(DEFAULTS, raw))


def save(new: dict) -> dict:
    """Merge `new` over the stored settings. A secret sent back masked (or empty) keeps the stored value."""
    cur = {}
    if config.SETTINGS_FILE.exists():
        try:
            cur = json.loads(config.SETTINGS_FILE.read_text("utf-8"))
        except json.JSONDecodeError:
            cur = {}
    merged = _merge(_merge(DEFAULTS, cur), new)
    for sec, key in SECRET_FIELDS:
        v = (new.get(sec) or {}).get(key)
        if v is None or v == "" or "•" in str(v):
            merged[sec][key] = (cur.get(sec) or {}).get(key, "")
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), "utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(config.SETTINGS_FILE)
    return load()


def mask(s: dict) -> dict:
    out = copy.deepcopy(s)
    for sec, key in SECRET_FIELDS:
        v = out[sec].get(key) or ""
        out[sec][key] = (v[:4] + "••••••" + v[-4:]) if len(v) > 10 else ("••••••" if v else "")
    return out
