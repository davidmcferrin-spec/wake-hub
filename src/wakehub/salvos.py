"""Named sequences of power steps. schedule is stored and unused so a timer can be added later."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from wakehub.errors import ConfirmationRequired, Conflict, NotFound, WakeHubError
from wakehub.hub import Hub
from wakehub.inventory import utcnow
from wakehub.tags import has_tags, normalize_tags

ACTIONS = {"wake", "on", "off", "cycle", "shutdown"}
TARGET_KINDS = {"device", "plug", "roku", "tag"}
ON_ERROR = {"stop", "continue"}
_SUPPORTS = {
    "device": ACTIONS,
    "plug": {"on", "off", "cycle"},
    "roku": {"on", "off"},
}


def list_salvos(hub: Hub) -> list[dict[str, Any]]:
    return [_public(row) for row in hub.query("SELECT * FROM salvos ORDER BY name COLLATE NOCASE")]


def get_salvo(hub: Hub, salvo_id: int) -> dict[str, Any]:
    return _public(_row(hub, salvo_id))


def add_salvo(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    name = _name(payload.get("name"))
    steps = _steps(payload.get("steps"))
    on_error = _on_error(payload.get("on_error") or "stop")
    now = utcnow()
    try:
        salvo_id = hub.write(
            """
            INSERT INTO salvos (name, steps, on_error, schedule, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (name, json.dumps(steps), on_error, now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a salvo named {name} already exists") from exc
    return get_salvo(hub, salvo_id)


def update_salvo(hub: Hub, salvo_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _row(hub, salvo_id)
    name = _name(payload["name"]) if payload.get("name") else current["name"]
    steps = _steps(payload["steps"]) if "steps" in payload and payload["steps"] is not None else json.loads(current["steps"])
    on_error = _on_error(payload["on_error"]) if payload.get("on_error") else current["on_error"]
    try:
        hub.write(
            "UPDATE salvos SET name=?, steps=?, on_error=?, updated_at=? WHERE id=?",
            (name, json.dumps(steps), on_error, utcnow(), salvo_id),
        )
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"a salvo named {name} already exists") from exc
    return get_salvo(hub, salvo_id)


def remove_salvo(hub: Hub, salvo_id: int) -> None:
    _row(hub, salvo_id)
    hub.write("DELETE FROM salvos WHERE id = ?", (salvo_id,))


def duplicate_salvo(hub: Hub, salvo_id: int) -> dict[str, Any]:
    current = get_salvo(hub, salvo_id)
    name = _copy_name(hub, current["name"])
    return add_salvo(hub, {"name": name, "steps": current["steps"], "on_error": current["on_error"]})


def run_salvo(hub: Hub, salvo_id: int, *, confirm: bool, dry_run: bool, source: str) -> dict[str, Any]:
    salvo = get_salvo(hub, salvo_id)
    plan = [_plan_step(hub, index, step) for index, step in enumerate(salvo["steps"])]
    if dry_run:
        steps = []
        for step in plan:
            steps.append({**_step_view(step), "targets": [{**item, "ok": None, "detail": "preview"} for item in _targets_view(step)]})
        return _envelope(salvo, dry_run=True, stopped=False, steps=steps)
    if confirm is not True:
        raise ConfirmationRequired("running a salvo needs confirm set to true")
    steps: list[dict[str, Any]] = []
    stopped = False
    for step in plan:
        if step["delay_seconds"]:
            time.sleep(step["delay_seconds"])
        rows: list[dict[str, Any]] = []
        for target in step["targets"]:
            outcome = _execute(hub, salvo["name"], step["action"], target, source)
            rows.append(outcome)
            if not outcome["ok"] and salvo["on_error"] == "stop":
                stopped = True
                break
        steps.append({**_step_view(step), "targets": rows})
        if stopped:
            break
    return _envelope(salvo, dry_run=False, stopped=stopped, steps=steps)


def _plan_step(hub: Hub, index: int, step: dict[str, Any]) -> dict[str, Any]:
    return {
        "step": index,
        "action": step["action"],
        "delay_seconds": step["delay_seconds"],
        "targets": _targets(hub, step),
    }


def _targets(hub: Hub, step: dict[str, Any]) -> list[dict[str, Any]]:
    action = step["action"]
    kind = step["target_kind"]
    if kind == "tag":
        return _tagged(hub, step["tags"], action)
    return [_one(hub, kind, int(step["target_id"]))]


def _tagged(hub: Hub, tags: list[str], action: str) -> list[dict[str, Any]]:
    from wakehub.endpoints import list_plugs, list_rokus
    from wakehub.inventory import list_devices

    found: list[dict[str, Any]] = []
    if action in _SUPPORTS["device"]:
        for device in list_devices(hub):
            if has_tags(device["tags"], tags):
                found.append({"kind": "device", "id": device["id"], "name": device["name"]})
    if action in _SUPPORTS["plug"]:
        for plug in list_plugs(hub):
            if has_tags(plug["tags"], tags):
                found.append({"kind": "plug", "id": plug["id"], "name": plug["name"]})
    if action in _SUPPORTS["roku"]:
        for roku in list_rokus(hub):
            if has_tags(roku["tags"], tags):
                found.append({"kind": "roku", "id": roku["id"], "name": roku["name"]})
    return found


def _one(hub: Hub, kind: str, item_id: int) -> dict[str, Any]:
    table = {"device": "devices", "plug": "plugs", "roku": "rokus"}[kind]
    row = hub.query_one(f"SELECT id, name FROM {table} WHERE id = ?", (item_id,))
    if row is None:
        return {"kind": kind, "id": item_id, "name": f"missing {kind} {item_id}", "missing": True}
    return {"kind": kind, "id": row["id"], "name": row["name"], "missing": False}


def _execute(hub: Hub, salvo_name: str, action: str, target: dict[str, Any], source: str) -> dict[str, Any]:
    from wakehub.inventory import record_action, wake_device
    from wakehub.power import dispatch_device, plug_power, roku_power

    kind = target["kind"]
    item_id = target["id"]
    name = target["name"]
    detail = f"salvo {salvo_name}"
    if target.get("missing") or action not in _SUPPORTS.get(kind, set()):
        reason = f"{kind} cannot {action}" if not target.get("missing") else f"{name} was not found"
        record_action(hub, source=source, action=action, ok=False, detail=f"{detail}: {reason}", target_kind=kind, target_id=item_id, target_name=name)
        return {"kind": kind, "id": item_id, "name": name, "ok": False, "detail": reason}
    try:
        if kind == "device" and action == "wake":
            wake_device(hub, item_id, source=source)
        elif kind == "device":
            dispatch_device(hub, item_id, action=action, confirm=True, source=source)
        elif kind == "plug":
            plug_power(hub, item_id, action, confirm=True, source=source)
        else:
            roku_power(hub, item_id, action, confirm=True, source=source)
    except Exception as exc:
        record_action(hub, source=source, action=action, ok=False, detail=f"{detail}: {exc}", target_kind=kind, target_id=item_id, target_name=name)
        return {"kind": kind, "id": item_id, "name": name, "ok": False, "detail": str(exc)}
    record_action(hub, source=source, action=action, ok=True, detail=detail, target_kind=kind, target_id=item_id, target_name=name)
    return {"kind": kind, "id": item_id, "name": name, "ok": True, "detail": detail}


def _step_view(step: dict[str, Any]) -> dict[str, Any]:
    return {"step": step["step"], "action": step["action"], "delay_seconds": step["delay_seconds"]}


def _targets_view(step: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"kind": item["kind"], "id": item["id"], "name": item["name"]} for item in step["targets"]]


def _envelope(salvo: dict[str, Any], *, dry_run: bool, stopped: bool, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "salvo_id": salvo["id"],
        "name": salvo["name"],
        "dry_run": dry_run,
        "on_error": salvo["on_error"],
        "schedule": salvo["schedule"],
        "stopped": stopped,
        "steps": steps,
    }


def _row(hub: Hub, salvo_id: int):
    row = hub.query_one("SELECT * FROM salvos WHERE id = ?", (salvo_id,))
    if row is None:
        raise NotFound(f"salvo {salvo_id} was not found")
    return row


def _public(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "steps": json.loads(row["steps"] or "[]"),
        "on_error": row["on_error"],
        # Nothing schedules a salvo yet. The column is here so a timer can be added without a new table.
        "schedule": row["schedule"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise WakeHubError("a salvo needs a name")
    if len(text) > 80:
        raise WakeHubError("a salvo name must be 80 characters or fewer")
    return text


def _on_error(value: object) -> str:
    text = str(value or "stop")
    if text not in ON_ERROR:
        raise WakeHubError("on_error must be stop or continue")
    return text


def _steps(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise WakeHubError("steps must be a list")
    if len(value) > 50:
        raise WakeHubError("a salvo can have at most 50 steps")
    return [_step(item, index) for index, item in enumerate(value)]


def _step(item: object, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise WakeHubError(f"step {index + 1} must be an object")
    action = str(item.get("action") or "")
    if action not in ACTIONS:
        raise WakeHubError(f"step {index + 1} action must be wake, on, off, cycle, or shutdown")
    kind = str(item.get("target_kind") or "")
    if kind not in TARGET_KINDS:
        raise WakeHubError(f"step {index + 1} target must be a device, plug, roku, or tag")
    if kind != "tag" and action not in _SUPPORTS[kind]:
        raise WakeHubError(f"a {kind} cannot {action}")
    try:
        delay = float(item.get("delay_seconds") or 0)
    except (TypeError, ValueError) as exc:
        raise WakeHubError(f"step {index + 1} delay must be a number of seconds") from exc
    if delay < 0 or delay > 3600:
        raise WakeHubError(f"step {index + 1} delay must be between 0 and 3600 seconds")
    target_id = item.get("target_id")
    tags: list[str] = []
    if kind == "tag":
        tags = normalize_tags(list(item.get("tags") or []))
        if not tags:
            raise WakeHubError(f"step {index + 1} needs at least one tag")
        target_id = None
    else:
        if target_id is None:
            raise WakeHubError(f"step {index + 1} needs a {kind} id")
        target_id = int(target_id)
    return {
        "target_kind": kind,
        "target_id": target_id,
        "tags": tags,
        "action": action,
        "delay_seconds": delay,
    }


def _copy_name(hub: Hub, name: str) -> str:
    taken = {row["name"] for row in hub.query("SELECT name FROM salvos")}
    candidate = f"{name} copy"
    if candidate not in taken:
        return candidate
    number = 2
    while f"{name} copy {number}" in taken:
        number += 1
    return f"{name} copy {number}"
