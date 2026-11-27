"""Device inventory, wake, action log and settings."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from wakehub.crypto import decrypt, encrypt
from wakehub.errors import Conflict, DisabledDevice, NotFound, Unauthorized, WakeHubError, require_confirm
from wakehub.identity import assert_available, bind_identity
from wakehub.hub import Hub
from wakehub.wol import (
    build_magic_packet,
    normalize_mac,
    parse_secureon,
    send_magic_packet,
    wait_until_reachable,
)

log = logging.getLogger("wakehub.actions")

WAKE_STRATEGIES = {"wol_only", "power_then_wol"}
REACH_MODES = {"icmp", "tcp"}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tags(values: list[str]) -> list[str]:
    from wakehub.tags import normalize_tags

    return normalize_tags(values)


def normalize_methods(methods: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not methods:
        return [{"kind": "wol"}]
    cleaned: list[dict[str, Any]] = []
    for item in methods:
        if not isinstance(item, dict):
            raise WakeHubError("a power method must be an object")
        kind = item.get("kind")
        if kind == "wol":
            cleaned.append({"kind": "wol"})
        elif kind == "pdu":
            cleaned.append({"kind": "pdu", "pdu_id": int(item["pdu_id"]), "outlet": int(item["outlet"])})
        elif kind == "amt":
            cleaned.append({"kind": "amt", "amt_id": int(item["amt_id"])})
        elif kind == "jetkvm":
            cleaned.append({"kind": "jetkvm", "jetkvm_id": int(item["jetkvm_id"])})
        elif kind == "plug":
            cleaned.append({"kind": "plug", "plug_id": int(item["plug_id"])})
        elif kind == "ups":
            cleaned.append({"kind": "ups", "ups_id": int(item["ups_id"])})
        elif kind == "roku":
            cleaned.append({"kind": "roku", "roku_id": int(item["roku_id"])})
        else:
            raise WakeHubError(f"unknown power method {kind}")
    return cleaned


def _ipv4(value: str, label: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ipaddress.AddressValueError as exc:
        raise WakeHubError(f"{label} must be an IPv4 address") from exc


_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_host(value: str) -> str:
    """An IPv4/IPv6 address or a hostname whose labels do not start or end with '-'."""
    text = value.strip().rstrip(".")
    if not text or text.startswith("-") or ".." in text or any(ch.isspace() for ch in text):
        raise WakeHubError("host must be an IP address or a hostname")
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        pass
    if len(text) > 253:
        raise WakeHubError("host must be an IP address or a hostname")
    labels = text.split(".")
    if not labels or any(_HOST_LABEL.fullmatch(label) is None for label in labels):
        raise WakeHubError("host must be an IP address or a hostname")
    return text


def host_for_url(host: str) -> str:
    """IPv6 literals need brackets before a port, or the URL parser splits on the wrong colon."""
    text = host.strip()
    if text.startswith("[") and text.endswith("]"):
        return text
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return text
    if parsed.version == 6:
        return f"[{parsed}]"
    return str(parsed)


def _host(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return validate_host(text)


def public_device(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "mac": row["mac"],
        "host": row["host"],
        "broadcast": row["broadcast"],
        "wol_port": row["wol_port"],
        "secureon_set": bool(row["secureon_enc"]),
        "notes": row["notes"],
        "tags": json.loads(row["tags"]),
        "enabled": bool(row["enabled"]),
        "reach_mode": row["reach_mode"],
        "reach_port": row["reach_port"],
        "reach_timeout": row["reach_timeout"],
        "wake_strategy": row["wake_strategy"],
        "methods": json.loads(row["methods"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_row(hub: Hub, device_id: int) -> Any:
    row = hub.query_one("SELECT * FROM devices WHERE id = ?", (device_id,))
    if row is None:
        raise NotFound(f"device {device_id} was not found")
    return row


def list_devices(hub: Hub, *, tag: str | None = None, tags: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
    from wakehub.tags import has_tags, normalize_tags

    rows = hub.query("SELECT * FROM devices ORDER BY name COLLATE NOCASE")
    devices = [_with_power(hub, public_device(row)) for row in rows]
    text, inline = _query_tags(q)
    wanted = normalize_tags([*(tags or "").split(","), *([tag] if tag else []), *inline])
    if wanted:
        devices = [item for item in devices if has_tags(item["tags"], wanted)]
    if text:
        needle = text.lower()
        devices = [
            item
            for item in devices
            if needle in item["name"].lower()
            or needle in (item["host"] or "").lower()
            or needle in (item["mac"] or "").lower()
        ]
    return devices


def _query_tags(q: str | None) -> tuple[str, list[str]]:
    if not q:
        return "", []
    tags: list[str] = []
    words: list[str] = []
    for part in q.split():
        if part.startswith("#") and len(part) > 1:
            tags.append(part)
        else:
            words.append(part)
    return " ".join(words), tags


def get_device(hub: Hub, device_id: int) -> dict[str, Any]:
    return _with_power(hub, public_device(_get_row(hub, device_id)))


def _with_power(hub: Hub, device: dict[str, Any]) -> dict[str, Any]:
    from wakehub.metrics import power_snapshot

    device["power"] = power_snapshot(hub, device)
    return device


def _insert_values(hub: Hub, fields: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    try:
        device_id = hub.write(
            """
            INSERT INTO devices (
                name, mac, host, broadcast, wol_port, secureon_enc, notes, tags,
                enabled, reach_mode, reach_port, reach_timeout, wake_strategy, methods,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["name"],
                fields["mac"],
                fields["host"],
                fields["broadcast"],
                fields["wol_port"],
                fields["secureon_enc"],
                fields["notes"],
                fields["tags"],
                fields["enabled"],
                fields["reach_mode"],
                fields["reach_port"],
                fields["reach_timeout"],
                fields["wake_strategy"],
                fields["methods"],
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a device named {fields['name']} already exists") from exc
    bind_identity(hub, "device", device_id, fields["host"], fields["mac"])
    return get_device(hub, device_id)


def add_device(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name or len(name) > 80:
        raise WakeHubError("name is required and must be 80 characters or fewer")
    mac = payload.get("mac")
    mac_norm = normalize_mac(mac) if mac else None
    secureon = payload.get("secureon")
    secureon_enc = encrypt(hub.cipher, parse_secureon(secureon).hex()) if secureon else None
    reach_mode = payload.get("reach_mode") or "icmp"
    if reach_mode not in REACH_MODES:
        raise WakeHubError("reach_mode must be icmp or tcp")
    strategy = payload.get("wake_strategy") or "wol_only"
    if strategy not in WAKE_STRATEGIES:
        raise WakeHubError("wake_strategy must be wol_only or power_then_wol")
    port = int(payload.get("wol_port") or 9)
    if port < 1 or port > 65535:
        raise WakeHubError("wol_port must be between 1 and 65535")
    reach_port = payload.get("reach_port")
    if reach_port is not None:
        reach_port = int(reach_port)
        if reach_port < 1 or reach_port > 65535:
            raise WakeHubError("reach_port must be between 1 and 65535")
    timeout = float(payload.get("reach_timeout") if payload.get("reach_timeout") is not None else 30)
    if timeout <= 0 or timeout > 300:
        raise WakeHubError("reach_timeout must be between 0 and 300 seconds")
    notes = payload.get("notes") or ""
    if len(notes) > 2000:
        raise WakeHubError("notes must be 2000 characters or fewer")
    host = _host(payload.get("host"))
    assert_available(hub, "device", host, mac_norm)
    return _insert_values(
        hub,
        {
            "name": name,
            "mac": mac_norm,
            "host": host,
            "broadcast": _ipv4(payload.get("broadcast") or "255.255.255.255", "broadcast"),
            "wol_port": port,
            "secureon_enc": secureon_enc,
            "notes": notes,
            "tags": json.dumps(_tags(list(payload.get("tags") or []))),
            "enabled": 1 if payload.get("enabled", True) else 0,
            "reach_mode": reach_mode,
            "reach_port": reach_port,
            "reach_timeout": timeout,
            "wake_strategy": strategy,
            "methods": json.dumps(normalize_methods(payload.get("methods"))),
        },
    )


def update_device(hub: Hub, device_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = _get_row(hub, device_id)
    fields: dict[str, Any] = {
        "name": row["name"],
        "mac": row["mac"],
        "host": row["host"],
        "broadcast": row["broadcast"],
        "wol_port": row["wol_port"],
        "secureon_enc": row["secureon_enc"],
        "notes": row["notes"],
        "tags": row["tags"],
        "enabled": row["enabled"],
        "reach_mode": row["reach_mode"],
        "reach_port": row["reach_port"],
        "reach_timeout": row["reach_timeout"],
        "wake_strategy": row["wake_strategy"],
        "methods": row["methods"],
    }
    if "name" in payload and payload["name"] is not None:
        name = str(payload["name"]).strip()
        if not name or len(name) > 80:
            raise WakeHubError("name is required and must be 80 characters or fewer")
        fields["name"] = name
    if "mac" in payload:
        fields["mac"] = normalize_mac(payload["mac"]) if payload["mac"] else None
    if "host" in payload:
        fields["host"] = _host(payload["host"])
    if "broadcast" in payload and payload["broadcast"] is not None:
        fields["broadcast"] = _ipv4(payload["broadcast"], "broadcast")
    if "wol_port" in payload and payload["wol_port"] is not None:
        port = int(payload["wol_port"])
        if port < 1 or port > 65535:
            raise WakeHubError("wol_port must be between 1 and 65535")
        fields["wol_port"] = port
    if "secureon" in payload:
        if payload["secureon"] in (None, ""):
            fields["secureon_enc"] = None
        else:
            fields["secureon_enc"] = encrypt(hub.cipher, parse_secureon(str(payload["secureon"])).hex())
    if "notes" in payload and payload["notes"] is not None:
        if len(payload["notes"]) > 2000:
            raise WakeHubError("notes must be 2000 characters or fewer")
        fields["notes"] = payload["notes"]
    if "tags" in payload and payload["tags"] is not None:
        fields["tags"] = json.dumps(_tags(list(payload["tags"])))
    if "enabled" in payload and payload["enabled"] is not None:
        fields["enabled"] = 1 if payload["enabled"] else 0
    if "reach_mode" in payload and payload["reach_mode"] is not None:
        if payload["reach_mode"] not in REACH_MODES:
            raise WakeHubError("reach_mode must be icmp or tcp")
        fields["reach_mode"] = payload["reach_mode"]
    if "reach_port" in payload:
        reach_port = payload["reach_port"]
        if reach_port is not None:
            reach_port = int(reach_port)
            if reach_port < 1 or reach_port > 65535:
                raise WakeHubError("reach_port must be between 1 and 65535")
        fields["reach_port"] = reach_port
    if "reach_timeout" in payload and payload["reach_timeout"] is not None:
        timeout = float(payload["reach_timeout"])
        if timeout <= 0 or timeout > 300:
            raise WakeHubError("reach_timeout must be between 0 and 300 seconds")
        fields["reach_timeout"] = timeout
    if "wake_strategy" in payload and payload["wake_strategy"] is not None:
        if payload["wake_strategy"] not in WAKE_STRATEGIES:
            raise WakeHubError("wake_strategy must be wol_only or power_then_wol")
        fields["wake_strategy"] = payload["wake_strategy"]
    if "methods" in payload and payload["methods"] is not None:
        fields["methods"] = json.dumps(normalize_methods(payload["methods"]))
    assert_available(hub, "device", fields["host"], fields["mac"], exclude_id=device_id)
    try:
        hub.write(
            """
            UPDATE devices SET
                name=?, mac=?, host=?, broadcast=?, wol_port=?, secureon_enc=?, notes=?, tags=?,
                enabled=?, reach_mode=?, reach_port=?, reach_timeout=?, wake_strategy=?, methods=?,
                updated_at=?
            WHERE id=?
            """,
            (
                fields["name"],
                fields["mac"],
                fields["host"],
                fields["broadcast"],
                fields["wol_port"],
                fields["secureon_enc"],
                fields["notes"],
                fields["tags"],
                fields["enabled"],
                fields["reach_mode"],
                fields["reach_port"],
                fields["reach_timeout"],
                fields["wake_strategy"],
                fields["methods"],
                utcnow(),
                device_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a device named {fields['name']} already exists") from exc
    bind_identity(hub, "device", device_id, fields["host"], fields["mac"])
    return get_device(hub, device_id)


def remove_device(hub: Hub, device_id: int) -> None:
    _get_row(hub, device_id)
    from wakehub.removal import detach

    detach(hub, "device", device_id)
    hub.write_many(
        [
            ("UPDATE actions SET device_id = NULL WHERE device_id = ?", (device_id,)),
            ("DELETE FROM devices WHERE id = ?", (device_id,)),
        ]
    )


def set_enabled(hub: Hub, device_id: int, enabled: bool) -> dict[str, Any]:
    return update_device(hub, device_id, {"enabled": enabled})


def record_action(
    hub: Hub,
    *,
    source: str,
    action: str,
    ok: bool,
    detail: str,
    device_id: int | None = None,
    target_kind: str = "device",
    target_id: int | None = None,
    target_name: str = "",
) -> None:
    if source not in {"ui", "api", "mcp"}:
        source = "api"
    hub.write(
        """
        INSERT INTO actions (
            created_at, source, device_id, target_kind, target_id, target_name, action, ok, detail
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (utcnow(), source, device_id, target_kind, target_id, target_name, action, 1 if ok else 0, detail),
    )
    log.info(
        "action=%s source=%s target=%s:%s name=%s ok=%s",
        action,
        source,
        target_kind,
        target_id,
        target_name,
        ok,
    )


def list_actions(hub: Hub, *, limit: int = 100, device_id: int | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    if device_id is None:
        rows = hub.query(
            "SELECT * FROM actions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    else:
        rows = hub.query(
            "SELECT * FROM actions WHERE device_id = ? ORDER BY id DESC LIMIT ?",
            (device_id, limit),
        )
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "source": row["source"],
            "device_id": row["device_id"],
            "target_kind": row["target_kind"],
            "target_id": row["target_id"],
            "target_name": row["target_name"],
            "action": row["action"],
            "ok": bool(row["ok"]),
            "detail": row["detail"],
        }
        for row in rows
    ]


def _secureon_bytes(hub: Hub, row: Any) -> bytes | None:
    if not row["secureon_enc"]:
        return None
    return bytes.fromhex(decrypt(hub.cipher, row["secureon_enc"]))


def _require_enabled(hub: Hub, row: Any, source: str, action: str) -> None:
    if row["enabled"]:
        return
    record_action(
        hub,
        source=source,
        action=action,
        ok=False,
        detail="device is disabled",
        device_id=row["id"],
        target_id=row["id"],
        target_name=row["name"],
    )
    raise DisabledDevice("Device is disabled")


def wake_device(hub: Hub, device_id: int, *, source: str, timeout: float | None = None) -> dict[str, Any]:
    row = _get_row(hub, device_id)
    _require_enabled(hub, row, source, "wake")
    if not row["mac"]:
        record_action(
            hub,
            source=source,
            action="wake",
            ok=False,
            detail="device has no MAC address",
            device_id=row["id"],
            target_id=row["id"],
            target_name=row["name"],
        )
        raise WakeHubError("device has no MAC address")
    if row["wake_strategy"] == "power_then_wol":
        from wakehub.power import power_on_linked

        power_on_linked(hub, row, source)
    packet = build_magic_packet(row["mac"], _secureon_bytes(hub, row))
    try:
        send_magic_packet(packet, row["broadcast"], int(row["wol_port"]))
    except (OSError, WakeHubError) as exc:
        record_action(
            hub,
            source=source,
            action="wake",
            ok=False,
            detail=str(exc),
            device_id=row["id"],
            target_id=row["id"],
            target_name=row["name"],
        )
        raise
    probe_timeout = float(timeout if timeout is not None else row["reach_timeout"])
    reachable, elapsed = wait_until_reachable(row["host"], row["reach_mode"], row["reach_port"], probe_timeout)
    detail = json.dumps(
        {
            "broadcast": row["broadcast"],
            "port": row["wol_port"],
            "bytes": len(packet),
            "reachable": reachable,
            "elapsed_s": round(elapsed, 2),
        }
    )
    record_action(
        hub,
        source=source,
        action="wake",
        ok=True,
        detail=detail,
        device_id=row["id"],
        target_id=row["id"],
        target_name=row["name"],
    )
    return {
        "device_id": row["id"],
        "name": row["name"],
        "sent": True,
        "broadcast": row["broadcast"],
        "port": row["wol_port"],
        "reachable": reachable,
        "elapsed_s": round(elapsed, 2),
    }


def power_action(
    hub: Hub,
    device_id: int,
    *,
    action: str,
    method: str = "auto",
    confirm: bool = False,
    source: str,
) -> dict[str, Any]:
    from wakehub.power import dispatch_device

    return dispatch_device(hub, device_id, action=action, method=method, confirm=confirm, source=source)


def probe_device(hub: Hub, device_id: int, *, timeout: float = 2) -> dict[str, Any]:
    row = _get_row(hub, device_id)
    reachable, elapsed = wait_until_reachable(row["host"], row["reach_mode"], row["reach_port"], timeout)
    return {
        "device_id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "enabled": bool(row["enabled"]),
        "reachable": reachable,
        "elapsed_s": round(elapsed, 2),
    }


def probe_all(hub: Hub, *, timeout: float = 1) -> list[dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor

    rows = hub.query("SELECT id FROM devices WHERE enabled = 1 ORDER BY name COLLATE NOCASE")
    if not rows:
        return []

    def one(device_id: int) -> dict[str, Any]:
        return probe_device(hub, device_id, timeout=timeout)

    with ThreadPoolExecutor(max_workers=min(16, len(rows))) as pool:
        return list(pool.map(one, [row["id"] for row in rows]))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
    return secrets.compare_digest(digest, bytes.fromhex(digest_hex))


def public_settings(hub: Hub) -> dict[str, Any]:
    return {
        "ui_password_set": bool(hub.setting("ui_password")),
        "cors_origins": hub.cors_origins(),
        "metrics_poll_seconds": int(hub.setting("metrics_poll_seconds", "60") or 60),
        "metrics_retention_days": int(hub.setting("metrics_retention_days", "30") or 30),
        "session_days": int(hub.setting("session_days", "30") or 30),
        "scan_keep": int(hub.setting("scan_keep", "0") or 0),
        "scan_keep_days": int(hub.setting("scan_keep_days", "0") or 0),
        "duplicate_records": _duplicate_records(hub),
    }


def _duplicate_records(hub: Hub) -> list[dict[str, Any]]:
    raw = hub.setting("duplicate_records")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def update_settings(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("clear_ui_password"):
        hub.write("DELETE FROM settings WHERE key = 'ui_password'")
    elif payload.get("ui_password"):
        password = str(payload["ui_password"])
        if len(password) < 8:
            raise WakeHubError("UI password must be at least 8 characters")
        hub._write_setting("ui_password", hash_password(password))
    if payload.get("metrics_poll_seconds") is not None:
        seconds = int(payload["metrics_poll_seconds"])
        if seconds < 15 or seconds > 3600:
            raise WakeHubError("metrics poll must be between 15 and 3600 seconds")
        hub._write_setting("metrics_poll_seconds", str(seconds))
    if payload.get("metrics_retention_days") is not None:
        days = int(payload["metrics_retention_days"])
        if days < 1 or days > 3650:
            raise WakeHubError("metrics retention must be between 1 and 3650 days")
        hub._write_setting("metrics_retention_days", str(days))
    if payload.get("session_days") is not None:
        days = int(payload["session_days"])
        if days < 1 or days > 365:
            raise WakeHubError("session length must be between 1 and 365 days")
        hub._write_setting("session_days", str(days))
    if payload.get("scan_keep") is not None:
        keep = int(payload["scan_keep"])
        if keep < 0 or keep > 500:
            raise WakeHubError("scan history length must be between 0 and 500")
        hub._write_setting("scan_keep", str(keep))
    if payload.get("scan_keep_days") is not None:
        days = int(payload["scan_keep_days"])
        if days < 0 or days > 3650:
            raise WakeHubError("scan history age must be between 0 and 3650 days")
        hub._write_setting("scan_keep_days", str(days))
    if payload.get("cors_origins") is not None:
        origins = payload["cors_origins"]
        if isinstance(origins, str):
            origins = [part.strip() for part in origins.split(",") if part.strip()]
        if not isinstance(origins, list) or not origins:
            raise WakeHubError("cors_origins must be a list of origins, or *")
        hub._write_setting("cors_origins", ",".join(str(item).strip() for item in origins if str(item).strip()))
    if payload.get("scan_keep") is not None or payload.get("scan_keep_days") is not None:
        from wakehub.scan import prune_scans

        prune_scans(hub)
    return public_settings(hub)


def ui_login(hub: Hub, password: str, *, client: str) -> dict[str, Any]:
    if hub.attempts_blocked(f"ui:{client}"):
        raise Unauthorized("too many attempts; try again later")
    stored = hub.setting("ui_password")
    if not stored:
        hub.note_attempt(f"ui:{client}", ok=False)
        raise WakeHubError("UI password is not set")
    if not verify_password(password, stored):
        hub.note_attempt(f"ui:{client}", ok=False)
        raise Unauthorized("UI password is wrong")
    hub.note_attempt(f"ui:{client}", ok=True)
    return {"ok": True}


def ui_setup(hub: Hub, api_token: str, password: str, *, client: str) -> dict[str, Any]:
    if hub.setting("ui_password"):
        raise Conflict("UI password is already set")
    if hub.attempts_blocked(f"setup:{client}"):
        raise Unauthorized("too many attempts; try again later")
    if not token_matches(api_token, hub.token):
        hub.note_attempt(f"setup:{client}", ok=False)
        raise Unauthorized("API token is wrong")
    if len(password) < 8:
        raise WakeHubError("UI password must be at least 8 characters")
    hub._write_setting("ui_password", hash_password(password))
    hub.note_attempt(f"setup:{client}", ok=True)
    return {"ok": True}


def token_matches(presented: str, expected: str) -> bool:
    if len(presented) != len(expected):
        return False
    return secrets.compare_digest(presented, expected)
