import time

from wakehub.metrics import device_metrics, record


def test_scan_job_returns_discovered_hosts(client):
    from wakehub.hub import get_hub
    from wakehub.scan import start_scan

    def fake(cidr, progress):
        progress(1, 1)
        return [
            {
                "ip": "10.0.0.2",
                "mac": "AA:BB:CC:DD:EE:10",
                "hostname": "nas.local",
                "vendor": "Example",
                "kinds": ["wol", "shelly"],
                "detail": {},
            }
        ]

    scan_id = start_scan(get_hub(), "10.0.0.0/30", fake)["id"]
    deadline = time.monotonic() + 5
    body = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/scans/{scan_id}").json()
        if body["status"] == "done":
            break
        time.sleep(0.05)
    assert body["status"] == "done"
    assert body["hosts"][0]["kinds"] == ["wol", "shelly"]
    added = client.post(
        f"/api/v1/scans/{scan_id}/hosts/{body['hosts'][0]['id']}/add",
        json={"kind": "device", "name": "NAS"},
    )
    assert added.status_code == 201
    assert added.json()["mac"] == "AA:BB:CC:DD:EE:10"


def test_live_loopback_scan_finishes(client):
    created = client.post("/api/v1/scans", json={"cidr": "127.0.0.1/32"})
    scan_id = created.json()["id"]
    deadline = time.monotonic() + 20
    body = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/scans/{scan_id}").json()
        if body["status"] in {"done", "error"}:
            break
        time.sleep(0.2)
    assert body["status"] == "done"
    assert body["hosts"]
    assert body["hosts"][0]["ip"] == "127.0.0.1"


def test_metrics_round_trip_and_hidden_plug_secret(client, hub):
    created = client.post(
        "/api/v1/plugs",
        json={"name": "Lamp", "kind": "shelly", "host": "10.1.1.5", "password": "s3cret"},
    )
    assert created.status_code == 201
    assert "s3cret" not in created.text
    assert created.json()["password_set"] is True
    plug_id = created.json()["id"]
    record(hub, "plug", plug_id, None, [("power_w", 18.5, "W")])
    rows = client.get("/api/v1/metrics", params={"source_kind": "plug", "source_id": plug_id}).json()
    assert rows[0]["value"] == 18.5
    assert rows[0]["unit"] == "W"
    refused = client.post(f"/api/v1/plugs/{plug_id}/power", json={"action": "off", "confirm": False})
    assert refused.status_code == 409


def test_device_metrics_follow_a_linked_ups_sample(client, hub):
    device = client.post("/api/v1/devices", json={"name": "Tower", "mac": "00:11:22:33:44:55", "host": "10.0.0.8"}).json()
    record(hub, "ups", 3, device["id"], [("load_pct", 40, "%")])
    rows = device_metrics(hub, device["id"])
    assert rows[0]["metric"] == "load_pct"
