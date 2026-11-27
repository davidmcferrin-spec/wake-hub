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
    assert pdu["type"] == "synaccess" and pdu["prefill"]["kind"] == "pdu" and pdu["prefill"]["port"] == 80
    vendor_hit = suggest(vendor="Synaccess Networks", mac="AA:BB:CC:DD:EE:15", ports={80}, http_kinds=[], mdns=[])
    assert vendor_hit["type"] == "synaccess" and vendor_hit["confidence"] == "high" and vendor_hit["prefill"]["port"] == 80
    pc = suggest(vendor="Dell Inc", mac="AA:BB:CC:DD:EE:06", ports=set(), http_kinds=[], mdns=[])
    assert pc["type"] == "pc" and pc["confidence"] == "low" and "wol" in pc["capabilities"]


def test_ptr_reply_is_parsed_and_one_shelly_does_not_relabel_another_host(monkeypatch):
    import struct

    from wakehub.scan import _dns_names, _dns_query, _fingerprint, _mdns_names, _remember_mdns, discover_subnet

    packet = bytearray(_dns_query("_shelly._tcp.local"))
    packet[6:8] = b"\x00\x01"
    target = b"\x07shelly1\x05local\x00"
    packet += struct.pack("!HHHIH", 0xC00C, 12, 1, 60, len(target)) + target
    assert any("shelly" in name for name in _dns_names(bytes(packet)))
    by_ip: dict[str, list[str]] = {}
    _remember_mdns(by_ip, bytes(packet), "10.1.0.1")
    assert "10.1.0.2" not in by_ip

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no multicast")

    monkeypatch.setattr("wakehub.scan.socket.socket", Boom)
    assert _mdns_names() == {}

    monkeypatch.setattr("wakehub.scan._arp_table", lambda: {"10.1.0.1": "AA:BB:CC:DD:EE:01", "10.1.0.2": "00:11:22:33:44:55"})
    monkeypatch.setattr("wakehub.scan._mdns_names", lambda: {"10.1.0.1": ["_shelly._tcp.local"]})
    monkeypatch.setattr("wakehub.scan._roku_ssdp", lambda: set())
    monkeypatch.setattr("wakehub.scan.ping", lambda ip, timeout: True)
    monkeypatch.setattr("wakehub.scan._hostname", lambda ip: "")
    monkeypatch.setattr("wakehub.scan._http_kinds", lambda ip: [])
    monkeypatch.setattr("wakehub.scan._snmp_cyberpower", lambda ip: False)
    monkeypatch.setattr("wakehub.scan._port_open", lambda ip, port: False)
    monkeypatch.setattr("wakehub.scan.vendor", lambda mac: "Dell Inc" if str(mac).startswith("00") else "Espressif Inc")
    found = {item["ip"]: item for item in discover_subnet("10.1.0.0/30", lambda done, total: None)}
    assert found["10.1.0.1"]["detail"]["suggestion"]["type"] == "shelly"
    assert found["10.1.0.2"]["detail"]["suggestion"]["type"] != "shelly"

    seen = []

    def open_port(ip, port):
        seen.append(port)
        return port == 80

    monkeypatch.setattr("wakehub.scan._port_open", open_port)
    monkeypatch.setattr("wakehub.scan.vendor", lambda mac: "Espressif Inc")
    _kinds, detail = _fingerprint("10.9.0.8", "AA:BB:CC:DD:EE:08", [])
    assert 80 in seen and 443 in seen
    assert detail["suggestion"]["type"] == "shelly"
    assert detail["suggestion"]["confidence"] == "medium"


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
    wide = interfaces_from(
        [
            {"ifname": "br0", "addr_info": [{"family": "inet", "local": "192.168.1.20", "prefixlen": 24}]},
            {"ifname": "shim-br0", "addr_info": [{"family": "inet", "local": "192.168.1.20", "prefixlen": 24}]},
            {"ifname": "vhost0", "addr_info": [{"family": "inet", "local": "192.168.1.21", "prefixlen": 24}]},
            {"ifname": "eth0", "addr_info": [{"family": "inet", "local": "10.5.9.8", "prefixlen": 16}]},
        ],
        [{"dst": "default", "dev": "br0"}],
    )
    assert [(item["name"], item["cidr"]) for item in wide] == [("br0", "192.168.1.0/24"), ("eth0", "10.5.9.0/24")]


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

    def status(self, labels=None):
        from wakehub.clients.synaccess import parse_status

        return parse_status("0000000000000011,1.20,0.40,27", labels)

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", names)
    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.status", status)
    created = client.post("/api/v1/pdus", json={"name": "Rack", "host": "10.8.0.8", "outlet_names": {"1": "Custom"}})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["device_outlet_names"] == {"1": "NAS", "2": "Desk"}
    assert body["outlet_names"]["1"] == "Custom"
    assert len(body["outlets"]) == 16
    assert body["outlets"][0]["name"] == "Custom"
    assert body["outlets"][1]["name"] == "Desk"
    assert "tags" in body["outlets"][0]
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

    def offline_status(self, labels=None):
        from wakehub.errors import UpstreamError

        raise UpstreamError("the PDU did not return outlet names")

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", missing)
    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.status", offline_status)
    offline = client.post("/api/v1/pdus", json={"name": "Quiet", "host": "10.8.0.9"})
    assert offline.status_code == 201, offline.text
    assert offline.json()["device_outlet_names"] == {}


def test_reread_keeps_a_name_set_in_wake_hub_and_records_a_failed_read(client, hub, monkeypatch):
    from wakehub.clients.synaccess import parse_status
    from wakehub.errors import UpstreamError

    current = {"names": {1: "Attic POE", 2: "HDMI Streaming", 3: "Home PC"}}

    def names(self):
        return dict(current["names"])

    def status(self, labels=None):
        return parse_status("111,0.40,22", labels)

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", names)
    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.status", status)
    created = client.post("/api/v1/pdus", json={"name": "NP-1601DU", "host": "192.168.0.8", "outlet_names": {"2": "Work HP"}})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["outlets"][0]["name"] == "Attic POE"
    assert body["outlets"][1]["name"] == "Work HP"
    hub.write("UPDATE pdu_outlets SET name = ? WHERE pdu_id = ? AND number = ?", ("Internet Fiber Jack", body["id"], 3))
    current["names"] = {1: "Attic POE", 2: "HDMI Streaming", 3: "Home PC"}
    kept = client.post(f"/api/v1/pdus/{body['id']}/outlet-names")
    assert kept.status_code == 200, kept.text
    outlets = {item["number"]: item["name"] for item in kept.json()["outlets"]}
    assert outlets[2] == "Work HP"
    assert outlets[3] == "Internet Fiber Jack"

    def missing(self):
        raise UpstreamError("Couldn't read outlet names from the PDU (/outletsetup.htm HTTP 200: <html>login)")

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", missing)
    failed = client.post(f"/api/v1/pdus/{body['id']}/outlet-names")
    assert failed.status_code == 200, failed.text
    assert failed.json()["names_error"].startswith("Couldn't read outlet names from the PDU")
    again = {item["number"]: item["name"] for item in failed.json()["outlets"]}
    assert again[1] == "Attic POE"
    assert again[2] == "Work HP"


def test_outlet_status_does_not_read_names_or_rewrite_a_repeat_failure(client, hub, monkeypatch):
    from wakehub.clients.synaccess import parse_status
    from wakehub.errors import UpstreamError

    calls = {"names": 0, "status": 0}

    def names(self):
        calls["names"] += 1
        self.name_pages = [{"path": "/outlets.htm", "status": 200, "content_type": "text/html", "body": "secret-pass and Authorization: Basic abc cookie: sid=1"}]
        raise UpstreamError("Couldn't read outlet names from the PDU (/outlets.htm HTTP 200: plain)")

    def status(self, labels=None):
        calls["status"] += 1
        return parse_status("1,0.20,22", labels)

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", names)
    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.status", status)
    created = client.post("/api/v1/pdus", json={"name": "NP", "host": "192.168.0.8", "password": "secret-pass"})
    assert created.status_code == 201, created.text
    pdu_id = created.json()["id"]
    assert calls["names"] >= 1
    calls["names"] = 0
    calls["status"] = 0
    listed = client.get(f"/api/v1/pdus/{pdu_id}/outlets")
    assert listed.status_code == 200, listed.text
    assert listed.json()["outlets"][0]["on"] is True
    assert calls["names"] == 0
    assert calls["status"] == 1
    client.get(f"/api/v1/pdus/{pdu_id}/outlets")
    assert calls["names"] == 0
    stamp = hub.query_one("SELECT updated_at FROM pdus WHERE id = ?", (pdu_id,))["updated_at"]
    again = client.post(f"/api/v1/pdus/{pdu_id}/outlet-names")
    assert again.status_code == 200, again.text
    assert hub.query_one("SELECT updated_at FROM pdus WHERE id = ?", (pdu_id,))["updated_at"] == stamp
    downloaded = client.get(f"/api/v1/pdus/{pdu_id}/name-diagnostics")
    assert downloaded.status_code == 200
    body = downloaded.text
    assert "secret-pass" not in body
    assert "Basic abc" not in body
    assert "sid=1" not in body
    assert "/outlets.htm" in body


def test_name_refresh_does_not_also_read_status_when_the_page_lists_every_outlet(client, monkeypatch):
    calls = []

    class Recording:
        def __init__(self, *args, **kwargs):
            self.outlet_count = 0
            self.name_pages = []

        def read_outlet_names(self):
            calls.append("names")
            self.outlet_count = 16
            self.name_pages = [{"path": "/pwr.htm", "status": 200, "content_type": "text/html", "body": "Internet Fiber J"}]
            return {1: "Internet Fiber J", 2: "Network Gear"}

        def status(self, *args, **kwargs):
            calls.append("status")
            raise AssertionError("name refresh should not read status.xml")

        def close(self):
            pass

    monkeypatch.setattr("wakehub.endpoints.SynaccessClient", Recording)
    created = client.post("/api/v1/pdus", json={"name": "NP", "host": "192.168.0.18", "outlet_names": {"2": "Work HP"}})
    assert created.status_code == 201, created.text
    outlets = {item["number"]: item["name"] for item in created.json()["outlets"]}
    assert outlets[1] == "Internet Fiber J"
    assert outlets[2] == "Work HP"
    assert outlets[4] == "Outlet 4"
    assert calls == ["names"]


def test_credential_profile_is_stored_encrypted_and_selectable(client):
    created = client.post("/api/v1/credential-profiles", json={"name": "rack", "username": "admin", "password": "secret-pw"})
    assert created.status_code == 201
    assert "secret-pw" not in created.text
    profile_id = created.json()["id"]
    pdu = client.post("/api/v1/pdus", json={"name": "Strip", "host": "10.0.0.40", "credential_profile_id": profile_id})
    assert pdu.status_code == 201
    assert pdu.json()["credential_profile_id"] == profile_id
    assert client.get("/api/v1/interfaces").status_code == 200


def test_shared_login_delete_names_users_and_a_missing_profile_uses_the_device_password(client, hub):
    profile = client.post(
        "/api/v1/credential-profiles",
        json={"name": "rack", "username": "shared", "password": "shared-secret"},
    ).json()
    created = client.post(
        "/api/v1/pdus",
        json={
            "name": "Strip",
            "host": "10.0.0.41",
            "username": "local",
            "password": "local-secret",
            "credential_profile_id": profile["id"],
        },
    )
    assert created.status_code == 201, created.text
    refused = client.delete(f"/api/v1/credential-profiles/{profile['id']}")
    assert refused.status_code == 409
    assert "Strip" in refused.json()["error"]["message"]
    assert refused.json()["error"]["existing"]["records"][0]["name"] == "Strip"
    assert client.get("/api/v1/pdus").json()[0]["credential_profile_id"] == profile["id"]
    forced = client.delete(f"/api/v1/credential-profiles/{profile['id']}?force=true")
    assert forced.status_code == 204, forced.text
    assert client.get("/api/v1/pdus").json()[0]["credential_profile_id"] is None
    hub.write("UPDATE pdus SET credential_profile_id = ? WHERE id = ?", (999, created.json()["id"]))
    from wakehub.endpoints import _resolved_login, _row

    username, password = _resolved_login(hub, _row(hub, "pdu", created.json()["id"]))
    assert username == "local"
    assert password == "local-secret"


def test_changing_the_ui_password_keeps_this_browser_and_drops_the_others(client, hub):
    client.patch("/api/v1/settings", json={"ui_password": "correct horse"})
    client.headers.pop("Authorization")
    assert client.post("/api/v1/ui/login", json={"password": "correct horse"}).status_code == 200
    other = client.cookies.get("wakehub_ui")
    assert client.get("/api/v1/ui/session").status_code == 200
    client.headers["Authorization"] = f"Bearer {hub.token}"
    changed = client.patch("/api/v1/settings", json={"ui_password": "new horse"})
    assert changed.status_code == 200, changed.text
    client.headers.pop("Authorization")
    assert client.get("/api/v1/ui/session").status_code == 200
    client.cookies.clear()
    client.cookies.set("wakehub_ui", other)
    assert client.get("/api/v1/ui/session").status_code == 401
    assert client.post("/api/v1/ui/login", json={"password": "new horse"}).status_code == 200
    client.headers["Authorization"] = f"Bearer {hub.token}"
    cleared = client.patch("/api/v1/settings", json={"clear_ui_password": True})
    assert cleared.json()["ui_password_set"] is False
    client.headers.pop("Authorization")
    assert client.get("/api/v1/ui/session").status_code == 401


def test_one_bad_mdns_packet_does_not_end_listening(monkeypatch):
    from wakehub.scan import _mdns_names

    packets = [b"bad", b"good"]

    class Sock:
        def setsockopt(self, *args):
            return None

        def setblocking(self, flag):
            return None

        def sendto(self, data, addr):
            return None

        def recvfrom(self, size):
            item = packets.pop(0)
            if item == b"bad":
                raise ValueError("bad packet")
            return item, ("10.2.0.5", 5353)

        def close(self):
            return None

    monkeypatch.setattr("wakehub.scan.socket.socket", lambda *args, **kwargs: Sock())
    ready = {"n": 0}

    def select(readers, writers, errors, timeout):
        ready["n"] += 1
        if ready["n"] > 2:
            return [], [], []
        return readers, [], []

    monkeypatch.setattr("wakehub.scan.select.select", select)
    clock = {"t": 1000.0}

    def monotonic():
        clock["t"] += 0.25
        return clock["t"]

    monkeypatch.setattr("wakehub.scan.time.monotonic", monotonic)

    def remember(by_ip, packet, sender):
        by_ip.setdefault(sender, []).append("shelly")

    monkeypatch.setattr("wakehub.scan._remember_mdns", remember)
    assert _mdns_names().get("10.2.0.5") == ["shelly"]
