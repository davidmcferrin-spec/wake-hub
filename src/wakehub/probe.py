"""Check settings before they are saved. Nothing here writes inventory."""

from __future__ import annotations

from typing import Any

from wakehub.clients.amt import AmtClient
from wakehub.clients.jetkvm import JetKvmClient
from wakehub.clients.kasa import KasaClient
from wakehub.clients.shelly import ShellyClient
from wakehub.clients.roku import RokuClient
from wakehub.clients.synaccess import SynaccessClient
from wakehub.clients.ups import PysnmpTransport, UpsClient
from wakehub.credentials import profile_login
from wakehub.errors import WakeHubError
from wakehub.hub import Hub
from wakehub.inventory import validate_host
from wakehub.wol import build_magic_packet, normalize_mac, send_magic_packet, wait_until_reachable


def test_target(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "")
    try:
        if kind == "wol":
            return _wol(payload)
        if kind == "amt":
            return _amt(hub, payload)
        if kind == "pdu":
            return _pdu(hub, payload)
        if kind == "plug":
            return _plug(hub, payload)
        if kind == "jetkvm":
            return _jetkvm(hub, payload)
        if kind == "ups":
            return _ups(hub, payload)
        if kind == "roku":
            return _roku(payload)
        raise WakeHubError("kind must be wol, amt, pdu, plug, jetkvm, ups, or roku")
    except WakeHubError as exc:
        return {"ok": False, "kind": kind, "sent": False, "message": exc.message}


def _login(hub: Hub, payload: dict[str, Any]) -> tuple[str, str]:
    shared = profile_login(hub, payload.get("credential_profile_id"))
    if shared and not payload.get("password"):
        return shared
    return str(payload.get("username") or ""), str(payload.get("password") or "")


def _wol(payload: dict[str, Any]) -> dict[str, Any]:
    mac = normalize_mac(str(payload.get("mac") or ""))
    broadcast = str(payload.get("broadcast") or "255.255.255.255")
    validate_host(broadcast)
    if not payload.get("confirm"):
        return {
            "ok": True,
            "kind": "wol",
            "sent": False,
            "message": "MAC and broadcast are valid. Confirm to send the magic packet.",
        }
    packet = build_magic_packet(mac, None)
    port = int(payload.get("port") or 9)
    send_magic_packet(packet, broadcast, port)
    host = str(payload.get("host") or "")
    if not host:
        return {"ok": True, "kind": "wol", "sent": True, "message": "Packet sent. No host was given to watch."}
    reached, _elapsed = wait_until_reachable(host, "icmp", None, float(payload.get("timeout") or 5))
    return {
        "ok": bool(reached),
        "kind": "wol",
        "sent": True,
        "message": "Host answered." if reached else "Packet sent, host did not answer.",
    }


def _amt(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    username, password = _login(hub, payload)
    if not password:
        raise WakeHubError("AMT password is required")
    client = AmtClient(
        validate_host(str(payload.get("host") or "")),
        username or "admin",
        password,
        port=int(payload.get("port") or (16993 if payload.get("use_tls") else 16992)),
        use_tls=bool(payload.get("use_tls")),
        insecure_tls=bool(payload.get("insecure_tls")),
    )
    state = client.power_state()
    return {"ok": True, "kind": "amt", "sent": False, "message": f"AMT power state is {state.get('power_name') or 'unknown'}.", "detail": state}


def _pdu(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    username, password = _login(hub, payload)
    client = SynaccessClient(
        validate_host(str(payload.get("host") or "")),
        username or "admin",
        password,
        port=int(payload.get("port") or 80),
        use_tls=bool(payload.get("use_tls")),
        insecure_tls=bool(payload.get("insecure_tls")),
    )
    try:
        status = client.status()
    finally:
        client.close()
    return {"ok": True, "kind": "pdu", "sent": False, "message": f"PDU answered with {len(status.outlets)} outlets."}


def _plug(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    username, password = _login(hub, payload)
    host = validate_host(str(payload.get("host") or ""))
    plug_kind = str(payload.get("plug_kind") or "shelly")
    if plug_kind == "shelly":
        client = ShellyClient(host, username, password, port=int(payload.get("port") or 80), insecure_tls=bool(payload.get("insecure_tls")))
        status = client.status()
    elif plug_kind == "kasa":
        client = KasaClient(host, username, password, protocol=str(payload.get("protocol") or "auto"), port=int(payload.get("port") or 9999))
        status = client.status()
    else:
        raise WakeHubError("plug_kind must be shelly or kasa")
    state = "on" if status.get("on") else "off"
    return {"ok": True, "kind": "plug", "sent": False, "message": f"Plug answered and is {state}."}


def _jetkvm(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    _username, password = _login(hub, payload)
    client = JetKvmClient(
        validate_host(str(payload.get("host") or "")),
        password,
        port=int(payload.get("port") or (443 if payload.get("use_tls") else 80)),
        use_tls=bool(payload.get("use_tls")),
        insecure_tls=bool(payload.get("insecure_tls")),
    )
    try:
        info = client.reachable()
        if password:
            client.device()
    finally:
        client.close()
    mode = "password accepted" if password else "reachable without a password"
    return {"ok": True, "kind": "jetkvm", "sent": False, "message": f"JetKVM {mode}.", "detail": {"sku": info.get("sku") or ""}}


def _ups(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    username, password = _login(hub, payload)
    version = str(payload.get("snmp_version") or "2c")
    community = str(payload.get("community") or password or "public")
    transport = PysnmpTransport(
        validate_host(str(payload.get("host") or "")),
        int(payload.get("port") or 161),
        version,
        community,
        str(payload.get("v3_user") or username or ""),
        "sha",
        password or "",
        "aes",
        None,
    )
    client = UpsClient(transport)
    status = client.status()
    return {"ok": True, "kind": "ups", "sent": False, "message": f"UPS answered, output {status.get('output_status') or 'unknown'}."}


def _roku(payload: dict[str, Any]) -> dict[str, Any]:
    client = RokuClient(validate_host(str(payload.get("host") or "")), port=int(payload.get("port") or 8060))
    try:
        info = client.device_info()
    finally:
        client.close()
    name = info.get("name") or "Roku"
    model = info.get("model") or "unknown model"
    mode = info.get("power_mode") or "unknown"
    return {
        "ok": True,
        "kind": "roku",
        "sent": False,
        "message": f"{name} ({model}) is {mode}. Control by mobile apps must be enabled. Some models need network standby to power back on.",
        "detail": info,
    }
