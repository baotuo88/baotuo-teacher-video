"""Material for a film: pasted text, uploaded files (text, Markdown, PDF, images) and web pages / GitHub repos.
Everything is stored as text in <project>/materials/*.md (the storyboard's number check reads that folder too)."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import config

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
MAX_FETCH = 20 * 1024 * 1024
MAX_REDIRECTS = 5


class Blocked(ValueError):
    pass


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


async def check_host(url: str) -> None:
    """Material is read from the public internet only: not from this machine, its network or a cloud metadata address
    (anyone who can make a film could otherwise read those through the server). ALLOW_PRIVATE_URLS lifts this."""
    u = httpx.URL(url)
    if u.scheme not in ("http", "https") or not u.host:
        raise Blocked("网址要以 http:// 或 https:// 开头")
    if config.ALLOW_PRIVATE_URLS:
        return
    try:
        addrs = await _resolve(u.host)
    except OSError:
        raise ValueError(f"找不到这个网站：{u.host}")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise Blocked(f"不读取内网或本机地址（{u.host} → {ip}）；确实需要请设置 ALLOW_PRIVATE_URLS=1")


@dataclass
class Page:
    status: int
    ctype: str
    content: bytes
    text: str


async def _get(c: httpx.AsyncClient, url: str) -> Page:
    """GET with every redirect hop checked, the body capped at MAX_FETCH."""
    for _ in range(MAX_REDIRECTS + 1):
        await check_host(url)
        async with c.stream("GET", url) as r:
            if r.is_redirect and r.headers.get("location"):
                url = str(r.url.join(r.headers["location"]))
                continue
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_FETCH:
                    raise ValueError(f"网页太大（超过 {MAX_FETCH // 1024 // 1024}MB）")
            data = bytes(buf)
            return Page(r.status_code, r.headers.get("content-type", ""), data,
                        data.decode(r.encoding or "utf-8", "replace"))
    raise ValueError("网址跳转次数太多")


async def fetch_url(url: str) -> tuple[str, str]:
    """→ (title, text). A GitHub repository gives its description and README."""
    url = url.strip()
    if not re.match(r"^https?://", url):
        raise ValueError("网址要以 http:// 或 https:// 开头")
    headers = {"user-agent": "Mozilla/5.0 (baotuo-teacher-video)"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, headers=headers) as c:
        m = GH.match(url)
        if m:
            owner, repo = m.group(1), m.group(2)
            parts = [f"# {owner}/{repo}", f"Repository: https://github.com/{owner}/{repo}", f"Owner: {owner}"]
            try:
                r = await _get(c, f"https://api.github.com/repos/{owner}/{repo}")
                if r.status == 200:
                    j = json.loads(r.text)
                    parts += [f"Name: {j.get('name')}", f"Description: {j.get('description') or ''}",
                              f"Stars: {j.get('stargazers_count')}", f"Language: {j.get('language') or ''}",
                              f"Topics: {', '.join(j.get('topics') or [])}", f"License: {(j.get('license') or {}).get('spdx_id', '')}"]
            except (httpx.HTTPError, ValueError):
                pass
            readme = ""
            for branch in ("HEAD", "main", "master"):
                for fname in ("README.md", "README.zh-CN.md", "readme.md", "README"):
                    try:
                        r = await _get(c, f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{fname}")
                    except (httpx.HTTPError, ValueError):
                        continue
                    if r.status == 200 and r.text.strip():
                        readme = r.text
                        break
                if readme:
                    break
            if not readme:
                try:
                    r = await _get(c, url)
                    readme = html_text(r.text)[1] if r.status == 200 else ""
                except (httpx.HTTPError, ValueError):
                    pass
            if not readme:
                raise ValueError("读不到这个仓库的 README（GitHub 访问不通？可以把 README 内容直接粘贴进来）")
            return f"{owner}-{repo}", "\n".join(parts) + "\n\n## README\n\n" + readme
        r = await _get(c, url)
        if r.status >= 400:
            raise ValueError(f"网页打不开（HTTP {r.status}）")
        ctype = r.ctype
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
