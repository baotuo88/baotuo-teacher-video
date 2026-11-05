"""Project zips (import) and the job manager."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from app import config, store
from app.jobs import Manager
from conftest import needs_node

SCRIPT = ("(function (root) { root.SCRIPT = { META: { title: 'Sky', style: 'whiteboard', look: 'kept' },"
          " PAGES: [{ id: 'p01', cues: ['天空是蓝的', '因为散射'] }] }; })(globalThis);\n")
VOICE = 'SCRIPT.VOICE = {"speaker": "x", "pages": [[{"t": "天空是蓝的", "f": "audio/a.wav", "d": 1}]]};'


def make_zip(files: dict[str, str | bytes], root: str = "film/") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(root + name, data)
    return buf.getvalue()


def post_zip(client, data: bytes):
    return client.post("/api/projects/import", files={"file": ("film.zip", data, "application/zip")})


def project_ids() -> list[str]:
    return [p["id"] for p in store.list_projects()]


@needs_node
def test_import_rewrites_script_and_voice(client):
    data = make_zip({
        "script.js": SCRIPT,
        "voice.js": VOICE,
        "pages/p01.js": "ENGINE.visual('p01', (P) => {});",
        "index.html": "<script>evil()</script>",
        "../escape.txt": "x",
        ".studio/project.json": json.dumps({"title": "Sky", "style": "no-such-style", "duration": 45}),
    })
    r = post_zip(client, data)
    assert r.status_code == 200, r.text
    p = r.json()
    d = store.pdir(p["id"])
    assert p["style"] == "whiteboard" and p["duration"] == 45
    script = (d / "script.js").read_text()
    assert "written by baotuo-teacher-video" in script and '"look": "kept"' in script
    assert (d / "voice.js").read_text().startswith("/* Narration timing")
    assert "evil" not in (d / "index.html").read_text()
    assert not (config.PROJECTS_DIR / "escape.txt").exists()
    assert (d / "pages" / "p01.js").exists()


@needs_node
def test_import_drops_voice_js_that_is_code(client):
    r = post_zip(client, make_zip({"script.js": SCRIPT, "voice.js": VOICE + " fetch('http://x')"}))
    assert r.status_code == 200
    assert not (store.pdir(r.json()["id"]) / "voice.js").exists()


@needs_node
@pytest.mark.parametrize("script", [
    "this is not javascript (",
    "globalThis.SCRIPT = { META: {}, PAGES: [1, 2] };",
    "globalThis.SCRIPT = { META: [], PAGES: [] };",
])
def test_import_bad_script_leaves_nothing(client, script):
    r = post_zip(client, make_zip({"script.js": script}))
    assert r.status_code == 400
    assert project_ids() == []


def test_import_without_script(client):
    r = post_zip(client, make_zip({"pages/p01.js": "x"}))
    assert r.status_code == 400 and "script.js" in r.json()["detail"]
    assert post_zip(client, b"not a zip").status_code == 400


def test_import_zip_bomb_refused(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 1)
    r = post_zip(client, make_zip({"script.js": SCRIPT, "assets/big.bin": b"\0" * (3 * 1024 * 1024)}))
    assert r.status_code == 400 and "解压后太大" in r.json()["detail"]
    assert project_ids() == []


def test_body_size_limit(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 1)
    r = post_zip(client, b"\0" * (2 * 1024 * 1024))
    assert r.status_code == 413


def test_upload_limits_per_route(client):
    p = store.create({"topic": "t"})
    big = b"a" * (31 * 1024 * 1024)
    r = client.post(f"/api/projects/{p['id']}/assets", files={"file": ("x.png", big, "image/png")})
    assert r.status_code == 413
    assert not list((store.pdir(p["id"]) / "assets").iterdir())


# ── jobs ──

def test_prune_keeps_running_and_newest():
    m = Manager()
    for i in range(150):
        m.jobs[f"j{i}"] = SimpleNamespace(id=f"j{i}", status="done", ended=float(i))
    m.jobs["run"] = SimpleNamespace(id="run", status="running", ended=None)
    m.prune()
    assert len(m.jobs) == m.KEEP_FINISHED + 1
    assert "run" in m.jobs and "j149" in m.jobs and "j0" not in m.jobs


def test_cancel_checks_project(client):
    from app.jobs import manager
    a = store.create({"topic": "a"})
    b = store.create({"topic": "b"})

    async def run():
        started = asyncio.Event()

        async def fn(job):
            started.set()
            await asyncio.sleep(30)

        job = manager.start(a["id"], "check", fn)
        await started.wait()
        return job

    # the job must live in the app's event loop: start it through the client's portal
    with client:
        j = client.portal.call(run)
        assert client.post(f"/api/projects/{b['id']}/jobs/{j.id}/cancel").status_code == 404
        assert client.post(f"/api/projects/{a['id']}/jobs/{j.id}/cancel").json() == {"ok": True}
