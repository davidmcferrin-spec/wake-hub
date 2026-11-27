import json
import socket


def test_health_and_ui_do_not_need_a_token(client):
    client.headers.pop("Authorization", None)
    assert client.get("/healthz").json()["status"] == "ok"
    assert "Wake Hub" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_api_rejects_a_missing_or_wrong_token(client, hub):
    client.headers.pop("Authorization", None)
    missing = client.get("/api/v1/devices")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    client.headers["Authorization"] = "Bearer wrong-token"
    assert client.get("/api/v1/devices").status_code == 401
    client.headers["Authorization"] = f"Bearer {hub.token}"
    assert client.get("/api/v1/devices").status_code == 200


def test_device_crud_hides_secureon_and_blocks_disabled_wake(client):
    created = client.post(
        "/api/v1/devices",
        json={
            "name": "Desk",
            "mac": "01-23-45-67-89-ab",
            "host": "127.0.0.1",
            "broadcast": "127.0.0.1",
            "secureon": "secret",
            "tags": ["lab"],
            "reach_timeout": 2,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["mac"] == "01:23:45:67:89:AB"
    assert body["secureon_set"] is True
    assert "secret" not in created.text
    device_id = body["id"]

    listed = client.get("/api/v1/devices", params={"tag": "lab"})
    assert [item["id"] for item in listed.json()] == [device_id]

    disabled = client.post(f"/api/v1/devices/{device_id}/enabled", json={"enabled": False})
    assert disabled.json()["enabled"] is False
    refused = client.post(f"/api/v1/devices/{device_id}/wake")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "device_disabled"

    client.post(f"/api/v1/devices/{device_id}/enabled", json={"enabled": True})
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    client.patch(f"/api/v1/devices/{device_id}", json={"wol_port": port})
    try:
        woken = client.post(
            f"/api/v1/devices/{device_id}/wake",
            headers={"X-Wake-Hub-Source": "ui"},
        )
        assert woken.status_code == 200
        assert woken.json()["reachable"] is True
        listener.settimeout(2)
        packet, _addr = listener.recvfrom(256)
    finally:
        listener.close()
    assert packet[:6] == b"\xff" * 6
    assert packet.endswith(b"secret")

    history = client.get("/api/v1/actions").json()
    wake_rows = [row for row in history if row["action"] == "wake" and row["ok"]]
    assert wake_rows[0]["source"] == "ui"
    detail = json.loads(wake_rows[0]["detail"])
    assert detail["reachable"] is True

    destructive = client.post(
        f"/api/v1/devices/{device_id}/power",
        json={"action": "off", "method": "wol", "confirm": False},
    )
    assert destructive.status_code == 409
    assert destructive.json()["error"]["code"] == "confirmation_required"

    removed = client.delete(f"/api/v1/devices/{device_id}")
    assert removed.status_code == 204
    assert client.get(f"/api/v1/devices/{device_id}").status_code == 404


def test_rotate_token_and_ui_password(client, hub):
    old = hub.token
    rotated = client.post("/api/v1/access-token/rotate")
    assert rotated.status_code == 200
    new = rotated.json()["token"]
    assert new != old
    client.headers["Authorization"] = f"Bearer {old}"
    assert client.get("/api/v1/devices").status_code == 401
    client.headers["Authorization"] = f"Bearer {new}"
    saved = client.patch("/api/v1/settings", json={"ui_password": "correct horse", "cors_origins": ["http://localhost:3000"]})
    assert saved.json()["ui_password_set"] is True
    assert "correct horse" not in saved.text
    client.headers.pop("Authorization")
    assert client.get("/api/v1/ui/session").status_code == 401
    logged_in = client.post("/api/v1/ui/login", json={"password": "correct horse"})
    assert logged_in.status_code == 200
    assert "token" not in logged_in.json()
    session = client.get("/api/v1/ui/session")
    assert session.status_code == 200
    assert session.json()["token"] == new


def test_session_does_not_leak_the_token(client, hub):
    client.headers.pop("Authorization", None)
    response = client.get("/api/v1/ui/session", headers={"Origin": "http://evil.example"})
    assert response.status_code == 401
    assert "token" not in response.json()
    assert hub.token not in response.text
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}
