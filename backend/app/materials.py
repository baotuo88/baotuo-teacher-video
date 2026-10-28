"""Material for a film: pasted text, uploaded files (text, Markdown, PDF, images) and web pages / GitHub repos.
Everything is stored as text in <project>/materials/*.md (the storyboard's number check reads that folder too)."""

from __future__ import annotations

import html
import re
import time
from pathlib import Path

import httpx

MAX_CHARS = 120_000
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json", ".py", ".js", ".ts", ".html", ".htm", ".yaml", ".yml", ".rst"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def slug(name: str) -> str:
    s = re.sub(r"[^\w一-鿿.-]+", "-", name).strip("-.")[:60]
    return s or f"material-{int(time.time())}"


def unique(d: Path, name: str) -> Path:
    p = d / name
    i = 2
    while p.exists():
        p = d / f"{Path(name).stem}-{i}{Path(name).suffix}"
        i += 1
    return p


def save_text(d: Path, title: str, text: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    f = unique(d, slug(title) + ".md")
    f.write_text(text[:MAX_CHARS], "utf-8")
    return f


def pdf_text(data: bytes) -> str:
    import io
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n\n".join((p.extract_text() or "") for p in r.pages)


def html_text(src: str) -> tuple[str, str]:
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", src, re.S | re.I)
    if m:
        title = html.unescape(m.group(1)).strip()
    src = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", src)
    src = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|li|tr|section|article)>", "\n", src)
    src = re.sub(r"(?s)<[^>]+>", " ", src)
    text = html.unescape(src)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return title, text.strip()


GH = re.compile(r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$")


async def fetch_url(url: str) -> tuple[str, str]:
    """→ (title, text). A GitHub repository gives its description and README."""
    url = url.strip()
    if not re.match(r"^https?://", url):
        raise ValueError("网址要以 http:// 或 https:// 开头")
    headers = {"user-agent": "Mozilla/5.0 (baotuo-teacher-video)"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as c:
        m = GH.match(url)
        if m:
            owner, repo = m.group(1), m.group(2)
            parts = [f"# {owner}/{repo}", f"Repository: https://github.com/{owner}/{repo}", f"Owner: {owner}"]
            try:
                r = await c.get(f"https://api.github.com/repos/{owner}/{repo}")
                if r.status_code == 200:
                    j = r.json()
                    parts += [f"Name: {j.get('name')}", f"Description: {j.get('description') or ''}",
                              f"Stars: {j.get('stargazers_count')}", f"Language: {j.get('language') or ''}",
                              f"Topics: {', '.join(j.get('topics') or [])}", f"License: {(j.get('license') or {}).get('spdx_id', '')}"]
            except httpx.HTTPError:
                pass
            readme = ""
            for branch in ("HEAD", "main", "master"):
                for fname in ("README.md", "README.zh-CN.md", "readme.md", "README"):
                    try:
                        r = await c.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{fname}")
                    except httpx.HTTPError:
                        continue
                    if r.status_code == 200 and r.text.strip():
                        readme = r.text
                        break
                if readme:
                    break
            if not readme:
                try:
                    r = await c.get(url)
                    readme = html_text(r.text)[1] if r.status_code == 200 else ""
                except httpx.HTTPError:
                    pass
            if not readme:
                raise ValueError("读不到这个仓库的 README（GitHub 访问不通？可以把 README 内容直接粘贴进来）")
            return f"{owner}-{repo}", "\n".join(parts) + "\n\n## README\n\n" + readme
        r = await c.get(url)
        if r.status_code >= 400:
            raise ValueError(f"网页打不开（HTTP {r.status_code}）")
        ctype = r.headers.get("content-type", "")
        if "pdf" in ctype:
            return Path(url).stem or "page", pdf_text(r.content)
        if "html" in ctype or r.text.lstrip().startswith("<"):
            title, text = html_text(r.text)
            return title or url, f"Source: {url}\n\n{text}"
        return Path(url).name or "page", r.text


def file_text(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        return pdf_text(data)
    if ext in (".html", ".htm"):
        return html_text(data.decode("utf-8", "replace"))[1]
    if ext in TEXT_EXT or not ext:
        return data.decode("utf-8", "replace")
    raise ValueError(f"不支持的文件类型 {ext}：可以用文本、Markdown、PDF 或图片")


def read_all(d: Path) -> list[tuple[str, str]]:
    md = d / "materials"
    if not md.exists():
        return []
    return [(f.name, f.read_text("utf-8", "replace")) for f in sorted(md.iterdir()) if f.is_file() and f.suffix == ".md"]


def listing(d: Path) -> list[dict]:
    md = d / "materials"
    if not md.exists():
        return []
    out = []
    for f in sorted(md.iterdir()):
        if f.is_file():
            t = f.read_text("utf-8", "replace")
            out.append({"name": f.name, "chars": len(t), "preview": t[:300]})
    return out
