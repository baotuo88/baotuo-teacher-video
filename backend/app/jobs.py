"""Background jobs: one at a time per project, logs kept in memory and in .studio/jobs/<id>.log."""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

from . import config, settings, store

KIND_NAMES = {
    "storyboard": "生成分镜", "storyboard_revise": "修改分镜", "script": "写口播", "voice": "配音",
    "pages": "画页面", "page": "画单页", "check": "全片质检", "render": "渲染成片",
    "publish": "发布文案", "auto": "一键成片",
}


class Stop(Exception):
    """A job that ends early on purpose (e.g. waiting for the user): finishes as 'done' with this message."""


class Job:
    def __init__(self, pid: str, kind: str, label: str = "") -> None:
        self.id = store.new_id()
        self.pid = pid
        self.kind = kind
        self.label = label or KIND_NAMES.get(kind, kind)
        self.status = "running"
        self.started = time.time()
        self.ended: float | None = None
        self.lines: list[dict] = []
        self.base = 0          # index of lines[0] since the job started (old lines are dropped)
        self.error = ""
        self.result = ""
        self.progress: dict[str, Any] = {}
        self.task: asyncio.Task | None = None
        self._f = None
        try:
            f = config.PROJECTS_DIR / pid / ".studio" / "jobs" / f"{self.id}.log"
            f.parent.mkdir(parents=True, exist_ok=True)
            self._f = f.open("a", encoding="utf-8")
        except OSError:
            pass

    def log(self, msg: str, level: str = "info") -> None:
        for line in str(msg).splitlines() or [""]:
            item = {"t": time.time(), "level": level, "msg": line}
            self.lines.append(item)
            if self._f:
                self._f.write(f"{time.strftime('%H:%M:%S')} {level[0].upper()} {line}\n")
                self._f.flush()
        if len(self.lines) > 5000:
            del self.lines[:1000]
            self.base += 1000

    def since(self, n: int) -> tuple[list[dict], int]:
        """Lines from absolute index n on, and the index to ask from next."""
        return self.lines[max(0, n - self.base):], self.base + len(self.lines)

    def set_progress(self, **kw: Any) -> None:
        self.progress.update(kw)

    def summary(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "status": self.status,
                "started": self.started, "ended": self.ended, "error": self.error, "result": self.result,
                "progress": self.progress}

    def close(self) -> None:
        if self._f:
            self._f.close()
            self._f = None


class Limiter:
    """A semaphore whose size is read from settings each time (changing settings takes effect without a restart)."""

    def __init__(self, size: Callable[[], int]) -> None:
        self.size = size
        self.n = 0
        self.cond = asyncio.Condition()

    async def __aenter__(self):
        async with self.cond:
            await self.cond.wait_for(lambda: self.n < max(1, int(self.size() or 1)))
            self.n += 1
        return self

    async def __aexit__(self, *exc):
        async with self.cond:
            self.n -= 1
            self.cond.notify_all()


class Manager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.running: dict[str, Job] = {}      # project id → its running job
        self._llm: Limiter | None = None
        self._browser: Limiter | None = None
        self._render: Limiter | None = None

    # created lazily, inside the running loop
    @property
    def llm(self) -> Limiter:
        if not self._llm:
            self._llm = Limiter(lambda: settings.load()["pipeline"]["page_concurrency"])
        return self._llm

    @property
    def browser(self) -> Limiter:
        if not self._browser:
            self._browser = Limiter(lambda: settings.load()["pipeline"]["check_concurrency"])
        return self._browser

    @property
    def render(self) -> Limiter:
        if not self._render:
            self._render = Limiter(lambda: 1)
        return self._render

    def current(self, pid: str) -> Job | None:
        j = self.running.get(pid)
        return j if j and j.status == "running" else None

    def start(self, pid: str, kind: str, fn: Callable[[Job], Awaitable[str | None]], label: str = "") -> Job:
        if self.current(pid):
            raise HTTPException(409, f"这个项目正在{self.current(pid).label}，等它结束或先取消")
        job = Job(pid, kind, label)
        self.jobs[job.id] = job
        self.running[pid] = job
        job.log(f"开始：{job.label}")
        job.task = asyncio.create_task(self._run(job, fn))
        return job

    async def _run(self, job: Job, fn: Callable[[Job], Awaitable[str | None]]) -> None:
        try:
            res = await fn(job)
            job.status = "done"
            job.result = res or ""
            job.log(f"✓ 完成{('：' + res) if res else ''}", "ok")
        except Stop as e:
            job.status = "done"
            job.result = str(e)
            job.log(str(e), "ok")
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.log("已取消", "warn")
        except Exception as e:  # noqa: BLE001 - a job reports its error, never crashes the server
            job.status = "failed"
            job.error = str(e) or e.__class__.__name__
            job.log(f"✗ {job.error}", "error")
            tb = traceback.format_exc()
            if job._f:
                job._f.write(tb)
        finally:
            job.ended = time.time()
            job.close()
            if self.running.get(job.pid) is job:
                self.running.pop(job.pid, None)
            try:
                def keep(d: dict) -> None:
                    d["jobs"] = ([job.summary()] + [x for x in d.get("jobs", []) if x.get("id") != job.id])[:30]
                store.update(job.pid, keep)
            except Exception:  # noqa: BLE001 - the project may have been deleted meanwhile
                pass

    def cancel(self, job_id: str) -> bool:
        j = self.jobs.get(job_id)
        if j and j.status == "running" and j.task:
            j.task.cancel()
            return True
        return False

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def recover(self) -> None:
        """Jobs left 'running' by a restart did not finish."""
        for p in store.list_projects():
            if any(j.get("status") == "running" for j in p.get("jobs", [])):
                def fix(d: dict) -> None:
                    for j in d.get("jobs", []):
                        if j.get("status") == "running":
                            j["status"] = "failed"
                            j["error"] = "服务重启，任务中断"
                    for pg in d.get("pages", {}).values():
                        if pg.get("status") in ("drawing", "checking", "fixing", "queued"):
                            pg["status"] = "failed"
                            pg["note"] = "服务重启，任务中断"
                store.update(p["id"], fix)


manager = Manager()
