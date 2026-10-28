"""Optional password protection (APP_PASSWORD) and signed links for the sandboxed preview."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from . import config

COOKIE = "btv_session"
SESSION_DAYS = 30


def _secret() -> bytes:
    import os
    env = os.environ.get("APP_SECRET")
    if env:
        return env.encode()
    f = config.SECRET_FILE
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
        os.chmod(f, 0o600)
    return f.read_text().strip().encode()


def _sign(msg: str) -> str:
    return hmac.new(_secret(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def enabled() -> bool:
    return bool(config.APP_PASSWORD)


def check_password(pw: str) -> bool:
    return enabled() and hmac.compare_digest(pw.encode(), config.APP_PASSWORD.encode())


def new_session() -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    # the password's own hash is part of the signature: changing APP_PASSWORD logs every session out
    pw = hashlib.sha256(config.APP_PASSWORD.encode()).hexdigest()[:8]
    return f"{exp}.{_sign(f'session.{exp}.{pw}')}"


def valid_session(token: str | None) -> bool:
    if not enabled():
        return True
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < time.time():
        return False
    pw = hashlib.sha256(config.APP_PASSWORD.encode()).hexdigest()[:8]
    return hmac.compare_digest(sig, _sign(f"session.{exp}.{pw}"))


def preview_token(project_id: str, hours: int = 12) -> str:
    """The preview runs model-written code in an opaque-origin iframe that carries no cookie: its files are fetched
    through a signed path instead."""
    exp = int(time.time()) + hours * 3600
    return f"{exp}-{_sign(f'preview.{project_id}.{exp}')}"


def valid_preview(project_id: str, token: str) -> bool:
    if "-" not in token:
        return False
    exp, sig = token.split("-", 1)
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(f"preview.{project_id}.{exp}"))
