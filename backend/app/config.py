"""Paths and process environment. Everything is configurable through env vars so the same code runs in Docker and locally."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v).resolve() if v else default


DATA_DIR = _path("BTV_DATA_DIR", ROOT / "data")
PROJECTS_DIR = DATA_DIR / "projects"
SETTINGS_FILE = DATA_DIR / "settings.json"
SECRET_FILE = DATA_DIR / ".secret"

ENGINE_DIR = _path("BTV_ENGINE_DIR", ROOT / "vendor" / "engine")
PROMPTS_DIR = _path("BTV_PROMPTS_DIR", ROOT / "vendor" / "prompts")
FRONTEND_DIR = _path("BTV_FRONTEND_DIR", ROOT / "frontend" / "dist")
# sample films shipped with the app (backend/examples/<id>/script.js + pages/)
EXAMPLES_DIR = _path("BTV_EXAMPLES_DIR", ROOT / "backend" / "examples")

NODE = os.environ.get("NODE_BIN") or shutil.which("node") or "node"
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")


def _find_chrome() -> str | None:
    cands = [
        os.environ.get("CHROME_PATH"),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    return next((c for c in cands if c and Path(c).exists()), None)


CHROME = _find_chrome()
FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
IN_DOCKER = Path("/.dockerenv").exists() or os.environ.get("BTV_IN_DOCKER") == "1"


def tool_env(webgl: bool = False) -> dict[str, str]:
    """Environment for engine tools (node) and the Chrome they drive."""
    env = os.environ.copy()
    if CHROME:
        env["CHROME_PATH"] = CHROME
    env["FFMPEG_PATH"] = FFMPEG
    args = env.get("FRAMETELL_CHROME_ARGS", "").split()
    if IN_DOCKER:
        args += ["--no-sandbox", "--disable-dev-shm-usage"]
    if webgl and IN_DOCKER:
        # no GPU in the container: WebGL through SwiftShader (slow but correct). Later flags win over the engine's Metal ones.
        args += ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
    env["FRAMETELL_CHROME_ARGS"] = " ".join(dict.fromkeys(args))
    return env


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
