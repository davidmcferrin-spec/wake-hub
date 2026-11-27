import pytest

from wakehub.errors import AmtUnreachable


class _AlreadyOn:
    def __init__(self, *_args, **_kwargs):
        pass

    def request_power(self, action):
        assert action == "on"
        return {"action": "on", "power_state": 2, "noop": True, "reason": "already on", "return_value": 0}


class _Unreachable:
    def __init__(self, *_args, **_kwargs):
        pass

    def request_power(self, _action):
        raise AmtUnreachable("AMT unreachable: timed out")


def test_wake_on_a_running_machine_is_ok(client, monkeypatch):
    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:81", "host": "10.8.1.1"}).json()
    client.post("/api/v1/amt", json={"name": "UNRAID vPRO", "host": "10.8.1.2", "password": "secret-amt", "device_id": device["id"]})
    monkeypatch.setattr("wakehub.endpoints.AmtClient", _AlreadyOn)
    packets = []
    monkeypatch.setattr("wakehub.inventory.send_magic_packet", lambda *_args, **_kwargs: packets.append(True))
    woken = client.post(f"/api/v1/devices/{device['id']}/wake", json={})
    assert woken.status_code == 200, woken.text
    assert woken.json()["noop"] is True
    assert woken.json()["reason"] == "already on"
    assert packets == []


def test_salvo_continues_when_the_first_wake_is_already_on(client, monkeypatch):
    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:82", "host": "10.8.1.3"}).json()
    client.post("/api/v1/amt", json={"name": "UNRAID vPRO", "host": "10.8.1.4", "password": "secret-amt", "device_id": device["id"]})
    lamp = client.post("/api/v1/plugs", json={"name": "Lamp", "kind": "shelly", "host": "10.8.1.5"}).json()
    created = client.post(
        "/api/v1/salvos",
        json={
            "name": "Morning",
            "on_error": "stop",
            "steps": [
                {"target_kind": "device", "target_id": device["id"], "action": "wake", "method": "auto"},
                {"target_kind": "plug", "target_id": lamp["id"], "action": "off"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    monkeypatch.setattr("wakehub.endpoints.AmtClient", _AlreadyOn)
    calls = []
    monkeypatch.setattr("wakehub.power.plug_power", lambda *_args, **_kwargs: calls.append("plug") or {"ok": True})
    ran = client.post(f"/api/v1/salvos/{created.json()['id']}/run", json={"confirm": True})
    assert ran.status_code == 200, ran.text
    assert ran.json()["stopped"] is False
    assert [item["name"] for item in ran.json()["results"]] == ["UNRAID", "Lamp"]
    assert calls == ["plug"]


def test_auto_wake_falls_back_to_wol_when_amt_is_unreachable(client, monkeypatch):
    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:83", "host": "10.8.1.6"}).json()
    client.post("/api/v1/amt", json={"name": "UNRAID vPRO", "host": "10.8.1.7", "password": "secret-amt", "device_id": device["id"]})
    monkeypatch.setattr("wakehub.endpoints.AmtClient", _Unreachable)
    packets = []
    monkeypatch.setattr("wakehub.inventory.send_magic_packet", lambda *_args, **_kwargs: packets.append(True))
    monkeypatch.setattr("wakehub.inventory.wait_until_reachable", lambda *_args, **_kwargs: (False, 0))
    woken = client.post(f"/api/v1/devices/{device['id']}/wake", json={"method": "auto"})
    assert woken.status_code == 200, woken.text
    assert woken.json()["reason"] == "AMT unreachable, sent WOL"
    assert packets == [True]
    explicit = client.post(f"/api/v1/devices/{device['id']}/wake", json={"method": "amt"})
    assert explicit.status_code == 502
    assert packets == [True]
