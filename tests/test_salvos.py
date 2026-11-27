def test_salvo_preview_lists_tag_matches_and_run_needs_one_confirm(client, monkeypatch):
    desk = client.post(
        "/api/v1/devices",
        json={"name": "Desk", "mac": "02:00:00:00:00:31", "host": "10.9.4.1", "tags": ["#Office", "#Lights"]},
    ).json()
    spare = client.post(
        "/api/v1/devices",
        json={"name": "Spare", "mac": "02:00:00:00:00:32", "host": "10.9.4.2", "tags": ["Lights"]},
    ).json()
    lamp = client.post(
        "/api/v1/plugs",
        json={"name": "Lamp", "kind": "shelly", "host": "10.9.4.3", "tags": ["#Lights"]},
    ).json()
    created = client.post(
        "/api/v1/salvos",
        json={
            "name": "All Lights Off",
            "on_error": "stop",
            "steps": [
                {"target_kind": "tag", "tags": ["#Lights", "#Office"], "action": "off", "delay_seconds": 0},
                {"target_kind": "plug", "target_id": lamp["id"], "action": "off", "delay_seconds": 2},
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["schedule"] is None
    assert body["slug"] == "all-lights-off"
    renamed = client.patch(f"/api/v1/salvos/{body['slug']}", json={"name": "Lights out"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "all-lights-off"
    assert renamed.json()["name"] == "Lights out"
    assert body["steps"][0]["tags"] == ["Lights", "Office"]
    preview = client.post(f"/api/v1/salvos/{body['slug']}/run", json={"dry_run": True, "confirm": False})
    assert preview.status_code == 200, preview.text
    first = preview.json()["steps"][0]["targets"]
    assert [item["name"] for item in first] == ["Desk"]
    assert preview.json()["steps"][1]["targets"][0]["name"] == "Lamp"
    refused = client.post(f"/api/v1/salvos/{body['id']}/run", json={"dry_run": False, "confirm": False})
    assert refused.status_code == 409

    calls = []
    slept = []
    monkeypatch.setattr("wakehub.power.dispatch_device", lambda *args, **kwargs: calls.append(("device", args[1], kwargs.get("action"))))
    monkeypatch.setattr("wakehub.power.plug_power", lambda *args, **kwargs: calls.append(("plug", args[1])))
    monkeypatch.setattr("wakehub.salvos.time.sleep", lambda seconds: slept.append(seconds))
    ran = client.post(f"/api/v1/salvos/{body['id']}/run", json={"confirm": True})
    assert ran.status_code == 200, ran.text
    assert calls == [("device", desk["id"], "off"), ("plug", lamp["id"])]
    assert slept == [2]
    assert ran.json()["stopped"] is False
    history = client.get("/api/v1/actions").json()
    assert any(item["target_name"] == "Desk" and "salvo Lights out" in item["detail"] for item in history)
    assert [item["name"] for item in ran.json()["results"]] == ["Desk", "Lamp"]
    assert spare["id"] not in {item["target_id"] for item in history if item["target_name"] == "Spare"}

    failing = client.post(
        "/api/v1/salvos",
        json={
            "name": "Home Away",
            "on_error": "stop",
            "steps": [
                {"target_kind": "device", "target_id": desk["id"], "action": "wake"},
                {"target_kind": "plug", "target_id": lamp["id"], "action": "off"},
            ],
        },
    )
    assert failing.status_code == 201, failing.text

    def boom(*_args, **_kwargs):
        raise RuntimeError("no answer")

    monkeypatch.setattr("wakehub.inventory.wake_device", boom)
    calls.clear()
    stopped = client.post(f"/api/v1/salvos/{failing.json()['id']}/run", json={"confirm": True})
    assert stopped.json()["stopped"] is True
    assert calls == []
    copied = client.post(f"/api/v1/salvos/{body['id']}/duplicate")
    assert copied.status_code == 201
    assert copied.json()["name"] == "Lights out copy"
    assert copied.json()["slug"] == "lights-out-copy"
    assert copied.json()["steps"] == body["steps"]
