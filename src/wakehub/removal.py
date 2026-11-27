"""Delete inventory records without leaving plug, PDU, or salvo links behind."""

from __future__ import annotations

import json
from typing import Any

from wakehub.errors import WakeHubError
from wakehub.hub import Hub
from wakehub.inventory import utcnow
from wakehub.tags import has_tags, normalize_tags

KINDS = ("device", "pdu", "amt", "jetkvm", "plug", "ups", "roku")
_TABLE = {
    "device": "devices",
    "pdu": "pdus",
    "amt": "amt_endpoints",
    "jetkvm": "jetkvm_endpoints",
    "plug": "plugs",
    "ups": "ups_cards",
    "roku": "rokus",
}
_METHOD_ID = {
    "pdu": "pdu_id",
    "amt": "amt_id",
    "jetkvm": "jetkvm_id",
    "plug": "plug_id",
    "ups": "ups_id",
    "roku": "roku_id",
}
_HARDWARE_TABLES = ("amt_endpoints", "jetkvm_endpoints", "plugs", "ups_cards", "rokus")


def detach(hub: Hub, kind: str, item_id: int) -> list[str]:
    """Drop links that point at this record. Returns the salvos that lost a step."""
    if kind == "device":
        for table in _HARDWARE_TABLES:
            hub.write(f"UPDATE {table} SET device_id = NULL WHERE device_id = ?", (item_id,))
    else:
        key = _METHOD_ID.get(kind)
        if key:
            for row in hub.query("SELECT id, methods FROM devices"):
                methods = json.loads(row["methods"] or "[]")
                kept = [
                    item
                    for item in methods
                    if not (item.get("kind") == kind and int(item.get(key) or 0) == int(item_id))
                ]
                if len(kept) != len(methods):
                    if not any(item.get("kind") == "wol" for item in kept):
                        kept.insert(0, {"kind": "wol"})
                    hub.write("UPDATE devices SET methods = ? WHERE id = ?", (json.dumps(kept), row["id"]))
    return _drop_salvo_steps(hub, kind, item_id)


def bulk_remove(hub: Hub, *, confirm: bool, targets: list[dict[str, Any]] | None, tags: list[str] | None) -> dict[str, Any]:
    chosen = _resolve(hub, targets or [], tags or [])
    salvos = _salvo_names(hub, chosen)
    if confirm is not True:
        return {"confirm": False, "targets": chosen, "salvos": salvos, "removed": []}
    for item in chosen:
        _delete(hub, item["kind"], item["id"])
    return {"confirm": True, "targets": chosen, "salvos": salvos, "removed": chosen}


def _resolve(hub: Hub, targets: list[dict[str, Any]], tags: list[str]) -> list[dict[str, Any]]:
    found: dict[tuple[str, int], dict[str, Any]] = {}
    for item in targets:
        kind = str(item.get("kind") or "")
        if kind not in _TABLE:
            raise WakeHubError("bulk remove kind must be device, pdu, amt, jetkvm, plug, ups, or roku")
        if item.get("id") is None:
            raise WakeHubError("bulk remove target needs an id")
        row = hub.query_one(f"SELECT id, name FROM {_TABLE[kind]} WHERE id = ?", (int(item["id"]),))
        if row is None:
            continue
        found[(kind, row["id"])] = {"kind": kind, "id": row["id"], "name": row["name"]}
    wanted = normalize_tags(tags)
    if wanted:
        for kind, table in _TABLE.items():
            for row in hub.query(f"SELECT id, name, tags FROM {table}"):
                owned = json.loads(row["tags"] or "[]")
                if has_tags(owned, wanted):
                    found[(kind, row["id"])] = {"kind": kind, "id": row["id"], "name": row["name"]}
    return [found[key] for key in sorted(found)]


def _salvo_names(hub: Hub, targets: list[dict[str, Any]]) -> list[str]:
    if not targets:
        return []
    names: list[str] = []
    wanted = {(item["kind"], int(item["id"])) for item in targets}
    for row in hub.query("SELECT name, steps FROM salvos ORDER BY name COLLATE NOCASE"):
        steps = json.loads(row["steps"] or "[]")
        if any(_step_hits(step, wanted) for step in steps):
            names.append(row["name"])
    return names


def _step_hits(step: dict[str, Any], wanted: set[tuple[str, int]]) -> bool:
    kind = step.get("target_kind")
    if kind not in set(_TABLE) | {"outlet"} or step.get("target_id") is None:
        return False
    return (str(kind), int(step["target_id"])) in wanted


def _drop_salvo_steps(hub: Hub, kind: str, item_id: int) -> list[str]:
    changed: list[str] = []
    for row in hub.query("SELECT id, name, steps FROM salvos"):
        steps = json.loads(row["steps"] or "[]")
        kept = [step for step in steps if not _step_hits(step, {(kind, int(item_id))})]
        if len(kept) == len(steps):
            continue
        hub.write(
            "UPDATE salvos SET steps = ?, updated_at = ? WHERE id = ?",
            (json.dumps(kept), utcnow(), row["id"]),
        )
        changed.append(row["name"])
    return changed


def _delete(hub: Hub, kind: str, item_id: int) -> None:
    if kind == "device":
        from wakehub.inventory import remove_device

        remove_device(hub, item_id)
        return
    from wakehub.endpoints import remove_amt, remove_jetkvm, remove_pdu, remove_plug, remove_roku, remove_ups

    {
        "pdu": remove_pdu,
        "amt": remove_amt,
        "jetkvm": remove_jetkvm,
        "plug": remove_plug,
        "ups": remove_ups,
        "roku": remove_roku,
    }[kind](hub, item_id)
