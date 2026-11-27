"""Browser sessions. The API token is only for first-run setup."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Response

from wakehub.hub import Hub

COOKIE = "wakehub_ui"


def session_days(hub: Hub) -> int:
    raw = hub.setting("session_days", "30") or "30"
    try:
        days = int(raw)
    except ValueError:
        days = 30
    return min(365, max(1, days))


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _expires(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def set_cookie(response: Response, secret: str, days: int) -> None:
    # The LAN UI is plain HTTP. A Secure cookie would be dropped and the token prompt would return.
    response.set_cookie(
        COOKIE,
        secret,
        httponly=True,
        samesite="lax",
        max_age=days * 24 * 3600,
        path="/",
    )


def issue(hub: Hub, response: Response) -> None:
    secret = secrets.token_urlsafe(32)
    days = session_days(hub)
    hub.write(
        "INSERT INTO ui_sessions (token_hash, expires_at, created_at) VALUES (?, ?, ?)",
        (_hash(secret), _expires(days), _stamp()),
    )
    set_cookie(response, secret, days)


def valid(hub: Hub, secret: str) -> bool:
    if not secret:
        return False
    row = hub.query_one("SELECT id, expires_at FROM ui_sessions WHERE token_hash = ?", (_hash(secret),))
    if row is None:
        return False
    if row["expires_at"] <= _stamp():
        hub.write("DELETE FROM ui_sessions WHERE id = ?", (row["id"],))
        return False
    return True


def slide(hub: Hub, response: Response, secret: str) -> None:
    if not secret:
        return
    days = session_days(hub)
    hub.write(
        "UPDATE ui_sessions SET expires_at = ? WHERE token_hash = ?",
        (_expires(days), _hash(secret)),
    )
    set_cookie(response, secret, days)


def drop(hub: Hub, secret: str) -> None:
    if secret:
        hub.write("DELETE FROM ui_sessions WHERE token_hash = ?", (_hash(secret),))


def drop_all(hub: Hub) -> None:
    hub.write("DELETE FROM ui_sessions")


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
