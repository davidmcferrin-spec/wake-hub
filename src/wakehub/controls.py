"""Fold linked single-target hardware into the device that already owns it.

The hardware row stays, with the same id and encrypted password, so the older
per-hardware endpoints keep working. Each hardware id is folded once. A later
restart does not put a removed method back.

AMT and JetKVM are tried before Wake-on-LAN. A plug, PDU outlet, UPS outlet,
or Roku is a power cut or a separate device, so it stays after Wake-on-LAN.
"""

from __future__ import annotations

import json
from typing import Any

from wakehub.hub import Hub

# Roku has no password column. The others keep password_enc untouched.
_LINKS = (
    ("amt_endpoints", "amt", "amt_id"),
    ("jetkvm_endpoints", "jetkvm", "jetkvm_id"),
    ("plugs", "plug", "plug_id"),
    ("rokus", "roku", "roku_id"),
)

# These can wake or shut down the machine itself. A meter plug must not jump ahead of them.
_BEFORE_WOL = {"amt", "jetkvm"}
_AFTER_WOL = {"plug", "pdu", "ups", "roku"}
_FOLDED = "control_folded"
_ORDER = "control_order_v1"


def fold_linked_controls(hub: Hub) -> list[dict[str, Any]]:
    merges = _merges(hub)
    folded = set(_folded_ids(hub))
    for item in merges:
        if item.get("kind") is not None and item.get("id") is not None:
            folded.add(f"{item['kind']}:{item['id']}")
    for table, kind, key in _LINKS:
        for row in hub.query(f"SELECT id, name, device_id FROM {table} WHERE device_id IS NOT NULL"):
            marker = f"{kind}:{row['id']}"
            if marker in folded:
                continue
            device = hub.query_one("SELECT id, name, methods FROM devices WHERE id = ?", (row["device_id"],))
            if device is None:
                folded.add(marker)
                continue
            methods = json.loads(device["methods"] or "[]") or [{"kind": "wol"}]
            method = {"kind": kind, key: row["id"]}
            if not _has_method(methods, method):
                methods = place_method(methods, method)
                hub.write("UPDATE devices SET methods = ? WHERE id = ?", (json.dumps(methods), device["id"]))
            if not any(item.get("kind") == kind and item.get("id") == row["id"] for item in merges):
                merges.append(
                    {
                        "kind": kind,
                        "id": row["id"],
                        "hardware": row["name"],
                        "device_id": device["id"],
                        "into": device["name"],
                    }
                )
            folded.add(marker)
    if hub.setting(_ORDER) != "1":
        _apply_default_order(hub)
        hub._write_setting(_ORDER, "1")
    hub._write_setting(_FOLDED, json.dumps(sorted(folded)))
    hub._write_setting("control_merges", json.dumps(merges))
    _mark_custom_timeouts(hub)
    return merges


def place_method(methods: list[dict[str, Any]], method: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert a method that is not already on the device, without passing a plug ahead of Wake-on-LAN."""
    if _has_method(methods, method):
        return methods
    kind = method.get("kind")
    if kind in _BEFORE_WOL:
        return _insert_before_wol(methods, method)
    if kind == "wol":
        return methods if any(item.get("kind") == "wol" for item in methods) else [*methods, {"kind": "wol"}]
    return _insert_after_wol(methods, method)


def _has_method(methods: list[dict[str, Any]], method: dict[str, Any]) -> bool:
    kind = method["kind"]
    key = next(iter(name for name in method if name != "kind"), None)
    if key is None:
        return any(item.get("kind") == kind for item in methods)
    return any(item.get("kind") == kind and item.get(key) == method[key] for item in methods)


def _insert_before_wol(methods: list[dict[str, Any]], method: dict[str, Any]) -> list[dict[str, Any]]:
    for index, item in enumerate(methods):
        if item.get("kind") == "wol":
            return [*methods[:index], method, *methods[index:]]
    return [*methods, method]


def _insert_after_wol(methods: list[dict[str, Any]], method: dict[str, Any]) -> list[dict[str, Any]]:
    for index, item in enumerate(methods):
        if item.get("kind") == "wol":
            return [*methods[: index + 1], method, *methods[index + 1 :]]
    return [*methods, method]


def _order_methods(methods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before: list[dict[str, Any]] = []
    wol: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for item in methods:
        kind = item.get("kind")
        if kind in _BEFORE_WOL:
            before.append(item)
        elif kind == "wol":
            wol.append(item)
        elif kind in _AFTER_WOL:
            after.append(item)
        else:
            rest.append(item)
    if not wol:
        wol = [{"kind": "wol"}]
    return [*before, *wol, *after, *rest]


def _apply_default_order(hub: Hub) -> None:
    for row in hub.query("SELECT id, methods FROM devices"):
        methods = json.loads(row["methods"] or "[]") or [{"kind": "wol"}]
        ordered = _order_methods(methods)
        if ordered != methods:
            hub.write("UPDATE devices SET methods = ? WHERE id = ?", (json.dumps(ordered), row["id"]))


def _merges(hub: Hub) -> list[dict[str, Any]]:
    raw = hub.setting("control_merges")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _folded_ids(hub: Hub) -> list[str]:
    raw = hub.setting(_FOLDED)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _mark_custom_timeouts(hub: Hub) -> None:
    # A stored 30 is the old column default, not a choice. Anything else was typed in.
    hub.write(
        "UPDATE devices SET reach_timeout_set = 1 WHERE reach_timeout_set = 0 AND reach_timeout IS NOT NULL AND reach_timeout != 30"
    )
