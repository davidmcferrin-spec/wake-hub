import asyncio
import json

from wakehub.config import Settings
from wakehub.endpoints import add_pdu, add_plug
from wakehub.hub import Hub, set_hub
from wakehub.inventory import add_device
from wakehub.salvos import add_salvo
from wakehub.tags import normalize_tags


def _settings(tmp_path) -> Settings:
    return Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        host="127.0.0.1",
        port=0,
        secret_key="test-secret",
        cors_origins=(),
    )


def _close(hub: Hub) -> None:
    hub.stop_background()
    hub.join_background(timeout=5)
    hub.close()


def test_a_later_spelling_uses_the_one_saved_first():
    assert normalize_tags(["OFFICE", "office"], {"office": "Office"}) == ["Office"]
    assert normalize_tags(["#Office", "office", "#TV"]) == ["Office", "TV"]


def test_search_api_and_outlet_actions_ignore_case(client, hub, monkeypatch):
    desk = client.post(
        "/api/v1/devices",
        json={"name": "Desk", "mac": "02:00:00:00:00:81", "host": "10.9.8.1", "tags": ["#Office", "office", "#TV"]},
    )
    assert desk.status_code == 201, desk.text
    assert desk.json()["tags"] == ["Office", "TV"]
    spare = client.post(
        "/api/v1/devices",
        json={"name": "Spare", "mac": "02:00:00:00:00:82", "host": "10.9.8.2", "tags": ["office"]},
    )
    assert spare.status_code == 201, spare.text
    assert spare.json()["tags"] == ["Office"]
    other = client.post(
        "/api/v1/devices",
        json={"name": "Bench", "mac": "02:00:00:00:00:83", "host": "10.9.8.3", "tags": ["Lab"]},
    )
    assert other.status_code == 201, other.text
    found = client.get("/api/v1/devices", params={"q": "#office"})
    assert found.status_code == 200, found.text
    assert {item["name"] for item in found.json()} == {"Desk", "Spare"}
    filtered = client.get("/api/v1/devices", params={"tags": "OFFICE"})
    assert {item["name"] for item in filtered.json()} == {"Desk", "Spare"}
    stuck = client.patch(f"/api/v1/devices/{desk.json()['id']}", json={"tags": ["OFFICE"]})
    assert stuck.status_code == 200, stuck.text
    assert stuck.json()["tags"] == ["Office"]
    pdu = client.post("/api/v1/pdus", json={"name": "Rack", "host": "10.9.8.4", "password": "secret"})
    assert pdu.status_code == 201, pdu.text
    hub.write(
        "INSERT INTO pdu_outlets (pdu_id, number, name, tags) VALUES (?, 1, 'Lamp', '[]')",
        (pdu.json()["id"],),
    )
    tagged = client.patch(f"/api/v1/pdus/{pdu.json()['id']}/outlets/1", json={"tags": ["#office", "Office"]})
    assert tagged.status_code == 200, tagged.text
    assert tagged.json()["tags"] == ["Office"]
    calls = []
    monkeypatch.setattr("wakehub.power.dispatch_device", lambda *args, **kwargs: calls.append(("device", args[1])))
    monkeypatch.setattr("wakehub.power.set_pdu_outlet", lambda *args, **kwargs: calls.append(("outlet", args[2])))
    acted = client.post("/api/v1/tags/action", json={"tags": ["OFFICE"], "action": "off", "confirm": True})
    assert acted.status_code == 200, acted.text
    assert acted.json()["tags"] == ["Office"]
    assert ("device", desk.json()["id"]) in calls
    assert ("device", spare.json()["id"]) in calls
    assert ("device", other.json()["id"]) not in calls
    assert ("outlet", 1) in calls
    cleared = client.patch(f"/api/v1/devices/{other.json()['id']}", json={"tags": []})
    assert cleared.status_code == 200
    renamed = client.patch(f"/api/v1/devices/{other.json()['id']}", json={"tags": ["PORCH"]})
    assert renamed.json()["tags"] == ["PORCH"]
    again = client.post(
        "/api/v1/devices",
        json={"name": "Porch light", "mac": "02:00:00:00:00:84", "host": "10.9.8.5", "tags": ["porch"]},
    )
    assert again.json()["tags"] == ["PORCH"]


def test_mcp_tag_action_matches_a_different_spelling(client, hub, monkeypatch):
    from wakehub.mcp_server import build_server

    created = client.post(
        "/api/v1/devices",
        json={"name": "Desk", "mac": "02:00:00:00:00:91", "host": "10.9.8.11", "tags": ["#Office"]},
    )
    assert created.status_code == 201, created.text
    calls = []
    monkeypatch.setattr("wakehub.power.wake_device", lambda *args, **kwargs: calls.append(args[1]))
    set_hub(hub)
    result = asyncio.run(build_server().call_tool("tag_action", {"tags": ["office"], "action": "wake", "confirm": True}))
    body = json.loads(result.content[0].text)
    assert result.is_error is not True
    assert body["matched"] == 1
    assert body["tags"] == ["Office"]
    assert calls == [created.json()["id"]]


def test_restart_merges_tags_that_differ_only_by_case(tmp_path):
    hub = Hub.open(_settings(tmp_path))
    device = add_device(hub, {"name": "Desk", "mac": "02:00:00:00:00:71", "host": "10.9.8.21", "tags": ["office"]})
    plug = add_plug(hub, {"name": "Lamp", "kind": "shelly", "host": "10.9.8.22", "tags": ["Lab"]})
    pdu = add_pdu(hub, {"name": "Rack", "host": "10.9.8.23", "password": "secret"})
    salvo = add_salvo(
        hub,
        {"name": "Away", "steps": [{"target_kind": "tag", "tags": ["Lab"], "action": "off"}]},
    )
    hub.write(
        "UPDATE devices SET tags = ?, created_at = ? WHERE id = ?",
        (json.dumps(["office", "OFFICE"]), "2020-01-01T00:00:00+00:00", device["id"]),
    )
    hub.write("UPDATE plugs SET tags = ? WHERE id = ?", (json.dumps(["Office", "lab", "LAB"]), plug["id"]))
    hub.write(
        "INSERT INTO pdu_outlets (pdu_id, number, name, tags) VALUES (?, 1, 'Lamp', ?)",
        (pdu["id"], json.dumps(["OFFICE", "office"])),
    )
    hub.write(
        "UPDATE salvos SET steps = ? WHERE id = ?",
        (
            json.dumps(
                [
                    {
                        "target_kind": "tag",
                        "target_id": None,
                        "tags": ["OFFICE", "office"],
                        "action": "off",
                        "delay_seconds": 0,
                        "method": "auto",
                    }
                ]
            ),
            salvo["id"],
        ),
    )
    _close(hub)
    again = Hub.open(_settings(tmp_path))
    try:
        assert json.loads(again.query_one("SELECT tags FROM devices WHERE id = ?", (device["id"],))["tags"]) == ["office"]
        assert json.loads(again.query_one("SELECT tags FROM plugs WHERE id = ?", (plug["id"],))["tags"]) == ["office", "lab"]
        assert json.loads(again.query_one("SELECT tags FROM pdu_outlets WHERE pdu_id = ?", (pdu["id"],))["tags"]) == ["office"]
        steps = json.loads(again.query_one("SELECT steps FROM salvos WHERE id = ?", (salvo["id"],))["steps"])
        assert steps[0]["tags"] == ["office"]
    finally:
        _close(again)
    third = Hub.open(_settings(tmp_path))
    try:
        assert json.loads(third.query_one("SELECT tags FROM plugs WHERE id = ?", (plug["id"],))["tags"]) == ["office", "lab"]
    finally:
        _close(third)
