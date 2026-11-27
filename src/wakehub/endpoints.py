"""Stored PDU, AMT, JetKVM, plug and UPS endpoints. Passwords stay encrypted."""

from __future__ import annotations

import json
from typing import Any

from wakehub.clients.amt import AmtClient
from wakehub.clients.jetkvm import JetKvmClient
from wakehub.clients.kasa import KasaClient
from wakehub.clients.shelly import ShellyClient
from wakehub.clients.roku import RokuClient
from wakehub.clients.synaccess import SynaccessClient
from wakehub.clients.ups import PysnmpTransport, UpsClient
from wakehub.credentials import remember_profile
from wakehub.crypto import decrypt, encrypt
from wakehub.errors import NotFound, WakeHubError
from wakehub.identity import assert_available, bind_identity
from wakehub.tags import normalize_tags
from wakehub.hub import Hub
from wakehub.inventory import host_for_url, utcnow, validate_host

TABLES = {
    "pdu": "pdus",
    "amt": "amt_endpoints",
    "jetkvm": "jetkvm_endpoints",
    "plug": "plugs",
    "ups": "ups_cards",
    "roku": "rokus",
}


def _secret(hub: Hub, value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return encrypt(hub.cipher, value)


def _plain(hub: Hub, token: str | None) -> str:
    if not token:
        return ""
    return decrypt(hub.cipher, token)


def _row(hub: Hub, kind: str, item_id: int):
    row = hub.query_one(f"SELECT * FROM {TABLES[kind]} WHERE id = ?", (item_id,))
    if row is None:
        raise NotFound(f"{kind} {item_id} was not found")
    return row


def _stored_tags(row) -> list[str]:
    return json.loads(row["tags"] or "[]")


def _apply_tags(hub: Hub, table: str, item_id: int, payload: dict[str, Any]) -> None:
    if "tags" not in payload or payload["tags"] is None:
        return
    hub.write(f"UPDATE {table} SET tags = ? WHERE id = ?", (json.dumps(normalize_tags(payload["tags"])), item_id))


def _stamp(fields: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    fields["created_at"] = now
    fields["updated_at"] = now
    return fields


def public_pdu(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "use_tls": bool(row["use_tls"]),
        "insecure_tls": bool(row["insecure_tls"]),
        "username": row["username"],
        "password_set": bool(row["password_enc"]),
        "outlet_names": json.loads(row["outlet_names"] or "{}"),
        "device_outlet_names": json.loads(row["device_outlet_names"] or "{}"),
        "credential_profile_id": row["credential_profile_id"],
        "tags": _stored_tags(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_amt(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "use_tls": bool(row["use_tls"]),
        "insecure_tls": bool(row["insecure_tls"]),
        "username": row["username"],
        "password_set": bool(row["password_enc"]),
        "credential_profile_id": row["credential_profile_id"],
        "device_id": row["device_id"],
        "tags": _stored_tags(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_jetkvm(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "use_tls": bool(row["use_tls"]),
        "insecure_tls": bool(row["insecure_tls"]),
        "username": row["username"] or "",
        "password_set": bool(row["password_enc"]),
        "credential_profile_id": row["credential_profile_id"],
        "extension": row["extension"] or "",
        "poll_metrics": bool(row["poll_metrics"]),
        "device_id": row["device_id"],
        "console_url": _console(row),
        "tags": _stored_tags(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_plug(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "password_set": bool(row["password_enc"]),
        "insecure_tls": bool(row["insecure_tls"]),
        "protocol": row["protocol"],
        "switch_id": row["switch_id"],
        "credential_profile_id": row["credential_profile_id"],
        "device_id": row["device_id"],
        "tags": _stored_tags(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def public_ups(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "snmp_version": row["snmp_version"],
        "community_set": bool(row["community_enc"]),
        "v3_user": row["v3_user"],
        "v3_auth_proto": row["v3_auth_proto"],
        "v3_auth_set": bool(row["v3_auth_enc"]),
        "v3_priv_proto": row["v3_priv_proto"],
        "v3_priv_set": bool(row["v3_priv_enc"]),
        "credential_profile_id": row["credential_profile_id"],
        "device_id": row["device_id"],
        "tags": _stored_tags(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _console(row) -> str:
    scheme = "https" if row["use_tls"] else "http"
    return f"{scheme}://{host_for_url(row['host'])}:{row['port']}/"


def _updated_host(payload: dict[str, Any], current) -> str:
    raw = payload.get("host")
    if raw is None or str(raw).strip() == "":
        return current["host"]
    return validate_host(str(raw))


def _jet_extension(value: str | None) -> str:
    text = (value or "").strip()
    if text not in {"", "atx-power", "dc-power"}:
        raise WakeHubError("JetKVM extension must be atx-power, dc-power, or empty")
    return text


def _require_host(payload: dict[str, Any]) -> str:
    host = (payload.get("host") or "").strip()
    if not host:
        raise WakeHubError("host is required")
    return validate_host(host)


def _require_name(payload: dict[str, Any]) -> str:
    name = (payload.get("name") or "").strip()
    if not name:
        raise WakeHubError("name is required")
    return name


def list_pdus(hub: Hub) -> list[dict[str, Any]]:
    return [public_pdu(row) for row in hub.query("SELECT * FROM pdus ORDER BY name COLLATE NOCASE")]


def add_pdu(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    fields = _stamp(
        {
            "name": _require_name(payload),
            "host": _require_host(payload),
            "port": int(payload.get("port") or 80),
            "use_tls": 1 if payload.get("use_tls") else 0,
            "insecure_tls": 1 if payload.get("insecure_tls") else 0,
            "username": payload.get("username") or "admin",
            "password_enc": _secret(hub, payload.get("password")),
            "outlet_names": json.dumps(payload.get("outlet_names") or {}),
        }
    )
    assert_available(hub, "pdu", fields["host"])
    item_id = hub.write(
        """
        INSERT INTO pdus (name, host, port, use_tls, insecure_tls, username, password_enc, outlet_names, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(fields[key] for key in ("name", "host", "port", "use_tls", "insecure_tls", "username", "password_enc", "outlet_names", "created_at", "updated_at")),
    )
    bind_identity(hub, "pdu", item_id, fields["host"])
    remember_profile(hub, "pdus", item_id, payload)
    _apply_tags(hub, "pdus", item_id, payload)
    try:
        refresh_pdu_outlet_names(hub, item_id)
    except Exception:
        # Adding the record still succeeds when the PDU is offline or has no name API.
        pass
    return public_pdu(_row(hub, "pdu", item_id))


def update_pdu(hub: Hub, pdu_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _row(hub, "pdu", pdu_id)
    password = current["password_enc"]
    if "password" in payload:
        password = _secret(hub, payload.get("password"))
    names = payload.get("outlet_names")
    host = _updated_host(payload, current)
    assert_available(hub, "pdu", host, exclude_id=pdu_id)
    hub.write(
        """
        UPDATE pdus SET name=?, host=?, port=?, use_tls=?, insecure_tls=?, username=?, password_enc=?, outlet_names=?, updated_at=?
        WHERE id=?
        """,
        (
            payload.get("name") or current["name"],
            host,
            int(payload.get("port") if payload.get("port") is not None else current["port"]),
            int(payload["use_tls"]) if "use_tls" in payload else current["use_tls"],
            int(payload["insecure_tls"]) if "insecure_tls" in payload else current["insecure_tls"],
            payload.get("username") if payload.get("username") is not None else current["username"],
            password,
            json.dumps(names) if names is not None else current["outlet_names"],
            utcnow(),
            pdu_id,
        ),
    )
    bind_identity(hub, "pdu", pdu_id, host)
    remember_profile(hub, "pdus", pdu_id, payload)
    _apply_tags(hub, "pdus", pdu_id, payload)
    return public_pdu(_row(hub, "pdu", pdu_id))


def outlet_labels(row) -> dict[int, str]:
    # A name typed in Wake Hub replaces the name read from the PDU.
    merged: dict[int, str] = {}
    for raw in (row["device_outlet_names"], row["outlet_names"]):
        for key, value in json.loads(raw or "{}").items():
            if value is None or not str(value).strip():
                continue
            merged[int(key)] = str(value)
    return merged


def refresh_pdu_outlet_names(hub: Hub, pdu_id: int) -> dict[str, Any]:
    _row(hub, "pdu", pdu_id)
    row, client = pdu_client(hub, pdu_id)
    try:
        names = client.read_outlet_names()
    finally:
        client.close()
    stored = {str(number): label for number, label in sorted(names.items())}
    hub.write(
        "UPDATE pdus SET device_outlet_names = ?, updated_at = ? WHERE id = ?",
        (json.dumps(stored), utcnow(), pdu_id),
    )
    return public_pdu(_row(hub, "pdu", pdu_id))


def remove_pdu(hub: Hub, pdu_id: int) -> None:
    _row(hub, "pdu", pdu_id)
    from wakehub.removal import detach

    detach(hub, "pdu", pdu_id)
    hub.write("DELETE FROM pdus WHERE id = ?", (pdu_id,))


def _resolved_login(hub: Hub, row, username_key: str = "username", secret_key: str = "password_enc") -> tuple[str, str]:
    from wakehub.credentials import profile_login

    profile_id = row["credential_profile_id"]
    if profile_id:
        try:
            shared = profile_login(hub, int(profile_id))
        except NotFound:
            # The saved login was removed. The device's own username and password still work.
            shared = None
        if shared and shared[1]:
            return shared[0] or str(row[username_key] or ""), shared[1]
    return str(row[username_key] or ""), _plain(hub, row[secret_key])


def pdu_client(hub: Hub, pdu_id: int) -> tuple[Any, SynaccessClient]:
    row = _row(hub, "pdu", pdu_id)
    username, password = _resolved_login(hub, row)
    client = SynaccessClient(
        row["host"],
        username,
        password,
        port=row["port"],
        use_tls=bool(row["use_tls"]),
        insecure_tls=bool(row["insecure_tls"]),
    )
    return row, client


def list_amt(hub: Hub) -> list[dict[str, Any]]:
    return [public_amt(row) for row in hub.query("SELECT * FROM amt_endpoints ORDER BY name COLLATE NOCASE")]


def add_amt(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("password"):
        raise WakeHubError("AMT password is required")
    fields = _stamp(
        {
            "name": _require_name(payload),
            "host": _require_host(payload),
            "port": int(payload.get("port") or (16993 if payload.get("use_tls") else 16992)),
            "use_tls": 1 if payload.get("use_tls") else 0,
            "insecure_tls": 1 if payload.get("insecure_tls") else 0,
            "username": payload.get("username") or "admin",
            "password_enc": _secret(hub, payload.get("password")),
            "device_id": payload.get("device_id"),
        }
    )
    assert_available(hub, "amt", fields["host"])
    item_id = hub.write(
        """
        INSERT INTO amt_endpoints (
            name, host, port, use_tls, insecure_tls, username, password_enc, device_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["name"],
            fields["host"],
            fields["port"],
            fields["use_tls"],
            fields["insecure_tls"],
            fields["username"],
            fields["password_enc"],
            fields["device_id"],
            fields["created_at"],
            fields["updated_at"],
        ),
    )
    _link(hub, fields["device_id"], {"kind": "amt", "amt_id": item_id})
    bind_identity(hub, "amt", item_id, fields["host"])
    remember_profile(hub, "amt_endpoints", item_id, payload)
    _apply_tags(hub, "amt_endpoints", item_id, payload)
    return public_amt(_row(hub, "amt", item_id))


def update_amt(hub: Hub, amt_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _row(hub, "amt", amt_id)
    password = current["password_enc"] if "password" not in payload else _secret(hub, payload.get("password"))
    if password is None:
        raise WakeHubError("AMT password is required")
    host = _updated_host(payload, current)
    assert_available(hub, "amt", host, exclude_id=amt_id)
    hub.write(
        """
        UPDATE amt_endpoints
        SET name=?, host=?, port=?, use_tls=?, insecure_tls=?, username=?, password_enc=?, device_id=?, updated_at=?
        WHERE id=?
        """,
        (
            payload.get("name") or current["name"],
            host,
            int(payload.get("port") if payload.get("port") is not None else current["port"]),
            int(payload["use_tls"]) if "use_tls" in payload else current["use_tls"],
            int(payload["insecure_tls"]) if "insecure_tls" in payload else current["insecure_tls"],
            payload.get("username") or current["username"],
            password,
            payload["device_id"] if "device_id" in payload else current["device_id"],
            utcnow(),
            amt_id,
        ),
    )
    bind_identity(hub, "amt", amt_id, host)
    remember_profile(hub, "amt_endpoints", amt_id, payload)
    _apply_tags(hub, "amt_endpoints", amt_id, payload)
    return public_amt(_row(hub, "amt", amt_id))


def remove_amt(hub: Hub, amt_id: int) -> None:
    _row(hub, "amt", amt_id)
    from wakehub.removal import detach

    detach(hub, "amt", amt_id)
    hub.write("DELETE FROM amt_endpoints WHERE id = ?", (amt_id,))


def amt_client(hub: Hub, amt_id: int) -> tuple[Any, AmtClient]:
    row = _row(hub, "amt", amt_id)
    username, password = _resolved_login(hub, row)
    client = AmtClient(
        row["host"],
        username or "admin",
        password,
        port=row["port"],
        use_tls=bool(row["use_tls"]),
        insecure_tls=bool(row["insecure_tls"]),
    )
    return row, client


def list_jetkvm(hub: Hub) -> list[dict[str, Any]]:
    return [public_jetkvm(row) for row in hub.query("SELECT * FROM jetkvm_endpoints ORDER BY name COLLATE NOCASE")]


def add_jetkvm(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    fields = _stamp(
        {
            "name": _require_name(payload),
            "host": _require_host(payload),
            "port": int(payload.get("port") or (443 if payload.get("use_tls") else 80)),
            "use_tls": 1 if payload.get("use_tls") else 0,
            "insecure_tls": 1 if payload.get("insecure_tls") else 0,
            "username": str(payload.get("username") or ""),
            "password_enc": _secret(hub, payload.get("password")),
            "extension": _jet_extension(payload.get("extension")),
            "poll_metrics": 1 if payload.get("poll_metrics") else 0,
            "device_id": payload.get("device_id"),
        }
    )
    assert_available(hub, "jetkvm", fields["host"])
    item_id = hub.write(
        """
        INSERT INTO jetkvm_endpoints (
            name, host, port, use_tls, insecure_tls, username, password_enc, extension, poll_metrics, device_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["name"],
            fields["host"],
            fields["port"],
            fields["use_tls"],
            fields["insecure_tls"],
            fields["username"],
            fields["password_enc"],
            fields["extension"],
            fields["poll_metrics"],
            fields["device_id"],
            fields["created_at"],
            fields["updated_at"],
        ),
    )
    _link(hub, fields["device_id"], {"kind": "jetkvm", "jetkvm_id": item_id})
    bind_identity(hub, "jetkvm", item_id, fields["host"])
    remember_profile(hub, "jetkvm_endpoints", item_id, payload)
    _apply_tags(hub, "jetkvm_endpoints", item_id, payload)
    return public_jetkvm(_row(hub, "jetkvm", item_id))


def update_jetkvm(hub: Hub, jetkvm_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _row(hub, "jetkvm", jetkvm_id)
    password = current["password_enc"] if "password" not in payload else _secret(hub, payload.get("password"))
    extension = _jet_extension(payload["extension"]) if "extension" in payload else (current["extension"] or "")
    poll_metrics = (1 if payload.get("poll_metrics") else 0) if "poll_metrics" in payload else current["poll_metrics"]
    host = _updated_host(payload, current)
    assert_available(hub, "jetkvm", host, exclude_id=jetkvm_id)
    hub.write(
        """
        UPDATE jetkvm_endpoints
        SET name=?, host=?, port=?, use_tls=?, insecure_tls=?, username=?, password_enc=?, extension=?, poll_metrics=?, device_id=?, updated_at=?
        WHERE id=?
        """,
        (
            payload.get("name") or current["name"],
            host,
            int(payload.get("port") if payload.get("port") is not None else current["port"]),
            int(payload["use_tls"]) if "use_tls" in payload else current["use_tls"],
            int(payload["insecure_tls"]) if "insecure_tls" in payload else current["insecure_tls"],
            payload.get("username") if payload.get("username") is not None else (current["username"] or ""),
            password,
            extension,
            poll_metrics,
            payload["device_id"] if "device_id" in payload else current["device_id"],
            utcnow(),
            jetkvm_id,
        ),
    )
    bind_identity(hub, "jetkvm", jetkvm_id, host)
    remember_profile(hub, "jetkvm_endpoints", jetkvm_id, payload)
    _apply_tags(hub, "jetkvm_endpoints", jetkvm_id, payload)
    return public_jetkvm(_row(hub, "jetkvm", jetkvm_id))


def remove_jetkvm(hub: Hub, jetkvm_id: int) -> None:
    _row(hub, "jetkvm", jetkvm_id)
    from wakehub.removal import detach

    detach(hub, "jetkvm", jetkvm_id)
    hub.write("DELETE FROM jetkvm_endpoints WHERE id = ?", (jetkvm_id,))


def jetkvm_client(hub: Hub, jetkvm_id: int, rpc=None) -> tuple[Any, JetKvmClient]:
    row = _row(hub, "jetkvm", jetkvm_id)
    _username, password = _resolved_login(hub, row)
    client = JetKvmClient(
        row["host"],
        password,
        port=row["port"],
        use_tls=bool(row["use_tls"]),
        insecure_tls=bool(row["insecure_tls"]),
        rpc=rpc,
    )
    return row, client


def list_plugs(hub: Hub) -> list[dict[str, Any]]:
    return [public_plug(row) for row in hub.query("SELECT * FROM plugs ORDER BY name COLLATE NOCASE")]


def add_plug(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    kind = payload.get("kind")
    if kind not in {"shelly", "kasa"}:
        raise WakeHubError("plug kind must be shelly or kasa")
    protocol = payload.get("protocol") or "auto"
    if kind == "kasa" and protocol not in {"auto", "xor", "klap"}:
        raise WakeHubError("Kasa protocol must be auto, xor, or klap")
    fields = _stamp(
        {
            "name": _require_name(payload),
            "kind": kind,
            "host": _require_host(payload),
            "port": int(payload.get("port") or 80),
            "username": payload.get("username") or "",
            "password_enc": _secret(hub, payload.get("password")),
            "insecure_tls": 1 if payload.get("insecure_tls") else 0,
            "protocol": protocol,
            "switch_id": int(payload.get("switch_id") or 0),
            "device_id": payload.get("device_id"),
        }
    )
    assert_available(hub, "plug", fields["host"])
    item_id = hub.write(
        """
        INSERT INTO plugs (
            name, kind, host, port, username, password_enc, insecure_tls, protocol, switch_id, device_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["name"],
            fields["kind"],
            fields["host"],
            fields["port"],
            fields["username"],
            fields["password_enc"],
            fields["insecure_tls"],
            fields["protocol"],
            fields["switch_id"],
            fields["device_id"],
            fields["created_at"],
            fields["updated_at"],
        ),
    )
    _link(hub, fields["device_id"], {"kind": "plug", "plug_id": item_id})
    bind_identity(hub, "plug", item_id, fields["host"])
    remember_profile(hub, "plugs", item_id, payload)
    _apply_tags(hub, "plugs", item_id, payload)
    return public_plug(_row(hub, "plug", item_id))


def update_plug(hub: Hub, plug_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _row(hub, "plug", plug_id)
    password = current["password_enc"] if "password" not in payload else _secret(hub, payload.get("password"))
    kind = payload.get("kind") or current["kind"]
    if kind not in {"shelly", "kasa"}:
        raise WakeHubError("plug kind must be shelly or kasa")
    host = _updated_host(payload, current)
    assert_available(hub, "plug", host, exclude_id=plug_id)
    hub.write(
        """
        UPDATE plugs
        SET name=?, kind=?, host=?, port=?, username=?, password_enc=?, insecure_tls=?, protocol=?, switch_id=?, device_id=?, updated_at=?
        WHERE id=?
        """,
        (
            payload.get("name") or current["name"],
            kind,
            host,
            int(payload.get("port") if payload.get("port") is not None else current["port"]),
            payload.get("username") if payload.get("username") is not None else current["username"],
            password,
            int(payload["insecure_tls"]) if "insecure_tls" in payload else current["insecure_tls"],
            payload.get("protocol") or current["protocol"],
            int(payload.get("switch_id") if payload.get("switch_id") is not None else current["switch_id"]),
            payload["device_id"] if "device_id" in payload else current["device_id"],
            utcnow(),
            plug_id,
        ),
    )
    bind_identity(hub, "plug", plug_id, host)
    remember_profile(hub, "plugs", plug_id, payload)
    _apply_tags(hub, "plugs", plug_id, payload)
    return public_plug(_row(hub, "plug", plug_id))


def remove_plug(hub: Hub, plug_id: int) -> None:
    _row(hub, "plug", plug_id)
    from wakehub.removal import detach

    detach(hub, "plug", plug_id)
    hub.write("DELETE FROM plugs WHERE id = ?", (plug_id,))


def plug_client(hub: Hub, plug_id: int):
    row = _row(hub, "plug", plug_id)
    username, password = _resolved_login(hub, row)
    if row["kind"] == "shelly":
        client = ShellyClient(
            row["host"],
            username,
            password,
            port=row["port"],
            switch_id=row["switch_id"],
            insecure_tls=bool(row["insecure_tls"]),
        )
    elif row["kind"] == "kasa":
        client = KasaClient(row["host"], username, password, protocol=row["protocol"], port=row["port"])
    else:
        raise WakeHubError(f"unknown plug kind {row['kind']}")
    return row, client


def list_ups(hub: Hub) -> list[dict[str, Any]]:
    return [public_ups(row) for row in hub.query("SELECT * FROM ups_cards ORDER BY name COLLATE NOCASE")]


def add_ups(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    version = str(payload.get("snmp_version") or "2c")
    if version not in {"1", "2c", "3"}:
        raise WakeHubError("SNMP version must be 1, 2c, or 3")
    fields = _stamp(
        {
            "name": _require_name(payload),
            "host": _require_host(payload),
            "port": int(payload.get("port") or 161),
            "snmp_version": version,
            "community_enc": _secret(hub, payload.get("community") or "public"),
            "v3_user": payload.get("v3_user") or "",
            "v3_auth_proto": payload.get("v3_auth_proto") or "sha",
            "v3_auth_enc": _secret(hub, payload.get("v3_auth")),
            "v3_priv_proto": payload.get("v3_priv_proto") or "aes",
            "v3_priv_enc": _secret(hub, payload.get("v3_priv")),
            "device_id": payload.get("device_id"),
        }
    )
    assert_available(hub, "ups", fields["host"])
    item_id = hub.write(
        """
        INSERT INTO ups_cards (
            name, host, port, snmp_version, community_enc, v3_user, v3_auth_proto, v3_auth_enc,
            v3_priv_proto, v3_priv_enc, device_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["name"],
            fields["host"],
            fields["port"],
            fields["snmp_version"],
            fields["community_enc"],
            fields["v3_user"],
            fields["v3_auth_proto"],
            fields["v3_auth_enc"],
            fields["v3_priv_proto"],
            fields["v3_priv_enc"],
            fields["device_id"],
            fields["created_at"],
            fields["updated_at"],
        ),
    )
    _link(hub, fields["device_id"], {"kind": "ups", "ups_id": item_id})
    bind_identity(hub, "ups", item_id, fields["host"])
    remember_profile(hub, "ups_cards", item_id, payload)
    _apply_tags(hub, "ups_cards", item_id, payload)
    return public_ups(_row(hub, "ups", item_id))


def update_ups(hub: Hub, ups_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _row(hub, "ups", ups_id)
    version = payload.get("snmp_version") or current["snmp_version"]
    if version not in {"1", "2c", "3"}:
        raise WakeHubError("SNMP version must be 1, 2c, or 3")
    host = _updated_host(payload, current)
    assert_available(hub, "ups", host, exclude_id=ups_id)
    hub.write(
        """
        UPDATE ups_cards SET
            name=?, host=?, port=?, snmp_version=?, community_enc=?, v3_user=?, v3_auth_proto=?,
            v3_auth_enc=?, v3_priv_proto=?, v3_priv_enc=?, device_id=?, updated_at=?
        WHERE id=?
        """,
        (
            payload.get("name") or current["name"],
            host,
            int(payload.get("port") if payload.get("port") is not None else current["port"]),
            version,
            current["community_enc"] if "community" not in payload else _secret(hub, payload.get("community")),
            payload.get("v3_user") if payload.get("v3_user") is not None else current["v3_user"],
            payload.get("v3_auth_proto") or current["v3_auth_proto"],
            current["v3_auth_enc"] if "v3_auth" not in payload else _secret(hub, payload.get("v3_auth")),
            payload.get("v3_priv_proto") or current["v3_priv_proto"],
            current["v3_priv_enc"] if "v3_priv" not in payload else _secret(hub, payload.get("v3_priv")),
            payload["device_id"] if "device_id" in payload else current["device_id"],
            utcnow(),
            ups_id,
        ),
    )
    bind_identity(hub, "ups", ups_id, host)
    remember_profile(hub, "ups_cards", ups_id, payload)
    _apply_tags(hub, "ups_cards", ups_id, payload)
    return public_ups(_row(hub, "ups", ups_id))


def remove_ups(hub: Hub, ups_id: int) -> None:
    _row(hub, "ups", ups_id)
    from wakehub.removal import detach

    detach(hub, "ups", ups_id)
    hub.write("DELETE FROM ups_cards WHERE id = ?", (ups_id,))


def ups_client(hub: Hub, ups_id: int) -> tuple[Any, UpsClient]:
    row = _row(hub, "ups", ups_id)
    from wakehub.credentials import profile_login

    community = _plain(hub, row["community_enc"]) or "public"
    v3_user = row["v3_user"]
    v3_auth = _plain(hub, row["v3_auth_enc"])
    if row["credential_profile_id"]:
        shared = profile_login(hub, int(row["credential_profile_id"]))
        if shared:
            if shared[0]:
                v3_user = shared[0]
            if shared[1] and row["snmp_version"] == "3":
                v3_auth = shared[1]
            elif shared[1]:
                community = shared[1]
    transport = PysnmpTransport(
        row["host"],
        row["port"],
        row["snmp_version"],
        community,
        v3_user,
        row["v3_auth_proto"],
        v3_auth,
        row["v3_priv_proto"],
        _plain(hub, row["v3_priv_enc"]),
    )
    return row, UpsClient(transport)


def public_roku(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "device_id": row["device_id"],
        "tags": _stored_tags(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_rokus(hub: Hub) -> list[dict[str, Any]]:
    return [public_roku(row) for row in hub.query("SELECT * FROM rokus ORDER BY name COLLATE NOCASE")]


def add_roku(hub: Hub, payload: dict[str, Any]) -> dict[str, Any]:
    fields = _stamp(
        {
            "name": _require_name(payload),
            "host": _require_host(payload),
            "port": int(payload.get("port") or 8060),
            "device_id": payload.get("device_id"),
            "tags": json.dumps(normalize_tags(payload.get("tags"))),
        }
    )
    assert_available(hub, "roku", fields["host"])
    item_id = hub.write(
        """
        INSERT INTO rokus (name, host, port, device_id, tags, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (fields["name"], fields["host"], fields["port"], fields["device_id"], fields["tags"], fields["created_at"], fields["updated_at"]),
    )
    _link(hub, fields["device_id"], {"kind": "roku", "roku_id": item_id})
    bind_identity(hub, "roku", item_id, fields["host"])
    return public_roku(_row(hub, "roku", item_id))


def update_roku(hub: Hub, roku_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = _row(hub, "roku", roku_id)
    host = _updated_host(payload, current)
    assert_available(hub, "roku", host, exclude_id=roku_id)
    hub.write(
        """
        UPDATE rokus SET name=?, host=?, port=?, device_id=?, updated_at=? WHERE id=?
        """,
        (
            payload.get("name") or current["name"],
            host,
            int(payload.get("port") if payload.get("port") is not None else current["port"]),
            payload["device_id"] if "device_id" in payload else current["device_id"],
            utcnow(),
            roku_id,
        ),
    )
    _apply_tags(hub, "rokus", roku_id, payload)
    bind_identity(hub, "roku", roku_id, host)
    return public_roku(_row(hub, "roku", roku_id))


def remove_roku(hub: Hub, roku_id: int) -> None:
    _row(hub, "roku", roku_id)
    from wakehub.removal import detach

    detach(hub, "roku", roku_id)
    hub.write("DELETE FROM rokus WHERE id = ?", (roku_id,))


def roku_client(hub: Hub, roku_id: int) -> tuple[Any, RokuClient]:
    row = _row(hub, "roku", roku_id)
    return row, RokuClient(row["host"], port=row["port"])


def _link(hub: Hub, device_id: int | None, method: dict[str, Any]) -> None:
    if not device_id:
        return
    from wakehub.inventory import get_device, normalize_methods, update_device

    device = get_device(hub, int(device_id))
    methods = list(device["methods"])
    if method not in methods:
        methods.append(method)
    update_device(hub, int(device_id), {"methods": normalize_methods(methods)})
