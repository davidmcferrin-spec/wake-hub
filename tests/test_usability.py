from wakehub.fingerprint import suggest
from wakehub.scan import interfaces_from


def test_suggestions_use_vendor_and_ports():
    amt = suggest(vendor="Intel Corporate", mac="AA:BB:CC:DD:EE:01", ports={16992}, http_kinds=[], mdns=[])
    assert amt["type"] == "amt" and amt["confidence"] == "high"
    kasa = suggest(vendor="TP-Link Systems Inc", mac="AA:BB:CC:DD:EE:02", ports={9999}, http_kinds=[], mdns=[])
    assert kasa["type"] == "kasa" and kasa["prefill"]["plug_kind"] == "kasa"
    shelly = suggest(vendor="Espressif Inc", mac="AA:BB:CC:DD:EE:03", ports=set(), http_kinds=["shelly"], mdns=["_shelly._tcp.local"])
    assert shelly["type"] == "shelly" and shelly["confidence"] == "high"
    ups = suggest(vendor="CyberPower Systems", mac="AA:BB:CC:DD:EE:04", ports={161}, http_kinds=[], mdns=[])
    assert ups["type"] == "ups"
    jet = suggest(vendor="", mac="", ports=set(), http_kinds=["jetkvm"], mdns=[])
    assert jet["type"] == "jetkvm"
    pdu = suggest(vendor="", mac="AA:BB:CC:DD:EE:05", ports=set(), http_kinds=["synaccess"], mdns=[])
    assert pdu["type"] == "synaccess" and pdu["prefill"]["kind"] == "pdu"
    pc = suggest(vendor="Dell Inc", mac="AA:BB:CC:DD:EE:06", ports=set(), http_kinds=[], mdns=[])
    assert pc["type"] == "pc" and pc["confidence"] == "low" and "wol" in pc["capabilities"]


def test_interface_picker_skips_docker_and_marks_the_default_route():
    addrs = [
        {"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16}]},
        {"ifname": "veth123", "addr_info": [{"family": "inet", "local": "169.254.1.1", "prefixlen": 24}]},
        {"ifname": "br-abcd", "addr_info": [{"family": "inet", "local": "172.18.0.1", "prefixlen": 16}]},
        {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
        {"ifname": "br0", "addr_info": [{"family": "inet", "local": "192.168.1.20", "prefixlen": 24}]},
        {"ifname": "eth1", "addr_info": [{"family": "inet", "local": "10.0.0.5", "prefixlen": 24}]},
    ]
    routes = [{"dst": "default", "dev": "br0"}]
    found = interfaces_from(addrs, routes)
    assert [item["name"] for item in found] == ["br0", "eth1"]
    assert next(item for item in found if item["primary"])["cidr"] == "192.168.1.0/24"


def test_wake_test_does_not_send_until_confirmed(client, monkeypatch):
    sent = []
    monkeypatch.setattr("wakehub.probe.send_magic_packet", lambda *args, **kwargs: sent.append(args))
    checked = client.post("/api/v1/test", json={"kind": "wol", "mac": "AA:BB:CC:DD:EE:10", "broadcast": "192.168.1.255", "confirm": False})
    assert checked.status_code == 200
    assert checked.json()["sent"] is False
    assert sent == []
    refused = client.post("/api/v1/test", json={"kind": "wol", "mac": "not-a-mac", "broadcast": "192.168.1.255"})
    assert refused.json()["ok"] is False


def test_session_survives_until_logout_or_rotation(client, hub):
    client.patch("/api/v1/settings", json={"ui_password": "correct horse", "session_days": 30})
    client.headers.pop("Authorization")
    logged = client.post("/api/v1/ui/login", json={"password": "correct horse"})
    assert logged.status_code == 200
    assert "token" not in logged.json()
    session = client.get("/api/v1/ui/session")
    assert session.status_code == 200
    assert session.json()["token"] == hub.token
    assert "max-age" in session.headers["set-cookie"].lower()
    client.post("/api/v1/ui/logout")
    assert client.get("/api/v1/ui/session").status_code == 401
    client.post("/api/v1/ui/login", json={"password": "correct horse"})
    client.headers["Authorization"] = f"Bearer {hub.token}"
    client.post("/api/v1/access-token/rotate")
    client.headers.pop("Authorization")
    again = client.get("/api/v1/ui/session")
    assert again.status_code == 401
    assert again.json()["setup_required"] is False


def test_pdu_outlet_names_are_read_and_local_overrides_win(client, monkeypatch):
    def names(self):
        return {1: "NAS", 2: "Desk"}

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", names)
    created = client.post("/api/v1/pdus", json={"name": "Rack", "host": "10.8.0.8", "outlet_names": {"1": "Custom"}})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["device_outlet_names"] == {"1": "NAS", "2": "Desk"}
    assert body["outlet_names"]["1"] == "Custom"
    from wakehub.endpoints import outlet_labels

    labels = outlet_labels({"device_outlet_names": '{"1": "NAS", "2": "Desk"}', "outlet_names": '{"1": "Custom"}'})
    assert labels == {1: "Custom", 2: "Desk"}
    refreshed = client.post(f"/api/v1/pdus/{body['id']}/outlet-names")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["outlet_names"]["1"] == "Custom"
    assert refreshed.json()["device_outlet_names"]["2"] == "Desk"

    def missing(self):
        from wakehub.errors import UpstreamError

        raise UpstreamError("the PDU did not return outlet names")

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", missing)
    offline = client.post("/api/v1/pdus", json={"name": "Quiet", "host": "10.8.0.9"})
    assert offline.status_code == 201, offline.text
    assert offline.json()["device_outlet_names"] == {}


def test_credential_profile_is_stored_encrypted_and_selectable(client):
    created = client.post("/api/v1/credential-profiles", json={"name": "rack", "username": "admin", "password": "secret-pw"})
    assert created.status_code == 201
    assert "secret-pw" not in created.text
    profile_id = created.json()["id"]
    pdu = client.post("/api/v1/pdus", json={"name": "Strip", "host": "10.0.0.40", "credential_profile_id": profile_id})
    assert pdu.status_code == 201
    assert pdu.json()["credential_profile_id"] == profile_id
    assert client.get("/api/v1/interfaces").status_code == 200
