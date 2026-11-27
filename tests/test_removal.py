def test_delete_unlinks_mappings_and_drops_only_the_salvo_steps_that_named_the_record(client):
    desk = client.post(
        "/api/v1/devices",
        json={"name": "Desk", "mac": "02:00:00:00:00:81", "host": "10.9.8.1", "tags": ["Office"]},
    ).json()
    spare = client.post(
        "/api/v1/devices",
        json={"name": "Spare", "mac": "02:00:00:00:00:82", "host": "10.9.8.2", "tags": ["Spare"]},
    ).json()
    plug = client.post(
        "/api/v1/plugs",
        json={"name": "Lamp", "kind": "shelly", "host": "10.9.8.3", "device_id": desk["id"], "tags": ["Office"]},
    ).json()
    pdu = client.post("/api/v1/pdus", json={"name": "Rack", "host": "10.9.8.4"}).json()
    linked = client.patch(
        f"/api/v1/devices/{desk['id']}",
        json={
            "methods": [
                {"kind": "wol"},
                {"kind": "plug", "plug_id": plug["id"]},
                {"kind": "pdu", "pdu_id": pdu["id"], "outlet": 2},
            ]
        },
    )
    assert linked.status_code == 200, linked.text
    salvo = client.post(
        "/api/v1/salvos",
        json={
            "name": "Home Away",
            "steps": [
                {"target_kind": "device", "target_id": desk["id"], "action": "off"},
                {"target_kind": "plug", "target_id": plug["id"], "action": "off"},
                {"target_kind": "tag", "tags": ["Office"], "action": "off"},
            ],
        },
    ).json()

    preview = client.post(
        "/api/v1/inventory/remove",
        json={"confirm": False, "targets": [{"kind": "device", "id": desk["id"]}], "tags": []},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["confirm"] is False
    assert preview.json()["removed"] == []
    assert preview.json()["salvos"] == ["Home Away"]
    assert client.get(f"/api/v1/devices/{desk['id']}").status_code == 200

    gone = client.post(
        "/api/v1/inventory/remove",
        json={"confirm": True, "targets": [{"kind": "device", "id": desk["id"]}], "tags": []},
    )
    assert gone.status_code == 200, gone.text
    assert client.get(f"/api/v1/devices/{desk['id']}").status_code == 404
    plugs = client.get("/api/v1/plugs").json()
    assert next(item for item in plugs if item["id"] == plug["id"])["device_id"] is None
    steps = client.get(f"/api/v1/salvos/{salvo['slug']}").json()["steps"]
    assert [step["target_kind"] for step in steps] == ["plug", "tag"]
    assert client.get(f"/api/v1/devices/{spare['id']}").status_code == 200

    client.patch(
        f"/api/v1/devices/{spare['id']}",
        json={
            "methods": [
                {"kind": "wol"},
                {"kind": "plug", "plug_id": plug["id"]},
                {"kind": "pdu", "pdu_id": pdu["id"], "outlet": 1},
            ]
        },
    )
    tagged = client.post("/api/v1/inventory/remove", json={"confirm": False, "targets": [], "tags": ["Office"]})
    assert sorted(item["name"] for item in tagged.json()["targets"]) == ["Lamp"]
    assert tagged.json()["salvos"] == ["Home Away"]
    assert any(item["id"] == plug["id"] for item in client.get("/api/v1/plugs").json())

    client.post("/api/v1/inventory/remove", json={"confirm": True, "tags": ["#Office"]})
    assert all(item["id"] != plug["id"] for item in client.get("/api/v1/plugs").json())
    methods = client.get(f"/api/v1/devices/{spare['id']}").json()["methods"]
    assert all(item.get("kind") != "plug" for item in methods)
    assert any(item.get("pdu_id") == pdu["id"] for item in methods)

    removed = client.delete(f"/api/v1/pdus/{pdu['id']}")
    assert removed.status_code == 204, removed.text
    methods = client.get(f"/api/v1/devices/{spare['id']}").json()["methods"]
    assert all(item.get("kind") != "pdu" for item in methods)
    steps = client.get(f"/api/v1/salvos/{salvo['slug']}").json()["steps"]
    assert [step["target_kind"] for step in steps] == ["tag"]
    assert client.get(f"/api/v1/devices/{spare['id']}").json()["name"] == "Spare"
