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


def test_restart_clears_a_scan_left_running(tmp_path):
    from wakehub.config import Settings
    from wakehub.hub import Hub
    from wakehub.inventory import utcnow
    from wakehub.scan import start_scan

    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        host="127.0.0.1",
        port=0,
        secret_key="test-secret",
        cors_origins=(),
    )
    first = Hub.open(settings)
    first.write(
        "INSERT INTO scans (cidr, status, progress, total, message, created_at) VALUES (?, 'running', 0, 1, '', ?)",
        ("10.0.0.0/30", utcnow()),
    )
    first.close()
    second = Hub.open(settings)
    abandoned = second.query_one("SELECT status, message FROM scans")
    assert abandoned["status"] == "error"
    assert abandoned["message"] == "interrupted by restart"

    def fake(_cidr, progress):
        progress(1, 1)
        return []

    started = start_scan(second, "10.0.0.0/30", fake)
    deadline = time.monotonic() + 5
    status = started["status"]
    while time.monotonic() < deadline and status == "running":
        status = second.query_one("SELECT status FROM scans WHERE id = ?", (started["id"],))["status"]
        time.sleep(0.05)
    assert status == "done"
    second.close()


def test_endpoint_updates_reject_a_bad_host(client):
    specs = [
        ("/api/v1/pdus", {"name": "Rack", "host": "10.0.0.5"}),
        ("/api/v1/amt", {"name": "Amt", "host": "10.0.0.6", "password": "secret"}),
        ("/api/v1/jetkvm", {"name": "Kvm", "host": "10.0.0.7"}),
        ("/api/v1/plugs", {"name": "Plug", "host": "10.0.0.8", "kind": "shelly"}),
        ("/api/v1/ups", {"name": "Ups", "host": "10.0.0.9"}),
    ]
    for path, body in specs:
        created = client.post(path, json=body)
        assert created.status_code == 201, created.text
        updated = client.patch(f"{path}/{created.json()['id']}", json={"host": "-bad"})
        assert updated.status_code == 400, updated.text
        assert "host" in updated.json()["error"]["message"]


def test_jetkvm_metrics_wait_for_an_opt_in(hub, monkeypatch):
    from wakehub.endpoints import add_jetkvm, update_jetkvm
    from wakehub.metrics import collect_once, query_metrics

    calls = []

    def status(_hub, jetkvm_id):
        calls.append(jetkvm_id)
        return {"dc": {"voltage_v": 12.1, "current_a": 0.4, "power_w": 4.8}}

    monkeypatch.setattr("wakehub.power.jetkvm_status", status)
    quiet = add_jetkvm(hub, {"name": "Quiet", "host": "10.2.2.2"})
    assert collect_once(hub) == 0
    assert calls == []
    update_jetkvm(hub, quiet["id"], {"poll_metrics": True})
    assert collect_once(hub) == 0
    assert calls == []
    update_jetkvm(hub, quiet["id"], {"extension": "dc-power", "poll_metrics": True})
    assert collect_once(hub) == 3
    assert calls == [quiet["id"]]
    rows = query_metrics(hub, source_kind="jetkvm", source_id=quiet["id"])
    assert {row["metric"] for row in rows} == {"voltage_v", "current_a", "power_w"}


def test_ipv6_hosts_are_bracketed_in_urls():
    from wakehub.clients.jetkvm import JetKvmClient
    from wakehub.endpoints import _console

    assert JetKvmClient("2001:db8::1").base == "http://[2001:db8::1]:80"
    assert _console({"use_tls": 1, "host": "2001:db8::5", "port": 443}) == "https://[2001:db8::5]:443/"


def test_device_metrics_follow_a_linked_ups_sample(client, hub):
    device = client.post("/api/v1/devices", json={"name": "Tower", "mac": "00:11:22:33:44:55", "host": "10.0.0.8"}).json()
    record(hub, "ups", 3, device["id"], [("load_pct", 40, "%")])
    rows = device_metrics(hub, device["id"])
    assert rows[0]["metric"] == "load_pct"
