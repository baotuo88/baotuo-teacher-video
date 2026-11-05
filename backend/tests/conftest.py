"""Every test runs on its own data dir and a stand-in engine dir: the app reads its paths from env at import."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="btv-test-")).resolve()
os.environ["BTV_DATA_DIR"] = str(_TMP / "data")
os.environ["BTV_ENGINE_DIR"] = str(_TMP / "engine")
os.environ["BTV_PROMPTS_DIR"] = str(_TMP / "prompts")
os.environ["BTV_FRONTEND_DIR"] = str(_TMP / "dist")
for k in list(os.environ):
    if k.startswith(("ANTHROPIC_", "OPENAI_", "LLM_", "TTS_")) or k in ("APP_PASSWORD", "APP_SECRET", "MAX_UPLOAD_MB",
                                                                       "ALLOW_PRIVATE_URLS"):
        del os.environ[k]

# a minimal engine: one style, and node_modules with a file in it (a delete must never reach it)
for sub in ("styles/whiteboard", "node_modules/marker", "lib", "tools"):
    (_TMP / "engine" / sub).mkdir(parents=True, exist_ok=True)
(_TMP / "engine" / "styles" / "whiteboard" / "style.css").write_text("")
(_TMP / "engine" / "lib" / "gauges.js").write_text("")
(_TMP / "engine" / "node_modules" / "marker" / "keep.txt").write_text("keep")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import config, settings  # noqa: E402

HAS_NODE = bool(shutil.which(config.NODE))
needs_node = pytest.mark.skipif(not HAS_NODE, reason="node is not installed")


@pytest.fixture(autouse=True)
def fresh_data():
    """Empty data dir for every test."""
    shutil.rmtree(config.DATA_DIR, ignore_errors=True)
    config.ensure_dirs()
    yield
    shutil.rmtree(config.DATA_DIR, ignore_errors=True)


@pytest.fixture
def client():
    """The API without the lifespan (no background thumbnail warm-up)."""
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture
def saved_settings():
    def save(llm: dict | None = None, tts: dict | None = None) -> dict:
        return settings.save({"llm": llm or {}, "tts": tts or {}})
    return save


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
