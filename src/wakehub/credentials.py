"""Saved logins that several endpoints can share. Each endpoint can still keep its own."""

from __future__ import annotations

from typing import Any

from wakehub.crypto import decrypt, encrypt
from wakehub.errors import Conflict, NotFound, WakeHubError
from wakehub.hub import Hub
from wakehub.inventory import utcnow


def _secret(hub: Hub, value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return encrypt(hub.cipher, value)


def _plain(hub: Hub, stored: str | None) -> str:
    if not stored:
        return ""
    return decrypt(hub.cipher, stored)


def public_profile(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "username": row["username"],
        "password_set": bool(row["password_enc"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_profiles(hub: Hub) -> list[dict[str, Any]]:
    return [public_profile(row) for row in hub.query("SELECT * FROM credential_profiles ORDER BY name COLLATE NOCASE")]


def add_profile(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise WakeHubError("name is required")
    now = utcnow()
    item_id = hub.write(
        """
        INSERT INTO credential_profiles (name, username, password_enc, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, str(payload.get("username") or ""), _secret(hub, payload.get("password")), now, now),
    )
    return public_profile(hub.query_one("SELECT * FROM credential_profiles WHERE id = ?", (item_id,)))


def update_profile(hub: Hub, profile_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = hub.query_one("SELECT * FROM credential_profiles WHERE id = ?", (profile_id,))
    if current is None:
        raise NotFound(f"credential profile {profile_id} was not found")
    password = current["password_enc"] if "password" not in payload else _secret(hub, payload.get("password"))
    hub.write(
        """
        UPDATE credential_profiles SET name = ?, username = ?, password_enc = ?, updated_at = ? WHERE id = ?
        """,
        (
            str(payload.get("name") or current["name"]).strip(),
            payload.get("username") if payload.get("username") is not None else current["username"],
            password,
            utcnow(),
            profile_id,
        ),
    )
    return public_profile(hub.query_one("SELECT * FROM credential_profiles WHERE id = ?", (profile_id,)))


_PROFILE_TABLES = (
    ("pdus", "PDU"),
    ("amt_endpoints", "AMT"),
    ("jetkvm_endpoints", "JetKVM"),
    ("plugs", "plug"),
    ("ups_cards", "UPS"),
    ("rokus", "Roku"),
)


def _profile_users(hub: Hub, profile_id: int) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    for table, kind in _PROFILE_TABLES:
        for row in hub.query(f"SELECT id, name FROM {table} WHERE credential_profile_id = ?", (profile_id,)):
            users.append({"kind": kind, "id": row["id"], "name": row["name"]})
    return users


def remove_profile(hub: Hub, profile_id: int, *, force: bool = False) -> None:
    current = hub.query_one("SELECT id FROM credential_profiles WHERE id = ?", (profile_id,))
    if current is None:
        raise NotFound(f"credential profile {profile_id} was not found")
    users = _profile_users(hub, profile_id)
    if users and not force:
        listed = ", ".join(f"{item['kind']} {item['name']}" for item in users)
        raise Conflict(
            f"saved login is used by {listed}. Set force to true to clear those links.",
            existing={"records": users},
        )
    if force:
        for table, _kind in _PROFILE_TABLES:
            hub.write(f"UPDATE {table} SET credential_profile_id = NULL WHERE credential_profile_id = ?", (profile_id,))
    hub.write("DELETE FROM credential_profiles WHERE id = ?", (profile_id,))


def profile_login(hub: Hub, profile_id: int | None) -> tuple[str, str] | None:
    if not profile_id:
        return None
    row = hub.query_one("SELECT username, password_enc FROM credential_profiles WHERE id = ?", (profile_id,))
    if row is None:
        raise NotFound(f"credential profile {profile_id} was not found")
    return row["username"] or "", _plain(hub, row["password_enc"])


def remember_profile(hub: Hub, table: str, item_id: int, payload: dict[str, Any]) -> None:
    if "credential_profile_id" not in payload:
        return
    value = payload.get("credential_profile_id") or None
    if value is not None:
        profile_login(hub, int(value))
        value = int(value)
    hub.write(f"UPDATE {table} SET credential_profile_id = ? WHERE id = ?", (value, item_id))
