"""Power actions shared by the UI, REST API and MCP."""

from __future__ import annotations

import json
import time
from typing import Any

from wakehub.clients.jetkvm import DESTRUCTIVE_ATX
from wakehub.clients.ups import DESTRUCTIVE as UPS_DESTRUCTIVE
from wakehub.clients.roku import KEYS as ROKU_KEYS
from wakehub.endpoints import (
    amt_client,
    jetkvm_client,
    list_plugs,
    list_rokus,
    outlet_labels,
    pdu_client,
    plug_client,
    refresh_pdu_outlet_names,
    roku_client,
    ups_client,
)
from wakehub.errors import ConfirmationRequired, WakeHubError, require_confirm
from wakehub.tags import has_tags, normalize_tags
from wakehub.hub import Hub
from wakehub.inventory import _get_row, _require_enabled, record_action, wake_device

PLUG_ACTIONS = {"on", "off", "toggle", "cycle"}
PDU_ACTIONS = {"on", "off", "reboot"}
DEVICE_ACTIONS = {"on", "off", "cycle", "reboot", "shutdown"}


def dispatch_device(
    hub: Hub,
    device_id: int,
    *,
    action: str,
    method: str = "auto",
    confirm: bool = False,
    source: str,
) -> dict[str, Any]:
    if action not in DEVICE_ACTIONS:
        raise WakeHubError("action must be on, off, cycle, reboot, or shutdown")
    require_confirm(action, confirm)
    row = _get_row(hub, device_id)
    _require_enabled(hub, row, source, action)
    chosen = _select_method(json.loads(row["methods"]), method, action)
    if chosen["kind"] == "wol":
        if action != "on":
            raise WakeHubError("Wake-on-LAN only supports action on")
        result = wake_device(hub, device_id, source=source)
        result["method"] = "wol"
        return result
    if chosen["kind"] == "pdu":
        mapped = {"on": "on", "off": "off", "cycle": "reboot", "reboot": "reboot"}.get(action)
        if mapped is None:
            raise WakeHubError(f"a PDU outlet cannot {action}")
        return set_pdu_outlet(hub, chosen["pdu_id"], chosen["outlet"], mapped, confirm=confirm, source=source)
    if chosen["kind"] == "plug":
        mapped = action if action in PLUG_ACTIONS else None
        if action == "cycle":
            mapped = "cycle"
        if action == "reboot":
            mapped = "cycle"
        if mapped is None:
            raise WakeHubError(f"a plug cannot {action}")
        return plug_power(hub, chosen["plug_id"], mapped, confirm=confirm, source=source)
    if chosen["kind"] == "amt":
        return amt_power(hub, chosen["amt_id"], action, confirm=confirm, source=source)
    if chosen["kind"] == "jetkvm":
        endpoint, client = jetkvm_client(hub, chosen["jetkvm_id"])
        client.close()
        if endpoint["extension"] == "dc-power" and action == "on":
            return jetkvm_power(hub, chosen["jetkvm_id"], "dc-on", confirm=confirm, source=source)
        if action == "on":
            state = jetkvm_status(hub, chosen["jetkvm_id"])
            atx = state.get("atx") or {}
            if "power_led" not in atx:
                raise WakeHubError("JetKVM power LED could not be read; refusing a press that might shut the machine down")
            if atx.get("power_led"):
                return {
                    "jetkvm_id": chosen["jetkvm_id"],
                    "action": "on",
                    "noop": True,
                    "reason": "power LED is already on",
                }
        jet_action = {"on": "power-short", "off": "power-long", "shutdown": "power-short", "reboot": "reset", "cycle": "reset"}.get(action)
        if jet_action is None:
            raise WakeHubError(f"JetKVM cannot {action}")
        return jetkvm_power(hub, chosen["jetkvm_id"], jet_action, confirm=confirm, source=source)
    if chosen["kind"] == "roku":
        mapped = {"on": "on", "off": "off"}.get(action)
        if mapped is None:
            raise WakeHubError(f"a Roku cannot {action}")
        return roku_power(hub, chosen["roku_id"], mapped, confirm=confirm, source=source)
    if chosen["kind"] == "ups":
        mapped = {"off": "turn_off", "shutdown": "shutdown", "reboot": "reboot", "cycle": "reboot", "on": "turn_on"}.get(action)
        if mapped is None:
            raise WakeHubError(f"a UPS cannot {action}")
        return ups_action(hub, chosen["ups_id"], mapped, confirm=confirm, source=source)
    raise WakeHubError(f"unknown power method {chosen['kind']}")


def _select_method(methods: list[dict[str, Any]], requested: str, action: str) -> dict[str, Any]:
    if requested == "auto":
        if action == "on":
            for kind in ("plug", "pdu", "amt", "ups", "jetkvm", "wol"):
                found = next((item for item in methods if item["kind"] == kind), None)
                if found:
                    return found
        else:
            for kind in ("amt", "plug", "pdu", "ups", "jetkvm"):
                found = next((item for item in methods if item["kind"] == kind), None)
                if found:
                    return found
        raise WakeHubError("device has no power method for that action")
    found = next((item for item in methods if item["kind"] == requested), None)
    if found is None:
        raise WakeHubError(f"device has no {requested} power method")
    return found


def power_on_linked(hub: Hub, row, source: str) -> None:
    for method in json.loads(row["methods"]):
        if method["kind"] == "plug":
            plug_power(hub, method["plug_id"], "on", confirm=False, source=source)
        elif method["kind"] == "pdu":
            set_pdu_outlet(hub, method["pdu_id"], method["outlet"], "on", confirm=False, source=source)


def set_pdu_outlet(hub: Hub, pdu_id: int, outlet: int, action: str, *, confirm: bool, source: str) -> dict[str, Any]:
    if action not in PDU_ACTIONS:
        raise WakeHubError("PDU action must be on, off, or reboot")
    if action in {"off", "reboot"}:
        require_confirm("off" if action == "off" else "reboot", confirm)
    row, client = pdu_client(hub, pdu_id)
    try:
        if action == "on":
            client.set_outlet(outlet, True)
        elif action == "off":
            client.set_outlet(outlet, False)
        else:
            client.reboot_outlet(outlet)
        detail = "ok"
        ok = True
    except Exception as exc:
        detail = str(exc)
        ok = False
        record_action(hub, source=source, action=f"pdu_{action}", ok=False, detail=detail, target_kind="pdu", target_id=pdu_id, target_name=row["name"])
        client.close()
        raise
    client.close()
    record_action(hub, source=source, action=f"pdu_{action}", ok=ok, detail=detail, target_kind="pdu", target_id=pdu_id, target_name=f"{row['name']} outlet {outlet}")
    return {"pdu_id": pdu_id, "outlet": outlet, "action": action, "ok": ok}


def list_pdu_outlets(hub: Hub, pdu_id: int) -> dict[str, Any]:
    try:
        refresh_pdu_outlet_names(hub, pdu_id)
    except Exception:
        pass
    row, client = pdu_client(hub, pdu_id)
    try:
        status = client.status(outlet_labels(row))
    finally:
        client.close()
    return {
        "pdu_id": pdu_id,
        "bank_amps": list(status.bank_amps),
        "temperature_c": status.temperature_c,
        "per_outlet_current": False,
        "outlets": [{"number": item.number, "name": item.name, "on": item.on} for item in status.outlets],
    }


def roku_status(hub: Hub, roku_id: int) -> dict[str, Any]:
    _row, client = roku_client(hub, roku_id)
    try:
        info = client.device_info()
    finally:
        client.close()
    return {"roku_id": roku_id, **info}


def roku_power(hub: Hub, roku_id: int, action: str, *, confirm: bool, source: str) -> dict[str, Any]:
    if action not in ROKU_KEYS:
        raise WakeHubError("Roku action must be on, off, or toggle")
    # PowerOff and Power can both turn the TV off.
    if action in {"off", "toggle"} and confirm is not True:
        raise ConfirmationRequired(f"{action} can turn the Roku off; set confirm to true")
    row, client = roku_client(hub, roku_id)
    try:
        client.keypress(ROKU_KEYS[action])
        info = client.device_info()
    except Exception as exc:
        record_action(hub, source=source, action=f"roku_{action}", ok=False, detail=str(exc), target_kind="roku", target_id=roku_id, target_name=row["name"])
        client.close()
        raise
    client.close()
    record_action(hub, source=source, action=f"roku_{action}", ok=True, detail=str(info.get("power_mode") or ""), target_kind="roku", target_id=roku_id, target_name=row["name"])
    return {"roku_id": roku_id, "action": action, "ok": True, **info}


def tag_action(hub: Hub, tags: list[str], action: str, *, confirm: bool, source: str) -> dict[str, Any]:
    wanted = normalize_tags(tags)
    if not wanted:
        raise WakeHubError("name at least one tag")
    if action not in {"wake", "on", "off"}:
        raise WakeHubError("tag action must be wake, on, or off")
    if confirm is not True:
        raise ConfirmationRequired("bulk tag actions need confirm set to true")
    from wakehub.inventory import list_devices

    results: list[dict[str, Any]] = []
    for device in list_devices(hub):
        if not has_tags(device["tags"], wanted):
            continue
        try:
            if action == "wake":
                wake_device(hub, device["id"], source=source)
            else:
                dispatch_device(hub, device["id"], action=action, confirm=True, source=source)
            results.append({"kind": "device", "id": device["id"], "name": device["name"], "ok": True, "detail": action})
        except Exception as exc:
            results.append({"kind": "device", "id": device["id"], "name": device["name"], "ok": False, "detail": str(exc)})
    if action in {"on", "off"}:
        for plug in list_plugs(hub):
            if not has_tags(plug["tags"], wanted):
                continue
            try:
                plug_power(hub, plug["id"], action, confirm=True, source=source)
                results.append({"kind": "plug", "id": plug["id"], "name": plug["name"], "ok": True, "detail": action})
            except Exception as exc:
                results.append({"kind": "plug", "id": plug["id"], "name": plug["name"], "ok": False, "detail": str(exc)})
        for roku in list_rokus(hub):
            if not has_tags(roku["tags"], wanted):
                continue
            try:
                roku_power(hub, roku["id"], action, confirm=True, source=source)
                results.append({"kind": "roku", "id": roku["id"], "name": roku["name"], "ok": True, "detail": action})
            except Exception as exc:
                results.append({"kind": "roku", "id": roku["id"], "name": roku["name"], "ok": False, "detail": str(exc)})
    return {"action": action, "tags": wanted, "matched": len(results), "results": results}


def plug_power(hub: Hub, plug_id: int, action: str, *, confirm: bool, source: str, cycle_seconds: float = 5) -> dict[str, Any]:
    if action not in PLUG_ACTIONS:
        raise WakeHubError("plug action must be on, off, toggle, or cycle")
    if action in {"off", "cycle"}:
        require_confirm("off" if action == "off" else "cycle", confirm)
    row, client = plug_client(hub, plug_id)
    try:
        if action == "toggle":
            current = client.status()
            if current.get("on"):
                require_confirm("off", confirm)
        if action == "on":
            result = client.set_on(True)
        elif action == "off":
            result = client.set_on(False)
        elif action == "toggle":
            if row["kind"] == "shelly":
                result = client.toggle()
            else:
                current = client.status()
                result = client.set_on(not bool(current.get("on")))
        else:
            client.set_on(False)
            time.sleep(cycle_seconds)
            result = client.set_on(True)
            result["cycled"] = True
    except Exception as exc:
        record_action(hub, source=source, action=f"plug_{action}", ok=False, detail=str(exc), target_kind="plug", target_id=plug_id, target_name=row["name"])
        raise
    record_action(hub, source=source, action=f"plug_{action}", ok=True, detail=action, target_kind="plug", target_id=plug_id, target_name=row["name"])
    result["plug_id"] = plug_id
    result["action"] = action
    return result


def plug_status(hub: Hub, plug_id: int) -> dict[str, Any]:
    row, client = plug_client(hub, plug_id)
    status = client.status()
    status["plug_id"] = plug_id
    status["kind"] = row["kind"]
    status["name"] = row["name"]
    return status


def amt_power(hub: Hub, amt_id: int, action: str, *, confirm: bool, source: str) -> dict[str, Any]:
    if action in {"off", "cycle", "reboot", "shutdown"}:
        require_confirm(action, confirm)
    row, client = amt_client(hub, amt_id)
    try:
        result = client.request_power(action)
    except Exception as exc:
        record_action(hub, source=source, action=f"amt_{action}", ok=False, detail=str(exc), target_kind="amt", target_id=amt_id, target_name=row["name"])
        raise
    record_action(hub, source=source, action=f"amt_{action}", ok=True, detail=action, target_kind="amt", target_id=amt_id, target_name=row["name"])
    result["amt_id"] = amt_id
    return result


def amt_state(hub: Hub, amt_id: int) -> dict[str, Any]:
    row, client = amt_client(hub, amt_id)
    state = client.power_state()
    state["amt_id"] = amt_id
    state["name"] = row["name"]
    return state


def jetkvm_power(hub: Hub, jetkvm_id: int, action: str, *, confirm: bool, source: str, extension: str = "auto") -> dict[str, Any]:
    if action in DESTRUCTIVE_ATX or action == "dc-off":
        require_confirm("off" if action in {"power-long", "dc-off"} else "reboot", confirm)
    row, client = jetkvm_client(hub, jetkvm_id)
    try:
        if action == "dc-on":
            result = client.dc_set(True)
        elif action == "dc-off":
            result = client.dc_set(False)
        elif extension == "dc-power" and action in {"power-short", "power-long"}:
            result = client.dc_set(action == "power-short")
        else:
            result = client.atx_action(action)
    except Exception as exc:
        record_action(hub, source=source, action=f"jetkvm_{action}", ok=False, detail=str(exc), target_kind="jetkvm", target_id=jetkvm_id, target_name=row["name"])
        client.close()
        raise
    client.close()
    record_action(hub, source=source, action=f"jetkvm_{action}", ok=True, detail=action, target_kind="jetkvm", target_id=jetkvm_id, target_name=row["name"])
    result["jetkvm_id"] = jetkvm_id
    result["console_url"] = client.console_url()
    return result


def jetkvm_status(hub: Hub, jetkvm_id: int) -> dict[str, Any]:
    row, client = jetkvm_client(hub, jetkvm_id)
    try:
        try:
            status = client.status()
        except Exception:
            status = client.reachable()
        status["name"] = row["name"]
        status["jetkvm_id"] = jetkvm_id
        status["console_url"] = client.console_url()
        return status
    finally:
        client.close()


def ups_action(hub: Hub, ups_id: int, action: str, *, confirm: bool, source: str, delay_seconds: int | None = None, outlet: int | None = None) -> dict[str, Any]:
    if action in UPS_DESTRUCTIVE:
        require_confirm("off" if action in {"shutdown", "turn_off", "sleep", "outlet_off"} else "reboot" if action in {"reboot", "outlet_cycle"} else "cycle", confirm)
        if action == "battery_test":
            require_confirm("cycle", confirm)
    row, client = ups_client(hub, ups_id)
    try:
        result = client.act(action, delay_seconds=delay_seconds, outlet=outlet)
    except Exception as exc:
        record_action(hub, source=source, action=f"ups_{action}", ok=False, detail=str(exc), target_kind="ups", target_id=ups_id, target_name=row["name"])
        raise
    record_action(hub, source=source, action=f"ups_{action}", ok=True, detail=action, target_kind="ups", target_id=ups_id, target_name=row["name"])
    result["ups_id"] = ups_id
    result["warning"] = "This can drop power to everything on the UPS." if action in UPS_DESTRUCTIVE else ""
    return result


def ups_status(hub: Hub, ups_id: int) -> dict[str, Any]:
    row, client = ups_client(hub, ups_id)
    status = client.status()
    status["ups_id"] = ups_id
    status["name"] = row["name"]
    return status
