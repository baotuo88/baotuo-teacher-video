"""Calls into the Frametell engine (node tools) and script.js reading/writing."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Callable

from . import config

JS = Path(__file__).resolve().parent / "js"


class ToolError(RuntimeError):
    pass


async def run(cmd: list[str], cwd: Path, timeout: float = 900, env: dict | None = None,
              on_line: Callable[[str], None] | None = None) -> tuple[int, str, str]:
    """Run a command in its own process group; stream lines to `on_line`; kill the group on timeout or cancel."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd), env=env or config.tool_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    out: list[str] = []
    err: list[str] = []

    async def pump(stream: asyncio.StreamReader, buf: list[str]) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            s = line.decode("utf-8", "replace").rstrip("\n")
            buf.append(s)
            if on_line and s.strip():
                on_line(s)

    def kill() -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    try:
        await asyncio.wait_for(asyncio.gather(pump(proc.stdout, out), pump(proc.stderr, err), proc.wait()), timeout)
    except asyncio.TimeoutError:
        kill()
        await proc.wait()
        raise ToolError(f"超时（{int(timeout)}s）：{' '.join(Path(c).name for c in cmd[:2])}")
    except asyncio.CancelledError:
        kill()
        raise
    return proc.returncode or 0, "\n".join(out), "\n".join(err)


def tool_path(name: str) -> str:
    return str(config.ENGINE_DIR / "tools" / name)


async def node(d: Path, tool: str, args: list[str] | None = None, timeout: float = 900, webgl: bool = False,
               on_line: Callable[[str], None] | None = None, env_extra: dict | None = None) -> tuple[int, str, str]:
    env = config.tool_env(webgl)
    if env_extra:
        env.update(env_extra)
    path = tool if tool.startswith("/") else tool_path(tool)
    return await run([config.NODE, path, *(args or [])], d, timeout, env, on_line)


def _last_json(text: str):
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


# ── script.js ──────────────────────────────────────────────────────

async def read_script(d: Path) -> dict:
    if not (d / "script.js").exists():
        return {"META": {}, "PAGES": []}
    code, out, err = await run([config.NODE, str(JS / "read-script.mjs"), str(d)], d, 30)
    data = _last_json(out)
    if not isinstance(data, dict):
        raise ToolError(f"读取 script.js 失败：{(err or out)[:400]}")
    if data.get("error"):
        raise ToolError(f"script.js 有语法错误：{data['error']}")
    return data


SCRIPT_HEADER = """/* Narration script — the single source of truth for this film (written by baotuo-teacher-video).
 * META: style, voice, pacing, components. PAGES: each page's subtitle lines (cues); pages/<id>.js is timed to them.
 * A cue is a string, or { t: 'line', hold: 0.6 } to keep the picture going a little after the line. */
"""


def write_script(d: Path, meta: dict, pages: list) -> None:
    body = (
        SCRIPT_HEADER
        + "(function (root) {\n"
        + "  const META = " + json.dumps(meta, ensure_ascii=False, indent=2).replace("\n", "\n  ") + ";\n"
        + "  const PAGES = [\n"
        + "".join("    " + json.dumps(p, ensure_ascii=False) + ",\n" for p in pages)
        + "  ];\n"
        + "  root.SCRIPT = { META, PAGES };\n"
        + "})(typeof window !== 'undefined' ? window : globalThis);\n"
    )
    f = d / "script.js"
    # same text → leave the file (and its mtime) alone: a fresh mtime would mark the film as changed
    if f.exists() and f.read_text("utf-8") == body:
        return
    tmp = d / "script.js.tmp"
    tmp.write_text(body, "utf-8")
    tmp.replace(f)


def cue_text(c) -> str:
    return c if isinstance(c, str) else (c.get("t") or "")


# ── engine tools ───────────────────────────────────────────────────

async def timeline(d: Path) -> dict:
    """Real page timeline (follows voice.js when present): { voiced, duration, pages: [{id,start,end,speechEnd,cues}] }"""
    code, out, err = await node(d, "pages.mjs", ["--json"], 60)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise ToolError(f"时间轴计算失败：{(err or out)[-600:]}")


async def script_tool(d: Path) -> str:
    """out/口播脚本.md + out/字幕.srt; returns its summary line."""
    code, out, err = await node(d, "script.mjs", [], 60)
    if code:
        raise ToolError(f"script.mjs 失败：{(err or out)[-600:]}")
    return out.strip().splitlines()[-1] if out.strip() else ""


async def storyboard_lint(d: Path) -> list[dict]:
    # numbers on screen are grounded in materials/ and script.js (the tool's defaults, relative to the project) + `say`
    code, out, err = await node(d, "storyboard-lint.mjs", ["storyboard.json", "--json"], 60)
    if code == 2:
        raise ToolError(f"分镜读不出来：{(err or out)[-400:]}")
    data = _last_json(out)
    return data if isinstance(data, list) else []


async def check_page(d: Path, pid: str, sheet: str, times: list[float], webgl: bool = False,
                     determinism: bool = False) -> dict:
    """lint + contact sheet of one page in one browser → { issues, sheet } | { issues, crash }"""
    args = ["--only", pid, "--sheet", sheet, "--lint-ms", "90000"]
    if determinism:
        args.append("--determinism")
    args += [f"{t:.2f}" for t in times]
    code, out, err = await node(d, "check.mjs", args, 300, webgl=webgl)
    data = _last_json(out)
    if not isinstance(data, dict):
        return {"issues": [], "crash": f"检查失败：{(err or out)[-1500:]}"}
    if data.get("crash") or not data.get("sheet"):
        data["crash"] = "\n".join(x for x in [data.get("crash") or "没有生成截图", err[-1500:] if err else ""] if x)
    return data


async def lint_all(d: Path, webgl: bool = False, determinism: bool = False) -> list[dict]:
    args = ["--json"] + (["--determinism"] if determinism else [])
    code, out, err = await node(d, "lint.mjs", args, 900, webgl=webgl)
    data = _last_json(out)
    if not isinstance(data, list):
        raise ToolError(f"lint 失败：{(err or out)[-800:]}")
    return data


async def snap(d: Path, name: str, times: list[float], only: list[str] | None = None, webgl: bool = False,
               tile: int = 480) -> Path:
    args = (["--only", ",".join(only)] if only else []) + ["--sheet", name] + [f"{t:.2f}" for t in times]
    code, out, err = await node(d, "snap.mjs", args, 600, webgl=webgl, env_extra={"SNAP_TILE": str(tile)})
    f = d / "out" / "snap" / f"{name}.jpg"
    if code or not f.exists():
        raise ToolError(f"截图失败：{(err or out)[-800:]}")
    return f


async def logos(d: Path, names: list[str]) -> str:
    code, out, err = await node(d, "logos.mjs", names, 120)
    if code:
        raise ToolError(f"logo 生成失败：{(err or out)[-400:]}")
    return out


async def syntax_check(f: Path) -> str | None:
    code, out, err = await run([config.NODE, "--check", str(f)], f.parent, 30)
    return None if code == 0 else (err or out).strip()[-1200:]
