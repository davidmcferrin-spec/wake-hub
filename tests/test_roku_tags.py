import httpx

from wakehub.clients.roku import RokuClient, parse_device_info, parse_ssdp
from wakehub.fingerprint import suggest
from wakehub.tags import normalize_tags


INFO = """
<device-info>
  <vendor-name>Roku</vendor-name>
  <model-name>Roku Ultra</model-name>
  <user-device-name>Den</user-device-name>
  <power-mode>PowerOn</power-mode>
  <serial-number>YN00</serial-number>
</device-info>
"""


def test_roku_device_info_and_ssdp_are_parsed():
    parsed = parse_device_info(INFO)
    assert parsed["name"] == "Den"
    assert parsed["model"] == "Roku Ultra"
    assert parsed["power_mode"] == "PowerOn"
    assert parsed["on"] is True
    packet = "HTTP/1.1 200 OK\r\nST: roku:ecp\r\nLOCATION: http://192.168.0.20:8060/\r\n\r\n"
    found = parse_ssdp(packet)
    assert found["ip"] == "192.168.0.20"
    assert found["port"] == 8060
    assert parse_ssdp("HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\n") is None


def test_roku_client_reads_info_and_sends_power_on(monkeypatch):
    monkeypatch.undo()
    sent = []

    def handler(request):
        if request.url.path == "/query/device-info":
            return httpx.Response(200, text=INFO)
        sent.append((request.method, request.url.path))
        return httpx.Response(200, text="")

    client = RokuClient("10.1.1.1", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.device_info()["model"] == "Roku Ultra"
    client.keypress("PowerOn")
    assert sent == [("POST", "/keypress/PowerOn")]
    client.close()


def test_roku_is_suggested_from_ssdp_port_and_oui():
    live = suggest(vendor="", mac="", ports=set(), http_kinds=["roku"], mdns=[], ssdp=True)
    assert live["type"] == "roku" and live["confidence"] == "high" and live["prefill"]["kind"] == "roku"
    port = suggest(vendor="Roku, Inc.", mac="00:0D:4B:11:22:33", ports={8060}, http_kinds=[], mdns=[])
    assert port["type"] == "roku" and port["confidence"] == "high"
    oui = suggest(vendor="Roku, Inc.", mac="00:0D:4B:11:22:34", ports=set(), http_kinds=[], mdns=[])
    assert oui["type"] == "roku" and oui["confidence"] == "medium"


def test_tags_are_case_insensitive_and_bulk_actions_need_confirm(client, monkeypatch):
    assert normalize_tags(["#Office", "office", "#TV"]) == ["Office", "TV"]
    office = client.post("/api/v1/devices", json={"name": "Desk", "mac": "02:00:00:00:00:01", "host": "10.9.2.1", "tags": ["#Office", "#TV"]})
    assert office.status_code == 201, office.text
    other = client.post("/api/v1/devices", json={"name": "Spare", "mac": "02:00:00:00:00:02", "host": "10.9.2.2", "tags": ["Office"]})
    assert other.status_code == 201
    listed = client.get("/api/v1/devices", params={"tags": "office,tv"})
    assert [item["name"] for item in listed.json()] == ["Desk"]
    hashed = client.get("/api/v1/devices", params={"q": "#office"})
    assert {item["name"] for item in hashed.json()} == {"Desk", "Spare"}
    assert client.get("/api/v1/tags").json() == ["Office", "TV"]
    plug = client.post("/api/v1/plugs", json={"name": "Lamp", "kind": "shelly", "host": "10.9.2.3", "tags": ["#Lights"]})
    assert plug.status_code == 201
    roku = client.post("/api/v1/rokus", json={"name": "Den", "host": "10.9.2.4", "tags": ["#TV", "tv"]})
    assert roku.status_code == 201
    assert roku.json()["tags"] == ["TV"]
    refused = client.post("/api/v1/rokus/{}/power".format(roku.json()["id"]), json={"action": "off", "confirm": False})
    assert refused.status_code == 409
    calls = []
    monkeypatch.setattr("wakehub.power.wake_device", lambda *args, **kwargs: calls.append("wake"))
    monkeypatch.setattr("wakehub.power.plug_power", lambda *args, **kwargs: calls.append("plug"))
    monkeypatch.setattr("wakehub.power.roku_power", lambda *args, **kwargs: calls.append("roku"))
    blocked = client.post("/api/v1/tags/action", json={"tags": ["#Office"], "action": "wake", "confirm": False})
    assert blocked.status_code == 409
    assert calls == []
    woke = client.post("/api/v1/tags/action", json={"tags": ["Office"], "action": "wake", "confirm": True})
    assert woke.status_code == 200, woke.text
    assert woke.json()["matched"] == 2
    assert calls == ["wake", "wake"]
    calls.clear()
    lights = client.post("/api/v1/tags/action", json={"tags": ["lights"], "action": "off", "confirm": True})
    assert lights.status_code == 200, lights.text
    assert calls == ["plug"]
    calls.clear()
    tvs = client.post("/api/v1/tags/action", json={"tags": ["TV"], "action": "off", "confirm": True})
    assert "roku" in calls
    assert tvs.json()["matched"] >= 1
