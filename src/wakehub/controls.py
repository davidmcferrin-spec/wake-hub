"""Fold linked single-target hardware into the device that already owns it.

The hardware row stays, with the same id and encrypted password, so the older
per-hardware endpoints keep working. The device's methods list is the order
tried for Wake, Off, Reset and Cycle.
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


def fold_linked_controls(hub: Hub) -> list[dict[str, Any]]:
    merges = _merges(hub)
    known = {(item.get("kind"), item.get("id"), item.get("device_id")) for item in merges}
    for table, kind, key in _LINKS:
        for row in hub.query(f"SELECT id, name, device_id FROM {table} WHERE device_id IS NOT NULL"):
            device = hub.query_one("SELECT id, name, methods FROM devices WHERE id = ?", (row["device_id"],))
            if device is None:
                continue
            methods = json.loads(device["methods"] or "[]") or [{"kind": "wol"}]
            method = {"kind": kind, key: row["id"]}
            marker = (kind, row["id"], device["id"])
            if _has_method(methods, method):
                if marker in known:
                    continue
                # The first time we notice a link that was appended after Wake-on-LAN, try the hardware first.
                methods = _move_before_wol(methods, method)
            else:
                methods = _insert_before_wol(methods, method)
            hub.write("UPDATE devices SET methods = ? WHERE id = ?", (json.dumps(methods), device["id"]))
            if marker in known:
                continue
            merges.append(
                {
                    "kind": kind,
                    "id": row["id"],
                    "hardware": row["name"],
                    "device_id": device["id"],
                    "into": device["name"],
                }
            )
            known.add(marker)
    hub._write_setting("control_merges", json.dumps(merges))
    _mark_custom_timeouts(hub)
    return merges


def _has_method(methods: list[dict[str, Any]], method: dict[str, Any]) -> bool:
    kind = method["kind"]
    key = next(iter(k for k in method if k != "kind"))
    return any(item.get("kind") == kind and item.get(key) == method[key] for item in methods)


def _move_before_wol(methods: list[dict[str, Any]], method: dict[str, Any]) -> list[dict[str, Any]]:
    kind = method["kind"]
    key = next(iter(name for name in method if name != "kind"))
    kept = [item for item in methods if not (item.get("kind") == kind and item.get(key) == method[key])]
    return _insert_before_wol(kept, method)


def _insert_before_wol(methods: list[dict[str, Any]], method: dict[str, Any]) -> list[dict[str, Any]]:
    for index, item in enumerate(methods):
        if item.get("kind") == "wol":
            return [*methods[:index], method, *methods[index:]]
    return [*methods, method]


def _merges(hub: Hub) -> list[dict[str, Any]]:
    raw = hub.setting("control_merges")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _mark_custom_timeouts(hub: Hub) -> None:
    # A stored 30 is the old column default, not a choice. Anything else was typed in.
    hub.write(
        "UPDATE devices SET reach_timeout_set = 1 WHERE reach_timeout_set = 0 AND reach_timeout IS NOT NULL AND reach_timeout != 30"
    )
