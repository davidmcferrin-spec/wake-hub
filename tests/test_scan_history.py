import time


def _wait(client, scan_id):
    deadline = time.monotonic() + 5
    body = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/scans/{scan_id}").json()
        if body["status"] in {"done", "error"}:
            return body
        time.sleep(0.05)
    return body


def test_scan_history_can_be_deleted_without_removing_devices(client, monkeypatch):
    def fake(_cidr, progress):
        progress(1, 1)
        return [{"ip": "10.1.0.2", "mac": None, "hostname": "", "vendor": "", "kinds": [], "detail": {}}]

    monkeypatch.setattr("wakehub.scan.discover_subnet", fake)
    device = client.post("/api/v1/devices", json={"name": "Desk", "mac": "02:00:00:00:00:61", "host": "10.1.0.9"})
    assert device.status_code == 201, device.text
    first = client.post("/api/v1/scans", json={"cidr": "10.1.0.0/30"})
    second = None
    assert _wait(client, first.json()["id"])["status"] == "done"
    second = client.post("/api/v1/scans", json={"cidr": "10.1.0.0/30"})
    assert _wait(client, second.json()["id"])["status"] == "done"

    removed = client.delete(f"/api/v1/scans/{first.json()['id']}")
    assert removed.status_code == 200, removed.text
    assert client.get(f"/api/v1/scans/{first.json()['id']}").status_code == 404
    assert client.get(f"/api/v1/devices/{device.json()['id']}").status_code == 200

    refused = client.post("/api/v1/scans/clear", json={"confirm": False})
    assert refused.status_code == 409
    assert client.get(f"/api/v1/scans/{second.json()['id']}").status_code == 200

    fresh = client.post(f"/api/v1/scans/{second.json()['id']}/rescan", json={"replace": False})
    assert fresh.status_code == 202, fresh.text
    assert fresh.json()["cidr"] == "10.1.0.0/30"
    assert _wait(client, fresh.json()["id"])["status"] == "done"
    assert client.get(f"/api/v1/scans/{second.json()['id']}").status_code == 200

    replaced = client.post(f"/api/v1/scans/{fresh.json()['id']}/rescan", json={"replace": True})
    assert replaced.status_code == 202, replaced.text
    assert _wait(client, replaced.json()["id"])["status"] == "done"
    assert client.get(f"/api/v1/scans/{second.json()['id']}").status_code == 404
    assert client.get(f"/api/v1/scans/{fresh.json()['id']}").status_code == 404
    assert client.get(f"/api/v1/devices/{device.json()['id']}").status_code == 200

    other = client.post("/api/v1/scans", json={"cidr": "10.1.0.4/30"})
    assert _wait(client, other.json()["id"])["status"] == "done"
    kept = client.patch("/api/v1/settings", json={"scan_keep": 1, "scan_keep_days": 0})
    assert kept.status_code == 200, kept.text
    listed = client.get("/api/v1/scans").json()
    assert len(listed) == 1
    assert client.get(f"/api/v1/devices/{device.json()['id']}").json()["name"] == "Desk"

    cleared = client.post("/api/v1/scans/clear", json={"confirm": True})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["removed"] >= 1
    assert client.get("/api/v1/scans").json() == []
    assert client.get(f"/api/v1/devices/{device.json()['id']}").status_code == 200


def _inventory(client):
    paths = {
        "devices": "/api/v1/devices",
        "pdus": "/api/v1/pdus",
        "amt": "/api/v1/amt",
        "jetkvm": "/api/v1/jetkvm",
        "plugs": "/api/v1/plugs",
        "ups": "/api/v1/ups",
        "rokus": "/api/v1/rokus",
    }
    snapshot = {}
    for name, path in paths.items():
        rows = client.get(path).json()
        snapshot[name] = sorted((row["id"], row["name"], row.get("host"), row.get("mac")) for row in rows)
    return snapshot


def test_deleting_scans_never_deletes_inventory_devices(client, monkeypatch):
    def fake(_cidr, progress):
        progress(1, 1)
        return [{"ip": "10.2.0.2", "mac": "02:00:00:00:00:77", "hostname": "den", "vendor": "", "kinds": [], "detail": {}}]

    monkeypatch.setattr("wakehub.scan.discover_subnet", fake)
    started = client.post("/api/v1/scans", json={"cidr": "10.2.0.0/30"})
    scan = _wait(client, started.json()["id"])
    added = client.post(f"/api/v1/scans/{scan['id']}/hosts/{scan['hosts'][0]['id']}/add", json={"kind": "device"})
    assert added.status_code == 201, added.text
    device = added.json()
    plug = client.post("/api/v1/plugs", json={"name": "Lamp", "kind": "shelly", "host": "10.2.0.3"})
    assert plug.status_code == 201, plug.text
    before = _inventory(client)
    assert (device["id"], "den", "10.2.0.2", "02:00:00:00:00:77") in before["devices"]

    removed = client.delete(f"/api/v1/scans/{scan['id']}")
    assert removed.status_code == 200, removed.text
    assert client.get(f"/api/v1/scans/{scan['id']}").status_code == 404
    assert _inventory(client) == before

    again = client.post("/api/v1/scans", json={"cidr": "10.2.0.0/30"})
    assert _wait(client, again.json()["id"])["status"] == "done"
    replaced = client.post(f"/api/v1/scans/{again.json()['id']}/rescan", json={"replace": True})
    assert replaced.status_code == 202, replaced.text
    assert _wait(client, replaced.json()["id"])["status"] == "done"
    assert _inventory(client) == before

    cleared = client.post("/api/v1/scans/clear", json={"confirm": True})
    assert cleared.status_code == 200, cleared.text
    assert client.get("/api/v1/scans").json() == []
    assert _inventory(client) == before
    kept = client.get(f"/api/v1/devices/{device['id']}")
    assert kept.status_code == 200
    assert kept.json()["mac"] == "02:00:00:00:00:77"
    assert kept.json()["host"] == "10.2.0.2"
