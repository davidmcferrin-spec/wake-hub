from wakehub.controls import fold_linked_controls
from wakehub.scan import _attach_device


def test_linked_amt_becomes_one_device_and_stays_idempotent(client, hub):
    device = client.post(
        "/api/v1/devices",
        json={"name": "UNRAID", "mac": "02:00:00:00:00:97", "host": "192.168.0.97"},
    ).json()
    amt = client.post(
        "/api/v1/amt",
        json={"name": "UNRAID vPRO", "host": "192.168.0.41", "port": 16992, "password": "secret-amt", "device_id": device["id"]},
    ).json()
    secret = hub.query_one("SELECT password_enc FROM amt_endpoints WHERE id = ?", (amt["id"],))["password_enc"]
    fold_linked_controls(hub)
    fold_linked_controls(hub)
    body = client.get(f"/api/v1/devices/{device['id']}").json()
    assert [item["kind"] for item in body["methods"]] == ["amt", "wol"]
    assert body["methods"][0]["amt_id"] == amt["id"]
    assert body["priority"] == ["amt", "wol"]
    assert hub.query_one("SELECT password_enc FROM amt_endpoints WHERE id = ?", (amt["id"],))["password_enc"] == secret
    listed = client.get("/api/v1/amt").json()
    assert any(item["id"] == amt["id"] and item["name"] == "UNRAID vPRO" for item in listed)
    merges = [item for item in client.get("/api/v1/settings").json()["control_merges"] if item["hardware"] == "UNRAID vPRO"]
    assert len(merges) == 1
    assert merges[0]["into"] == "UNRAID"
    renamed = client.patch(f"/api/v1/devices/{device['id']}", json={"name": "UNRAID tower"})
    assert renamed.status_code == 200, renamed.text
    assert [item["kind"] for item in renamed.json()["methods"]] == ["amt", "wol"]


def test_wake_off_reset_and_cycle_use_the_same_priority(client, hub, monkeypatch):
    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:98", "host": "192.168.0.97"}).json()
    amt = client.post(
        "/api/v1/amt",
        json={"name": "UNRAID vPRO", "host": "192.168.0.41", "password": "secret-amt", "device_id": device["id"]},
    ).json()
    fold_linked_controls(hub)
    seen = []

    def fake_amt(_hub, amt_id, action, *, confirm, source):
        seen.append((amt_id, action, confirm))
        return {"ok": True, "action": action}

    monkeypatch.setattr("wakehub.power.amt_power", fake_amt)
    woken = client.post(f"/api/v1/devices/{device['id']}/wake", json={})
    assert woken.status_code == 200, woken.text
    off = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "off", "confirm": True})
    reset = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "reboot", "confirm": True})
    cycle = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "cycle", "confirm": True})
    assert off.status_code == 200 and reset.status_code == 200 and cycle.status_code == 200
    assert [item[1] for item in seen] == ["on", "off", "reboot", "cycle"]
    assert {item[0] for item in seen} == {amt["id"]}


def test_omitted_wake_timeout_follows_the_setting_later(client, hub):
    client.patch("/api/v1/settings", json={"default_wake_timeout": 12})
    created = client.post("/api/v1/devices", json={"name": "Later", "mac": "02:00:00:00:00:12", "host": "10.9.8.12"})
    assert created.json()["reach_timeout"] is None
    client.patch("/api/v1/settings", json={"default_wake_timeout": 18})
    from wakehub.inventory import _resolved_timeout, _get_row

    assert _resolved_timeout(hub, _get_row(hub, created.json()["id"]), None) == 18


def test_removed_amt_stays_removed_after_restart(client, hub):
    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:41", "host": "192.168.0.97"}).json()
    amt = client.post(
        "/api/v1/amt",
        json={"name": "UNRAID vPRO", "host": "192.168.0.41", "password": "secret-amt", "device_id": device["id"]},
    ).json()
    fold_linked_controls(hub)
    removed = client.patch(f"/api/v1/devices/{device['id']}", json={"methods": [{"kind": "wol"}]})
    assert removed.status_code == 200, removed.text
    assert [item["kind"] for item in removed.json()["methods"]] == ["wol"]
    assert hub.query_one("SELECT device_id FROM amt_endpoints WHERE id = ?", (amt["id"],))["device_id"] is None
    fold_linked_controls(hub)
    again = client.get(f"/api/v1/devices/{device['id']}").json()
    assert [item["kind"] for item in again["methods"]] == ["wol"]
    assert hub.query_one("SELECT device_id FROM amt_endpoints WHERE id = ?", (amt["id"],))["device_id"] is None


def test_meter_plug_does_not_outrank_wol(client, hub, monkeypatch):
    device = client.post("/api/v1/devices", json={"name": "Office PC", "mac": "02:00:00:00:00:42", "host": "192.168.0.42"}).json()
    plug = client.post(
        "/api/v1/plugs",
        json={"name": "Office meter", "kind": "shelly", "host": "192.168.0.43", "device_id": device["id"]},
    ).json()
    fold_linked_controls(hub)
    body = client.get(f"/api/v1/devices/{device['id']}").json()
    assert [item["kind"] for item in body["methods"]] == ["wol", "plug"]
    calls = []
    monkeypatch.setattr("wakehub.inventory.send_wake_packet", lambda *_args, **_kwargs: calls.append("wol") or {"ok": True, "name": "Office PC"})
    monkeypatch.setattr("wakehub.power.plug_power", lambda *_args, **_kwargs: calls.append("plug") or {"ok": True})
    woken = client.post(f"/api/v1/devices/{device['id']}/wake", json={})
    assert woken.status_code == 200, woken.text
    refused = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "off", "confirm": False})
    assert refused.status_code == 409
    assert calls == ["wol"]
    off = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "off", "confirm": True})
    assert off.status_code == 200, off.text
    assert calls == ["wol", "plug"]
    client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"methods": [{"kind": "plug", "plug_id": plug["id"]}, {"kind": "wol"}]},
    )
    fold_linked_controls(hub)
    kept = client.get(f"/api/v1/devices/{device['id']}").json()
    assert [item["kind"] for item in kept["methods"]] == ["plug", "wol"]


def test_off_prefers_amt_over_a_meter_plug(client, hub, monkeypatch):
    device = client.post("/api/v1/devices", json={"name": "Office PC", "mac": "02:00:00:00:00:44", "host": "192.168.0.44"}).json()
    amt = client.post("/api/v1/amt", json={"name": "Office AMT", "host": "192.168.0.45", "password": "secret-amt", "device_id": device["id"]}).json()
    plug = client.post("/api/v1/plugs", json={"name": "Office meter", "kind": "shelly", "host": "192.168.0.46", "device_id": device["id"]}).json()
    ordered = client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"methods": [{"kind": "plug", "plug_id": plug["id"]}, {"kind": "amt", "amt_id": amt["id"]}, {"kind": "wol"}]},
    )
    assert ordered.status_code == 200, ordered.text
    seen = []
    monkeypatch.setattr("wakehub.power.amt_power", lambda *_args, **_kwargs: seen.append(("amt", _args[2])) or {"ok": True})
    monkeypatch.setattr("wakehub.power.plug_power", lambda *_args, **_kwargs: seen.append(("plug", _args[2])) or {"ok": True})
    off = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "off", "confirm": True})
    chosen = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "off", "method": "plug", "confirm": True})
    assert off.status_code == 200 and chosen.status_code == 200
    assert seen == [("amt", "off"), ("plug", "off")]


def test_saving_a_method_updates_or_creates_the_hardware(client, hub, monkeypatch):
    from wakehub.crypto import decrypt

    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:47", "host": "192.168.0.97"}).json()
    amt = client.post(
        "/api/v1/amt",
        json={"name": "UNRAID vPRO", "host": "192.168.0.41", "password": "secret-amt", "device_id": device["id"]},
    ).json()
    other = client.post("/api/v1/amt", json={"name": "Other", "host": "10.1.1.1", "password": "secret-amt"}).json()
    saved = client.patch(
        f"/api/v1/devices/{device['id']}",
        json={
            "methods": [
                {
                    "kind": "amt",
                    "amt_id": amt["id"],
                    "host": "10.9.9.99",
                    "port": 16993,
                    "use_tls": True,
                    "username": "admin",
                    "password": "new-secret",
                },
                {"kind": "wol"},
                {"kind": "amt", "host": "10.9.9.100", "password": "created-secret", "port": 16992},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    kinds = [item["kind"] for item in saved.json()["methods"]]
    assert kinds == ["amt", "wol", "amt"]
    updated = next(item for item in client.get("/api/v1/amt").json() if item["id"] == amt["id"])
    assert updated["host"] == "10.9.9.99"
    assert updated["port"] == 16993
    assert updated["use_tls"] is True
    stored = hub.query_one("SELECT password_enc FROM amt_endpoints WHERE id = ?", (amt["id"],))
    assert decrypt(hub.cipher, stored["password_enc"]) == "new-secret"
    created_id = saved.json()["methods"][2]["amt_id"]
    created = next(item for item in client.get("/api/v1/amt").json() if item["id"] == created_id)
    assert created["host"] == "10.9.9.100"
    assert created["device_id"] == device["id"]
    kept = client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"methods": [{"kind": "amt", "amt_id": amt["id"], "host": "10.9.9.99", "password": ""}, {"kind": "wol"}]},
    )
    assert kept.status_code == 200, kept.text
    assert decrypt(hub.cipher, hub.query_one("SELECT password_enc FROM amt_endpoints WHERE id = ?", (amt["id"],))["password_enc"]) == "new-secret"
    duplicate = client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"methods": [{"kind": "amt", "amt_id": amt["id"], "host": other["host"]}, {"kind": "wol"}]},
    )
    assert duplicate.status_code == 409
    seen = []

    class Capture:
        def __init__(self, host, username, password, *, port=16992, use_tls=False, insecure_tls=False, timeout=15, poster=None):
            seen.append((host, password, port, use_tls))

        def request_power(self, action):
            return {"action": action, "ok": True}

    monkeypatch.setattr("wakehub.endpoints.AmtClient", Capture)
    powered = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "on", "method": "amt"})
    assert powered.status_code == 200, powered.text
    assert seen == [("10.9.9.99", "new-secret", 16993, True)]


def test_mcp_and_salvo_honor_method_order_and_override(client, hub, monkeypatch):
    import asyncio

    from wakehub.hub import set_hub
    from wakehub.mcp_server import build_server

    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:48", "host": "192.168.0.97"}).json()
    amt = client.post(
        "/api/v1/amt",
        json={"name": "UNRAID vPRO", "host": "192.168.0.41", "password": "secret-amt", "device_id": device["id"]},
    ).json()
    plug = client.post(
        "/api/v1/plugs",
        json={"name": "Meter", "kind": "shelly", "host": "192.168.0.49", "device_id": device["id"]},
    ).json()
    seen = []
    monkeypatch.setattr("wakehub.power.amt_power", lambda *_args, **_kwargs: seen.append(("amt", _args[2])) or {"ok": True})
    monkeypatch.setattr("wakehub.power.plug_power", lambda *_args, **_kwargs: seen.append(("plug", _args[2])) or {"ok": True})
    monkeypatch.setattr("wakehub.inventory.send_wake_packet", lambda *_args, **_kwargs: seen.append(("wol", "on")) or {"ok": True, "name": "UNRAID"})
    set_hub(hub)
    server = build_server()

    def call(name, arguments):
        return asyncio.run(server.call_tool(name, arguments))

    call("power_action", {"device_id": device["id"], "action": "on", "method": "auto"})
    call("power_action", {"device_id": device["id"], "action": "on", "method": "plug"})
    call("wake_device", {"device_id": device["id"], "method": "wol"})
    salvo = client.post(
        "/api/v1/salvos",
        json={
            "name": "Order",
            "steps": [
                {"target_kind": "device", "target_id": device["id"], "action": "wake"},
                {"target_kind": "device", "target_id": device["id"], "action": "wake", "method": "plug"},
                {"target_kind": "device", "target_id": device["id"], "action": "off", "method": "auto"},
                {"target_kind": "device", "target_id": device["id"], "action": "off", "method": "plug"},
            ],
        },
    )
    assert salvo.status_code == 201, salvo.text
    ran = client.post(f"/api/v1/salvos/{salvo.json()['id']}/run", json={"confirm": True})
    assert ran.status_code == 200, ran.text
    assert seen == [
        ("amt", "on"),
        ("plug", "on"),
        ("wol", "on"),
        ("amt", "on"),
        ("plug", "on"),
        ("amt", "off"),
        ("plug", "off"),
    ]
    assert amt["id"] and plug["id"]


def test_a_failed_save_does_not_keep_a_partial_method_change(client, hub):
    from wakehub.crypto import decrypt

    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:61", "host": "192.168.0.61"}).json()
    amt = client.post(
        "/api/v1/amt",
        json={"name": "UNRAID vPRO", "host": "192.168.0.62", "password": "secret-amt", "device_id": device["id"]},
    ).json()
    other = client.post("/api/v1/amt", json={"name": "Taken", "host": "10.9.9.50", "password": "secret-amt"}).json()
    taken = client.post("/api/v1/devices", json={"name": "Taken PC", "mac": "02:00:00:00:00:63", "host": "192.168.0.70"}).json()
    before = decrypt(hub.cipher, hub.query_one("SELECT password_enc FROM amt_endpoints WHERE id = ?", (amt["id"],))["password_enc"])
    duplicate = client.patch(
        f"/api/v1/devices/{device['id']}",
        json={
            "methods": [
                {"kind": "amt", "host": "10.8.8.8", "password": "created-secret", "port": 16992},
                {"kind": "amt", "amt_id": amt["id"], "host": other["host"], "password": "changed"},
                {"kind": "wol"},
            ]
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    listed = client.get("/api/v1/amt").json()
    assert not any(item["host"] == "10.8.8.8" for item in listed)
    kept = next(item for item in listed if item["id"] == amt["id"])
    assert kept["host"] == "192.168.0.62"
    assert decrypt(hub.cipher, hub.query_one("SELECT password_enc FROM amt_endpoints WHERE id = ?", (amt["id"],))["password_enc"]) == before
    conflict = client.patch(
        f"/api/v1/devices/{device['id']}",
        json={
            "host": taken["host"],
            "methods": [{"kind": "amt", "amt_id": amt["id"], "host": "10.7.7.7", "password": "nope"}, {"kind": "wol"}],
        },
    )
    assert conflict.status_code == 409, conflict.text
    after = next(item for item in client.get("/api/v1/amt").json() if item["id"] == amt["id"])
    assert after["host"] == "192.168.0.62"
    assert client.get(f"/api/v1/devices/{device['id']}").json()["host"] == "192.168.0.61"


def test_scan_offers_add_amt_to_the_matching_device(hub):
    hub.write(
        "INSERT INTO devices (name, mac, host, broadcast, wol_port, notes, tags, enabled, reach_mode, reach_timeout, reach_timeout_set, wake_strategy, power_method, methods, created_at, updated_at) VALUES ('UNRAID', '02:00:00:00:00:97', '192.168.0.97', '255.255.255.255', 9, '', '[]', 1, 'icmp', 30, 0, 'wol_only', 'auto', ?, 't', 't')",
        ('[{"kind":"wol"}]',),
    )
    attach = _attach_device(hub, {"type": "amt"}, "02:00:00:00:00:97", "unraid-vpro")
    assert attach["label"] == "Add AMT to UNRAID"
    by_name = _attach_device(hub, {"type": "amt"}, None, "UNRAID")
    assert by_name["name"] == "UNRAID"

