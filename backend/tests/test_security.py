"""The trust boundaries: secrets stay out of the engine tools, imported JavaScript is read confined, stored keys only
go to the address they were entered for, material is read from the public internet only."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import config, engine, llm, materials, settings
from conftest import needs_node

ESCAPE = """
const p = this.constructor.constructor('return process')();
const r = {};
try { r.read = p.getBuiltinModule('fs').readFileSync(%(secret)r, 'utf8'); } catch (e) { r.read = e.code; }
try { p.getBuiltinModule('fs').writeFileSync(%(pwned)r, 'x'); r.write = 'ok'; } catch (e) { r.write = e.code; }
try { r.cp = String(p.getBuiltinModule('child_process').execSync('id')); } catch (e) { r.cp = e.code; }
r.env = Object.keys(p.env).filter((k) => k !== 'PATH');
globalThis.SCRIPT = { META: r, PAGES: [] };
"""


def test_tool_env_has_no_secrets(monkeypatch):
    for k in ("LLM_API_KEY", "TTS_API_KEY", "APP_PASSWORD", "APP_SECRET", "ANTHROPIC_AUTH_TOKEN", "OPENAI_BASE_URL",
              "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "s3cret")
    monkeypatch.setenv("FRAMETELL_CHROME_ARGS", "--foo")
    env = config.tool_env()
    assert not [k for k, v in env.items() if v == "s3cret"]
    assert env["PATH"] and "--foo" in env["FRAMETELL_CHROME_ARGS"]


@needs_node
def test_read_script_is_confined(tmp_path, monkeypatch):
    if not engine.permission_flag():
        pytest.skip("this node has no permission model")
    monkeypatch.setenv("LLM_API_KEY", "sk-should-not-leak")
    secret = tmp_path / "secret.txt"
    secret.write_text("the key")
    d = tmp_path / "ep"
    d.mkdir()
    (d / "script.js").write_text(ESCAPE % {"secret": str(secret), "pwned": str(tmp_path / "pwned")})
    meta = asyncio.run(engine.read_script(d))["META"]
    assert meta["read"] == "ERR_ACCESS_DENIED"
    assert meta["write"] == "ERR_ACCESS_DENIED"
    assert meta["cp"] == "ERR_ACCESS_DENIED"
    assert "LLM_API_KEY" not in meta["env"] and len(meta["env"]) <= 1   # macOS adds __CF_USER_TEXT_ENCODING itself
    assert not (tmp_path / "pwned").exists()


@needs_node
def test_read_script_cached_by_file(tmp_path, monkeypatch):
    (tmp_path / "script.js").write_text("globalThis.SCRIPT = { META: { n: 1 }, PAGES: [] };")
    calls = []
    real = engine.run

    async def counting(*a, **kw):
        calls.append(1)
        return await real(*a, **kw)

    monkeypatch.setattr(engine, "run", counting)
    first = asyncio.run(engine.read_script(tmp_path))
    first["META"]["n"] = 99                       # a caller's change must not leak into the cache
    assert asyncio.run(engine.read_script(tmp_path))["META"]["n"] == 1
    assert len(calls) == 1
    engine.write_script(tmp_path, {"n": 2}, [])
    assert asyncio.run(engine.read_script(tmp_path))["META"]["n"] == 2
    assert len(calls) == 2


# ── keys and addresses ──

def test_masked_key_cannot_move_to_new_address(saved_settings):
    saved_settings({"api_key": "sk-real-key-0001", "base_url": "https://api.anthropic.com"})
    with pytest.raises(settings.KeyNeeded):
        settings.save({"llm": {"api_key": "sk-r••••••0001", "base_url": "https://evil.example"}})
    with pytest.raises(settings.KeyNeeded):
        settings.save({"llm": {"base_url": "https://evil.example"}})
    assert settings.load()["llm"]["base_url"] == "https://api.anthropic.com"


def test_key_kept_when_address_unchanged_or_key_retyped(saved_settings):
    saved_settings({"api_key": "sk-real-key-0001", "base_url": "https://api.anthropic.com"})
    settings.save({"llm": {"api_key": "sk-r••••••0001", "base_url": "https://api.anthropic.com/", "model": "m2"}})
    assert settings.load()["llm"]["api_key"] == "sk-real-key-0001"
    settings.save({"llm": {"api_key": "sk-new-key-0002", "base_url": "https://other.example"}})
    assert settings.load()["llm"]["api_key"] == "sk-new-key-0002"


def test_key_from_env_is_bound_too(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-env-key-0003")
    monkeypatch.setenv("LLM_BASE_URL", "https://relay.example/v1")
    with pytest.raises(settings.KeyNeeded):
        settings.save({"llm": {"base_url": "https://evil.example"}})


def test_tts_key_bound(saved_settings):
    saved_settings(tts={"openai_api_key": "sk-tts-key-0004", "openai_base_url": "https://api.siliconflow.cn/v1"})
    with pytest.raises(settings.KeyNeeded):
        settings.save({"tts": {"openai_api_key": "", "openai_base_url": "https://evil.example"}})


def test_llm_test_does_not_send_stored_key_elsewhere(saved_settings, monkeypatch):
    saved_settings({"api_key": "sk-real-key-0001", "base_url": "https://api.anthropic.com"})

    async def no_call(*a, **kw):
        raise AssertionError("must not call the model")

    monkeypatch.setattr(llm, "_call_anthropic", no_call)
    with pytest.raises(settings.KeyNeeded):
        asyncio.run(llm.test({"base_url": "https://evil.example", "api_key": "sk-r••••••0001"}))


def test_settings_routes_answer_400(client, saved_settings):
    saved_settings({"api_key": "sk-real-key-0001"}, {"openai_api_key": "sk-tts-key-0004"})
    r = client.put("/api/settings", json={"llm": {"base_url": "https://evil.example"}})
    assert r.status_code == 400 and "API Key" in r.json()["detail"]
    r = client.post("/api/settings/test-llm", json={"base_url": "https://evil.example"})
    assert r.status_code == 400
    r = client.post("/api/settings/test-tts", json={"provider": "openai", "openai_base_url": "https://evil.example"})
    assert r.status_code == 400
    assert client.get("/api/settings").json()["llm"]["api_key"] == "sk-r••••••0001"


# ── material from the web ──

@pytest.fixture
def dns(monkeypatch):
    table = {"public.example": ["93.184.216.34"], "internal.example": ["10.0.0.5"], "meta.example": ["169.254.169.254"],
             "v6local.example": ["::1"], "mapped.example": ["::ffff:127.0.0.1"]}

    async def resolve(host):
        return table.get(host) or [host]

    monkeypatch.setattr(materials, "_resolve", resolve)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/api/settings", "http://internal.example/", "http://meta.example/",
                                 "http://v6local.example/", "http://mapped.example/", "http://[::1]/", "http://0.0.0.0/",
                                 "ftp://public.example/", "http://192.168.1.1/"])
def test_check_host_blocks(dns, url):
    with pytest.raises(materials.Blocked):
        asyncio.run(materials.check_host(url))


def test_check_host_allows_public_and_opt_in(dns, monkeypatch):
    asyncio.run(materials.check_host("https://public.example/page"))
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
    asyncio.run(materials.check_host("http://internal.example/"))


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_redirect_to_internal_is_blocked(dns):
    def handler(req):
        if req.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return httpx.Response(200, text="internal data")

    async def go():
        async with _client(handler) as c:
            return await materials._get(c, "http://public.example/")

    with pytest.raises(materials.Blocked):
        asyncio.run(go())


def test_fetch_follows_public_redirects_and_caps_size(dns, monkeypatch):
    def handler(req):
        if req.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text="<title>T</title>天空" * 50)

    async def go(url):
        async with _client(handler) as c:
            return await materials._get(c, url)

    page = asyncio.run(go("http://public.example/a"))
    assert page.status == 200 and "天空" in page.text
    monkeypatch.setattr(materials, "MAX_FETCH", 100)
    with pytest.raises(ValueError, match="太大"):
        asyncio.run(go("http://public.example/b"))


def test_material_url_route_refuses_internal(client, dns):
    from app import store
    p = store.create({"topic": "t"})
    r = client.post(f"/api/projects/{p['id']}/materials/url", json={"url": "http://127.0.0.1:8000/api/settings"})
    assert r.status_code == 400 and "内网" in r.json()["detail"]
