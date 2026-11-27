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


def test_scan_offers_add_amt_to_the_matching_device(hub):
    hub.write(
        "INSERT INTO devices (name, mac, host, broadcast, wol_port, notes, tags, enabled, reach_mode, reach_timeout, reach_timeout_set, wake_strategy, power_method, methods, created_at, updated_at) VALUES ('UNRAID', '02:00:00:00:00:97', '192.168.0.97', '255.255.255.255', 9, '', '[]', 1, 'icmp', 30, 0, 'wol_only', 'auto', ?, 't', 't')",
        ('[{"kind":"wol"}]',),
    )
    attach = _attach_device(hub, {"type": "amt"}, "02:00:00:00:00:97", "unraid-vpro")
    assert attach["label"] == "Add AMT to UNRAID"
    by_name = _attach_device(hub, {"type": "amt"}, None, "UNRAID")
    assert by_name["name"] == "UNRAID"

