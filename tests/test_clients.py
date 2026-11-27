import json

import httpx

from wakehub.clients.amt import build_power_change, parse_method_return, parse_power_state
from wakehub.clients.jetkvm import parse_device_status, parse_rpc, parse_signaling_answer, rpc_request, signaling_offer
from wakehub.clients.kasa import (
    KlapSession,
    auth_hash_v1,
    handshake1_hash,
    handshake1_hash_v1,
    handshake2_hash,
    handshake2_hash_v1,
    parse_energy,
    parse_sysinfo,
    xor_decrypt,
    xor_encrypt,
    xor_tcp_frame,
    xor_tcp_unframe,
)
from wakehub.clients.shelly import parse_shelly_info, parse_switch_status
from wakehub.clients.synaccess import SynaccessClient, parse_outlet_names, parse_result, parse_status, synaccess_http
from wakehub.clients.ups import OIDS, command_set, status_from_varbinds


def test_synaccess_np1601_status_is_bank_current():
    body = "0000000000000011,1.20,0.40,27"
    status = parse_status(body, {1: "NAS", 2: "Desk"})
    assert status.outlets[0].on is True
    assert status.outlets[0].name == "NAS"
    assert status.outlets[1].on is True
    assert status.outlets[2].on is False
    assert len(status.outlets) == 16
    assert status.bank_amps == (1.20, 0.40)
    assert status.temperature_c == 27
    prefixed = parse_status("$A0,0000000000000011,1.20,0.40,XX")
    assert prefixed.outlets[0].on is True
    assert prefixed.bank_amps == (1.20, 0.40)
    assert prefixed.temperature_c is None
    parse_result("$A0\n")
    client = SynaccessClient(
        "10.0.0.5",
        "admin",
        "secret",
        http=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="11,0.10,22"))),
    )
    parsed = client.status()
    assert parsed.outlets[0].on is True
    assert parsed.bank_amps == (0.10,)
    client.close()


def test_synaccess_outlet_names_come_from_json_or_the_setup_page(monkeypatch):
    monkeypatch.undo()
    assert parse_outlet_names('[{"outletIndex": 1, "outletName": "NAS"}, {"outletIndex": 2, "outletName": "Desk"}]') == {1: "NAS", 2: "Desk"}
    assert parse_outlet_names('{"outlets": [{"index": 0, "name": "NAS"}]}') == {1: "NAS"}
    html = '<input type="text" name="name1" value="NAS"><input value="Desk" name="name2">'
    assert parse_outlet_names(html) == {1: "NAS", 2: "Desk"}
    assert parse_outlet_names('<input type="text" name="name1" value="NAS &amp; Desk">') == {1: "NAS & Desk"}
    assert parse_outlet_names('var outletname = ["NAS", "Desk"];') == {1: "NAS", 2: "Desk"}

    def handler(request):
        if request.url.path == "/api/outlets":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, text=html)
        return httpx.Response(404)

    client = SynaccessClient("10.0.0.5", "admin", "secret", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.read_outlet_names() == {1: "NAS", 2: "Desk"}
    client.close()


def test_netbooter_setup_page_and_challenge_are_recognized():
    html = "<html><title>netBooter NP-1601DU</title><body>" + "".join(
        f'<input name="outletname{number}" value="Load {number}">' for number in range(1, 17)
    ) + "</body></html>"
    names = parse_outlet_names(html)
    assert len(names) == 16
    assert names[1] == "Load 1"
    assert names[16] == "Load 16"
    checkbox = '<input type="checkbox" name="on3" value="1"><input type="text" name="outletname1" value="NAS">'
    assert parse_outlet_names(checkbox) == {1: "NAS"}
    assert synaccess_http({"Server": "Synaccess"}, html, 200)
    assert synaccess_http({"WWW-Authenticate": 'Basic realm="netBooter"'}, "", 401)
    assert not synaccess_http({"Server": "nginx"}, "<title>Router</title>", 401)


NP1601_NAMES = (
    "Attic POE",
    "HDMI Streaming",
    "Home PC",
    "Internet Fiber Jack",
    "Network Gear",
    "Work HP",
    "Work Peplink",
)


def _np1601_setup_page() -> str:
    inputs = "".join(
        f'<input type="text" name="oName{index}" value="{label}">' for index, label in enumerate(NP1601_NAMES, start=1)
    )
    return f"<html><title>netBooter NP-1601DU</title><body><h1>Outlet Setup</h1><form>{inputs}</form></body></html>"


def test_np1601_setup_page_names_are_not_in_the_status_command(monkeypatch):
    monkeypatch.undo()
    assert parse_outlet_names("$A5\n1111111111111111,0.42,0.18,27") == {}
    assert parse_outlet_names(_np1601_setup_page()) == {index: label for index, label in enumerate(NP1601_NAMES, start=1)}
    quoted = ",".join(f'"{label}"' for label in NP1601_NAMES)
    assert parse_outlet_names(f"<script>var olName = new Array({quoted});</script>")[1] == "Attic POE"
    assert parse_outlet_names(f"<script>var olName = new Array({quoted});</script>")[7] == "Work Peplink"

    def handler(request):
        if request.url.path == "/outletsetup.htm":
            return httpx.Response(200, text=_np1601_setup_page())
        if request.url.path == "/cmd.cgi":
            return httpx.Response(200, text="1111111111111111,0.42,0.18,27")
        return httpx.Response(404, text="missing")

    client = SynaccessClient("192.168.0.8", "admin", "admin", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.read_outlet_names()[3] == "Home PC"
    assert client.read_outlet_names()[4] == "Internet Fiber Jack"
    client.close()


def test_np1601_name_read_logs_the_response_when_the_page_has_no_names(monkeypatch, caplog):
    import logging

    monkeypatch.undo()
    body = "<html><title>netBooter NP-1601DU</title><body>Please login</body></html>" + ("x" * 600)

    def handler(_request):
        return httpx.Response(200, text=body)

    client = SynaccessClient("192.168.0.8", "admin", "admin", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.INFO, logger="wakehub.synaccess"):
        try:
            client.read_outlet_names()
        except Exception as exc:
            message = str(exc)
        else:
            message = ""
    client.close()
    assert message.startswith("Couldn't read outlet names from the PDU")
    assert "HTTP 200" in caplog.text
    assert "Please login" in caplog.text
    assert "x" * 500 not in caplog.text


def test_amt_wsman_round_trip():
    request = build_power_change("http://amt.local:16992/wsman", 2, "uuid:test")
    assert "RequestPowerStateChange" in request
    assert "<n1:PowerState>2</n1:PowerState>" in request
    assert "Intel(r) AMT Power Management Service" in request
    state = parse_power_state(
        """
        <body>
          <PowerState>8</PowerState>
          <AvailableRequestedPowerStates>2</AvailableRequestedPowerStates>
          <AvailableRequestedPowerStates>8</AvailableRequestedPowerStates>
          <AvailableRequestedPowerStates>12</AvailableRequestedPowerStates>
        </body>
        """
    )
    assert state["power_name"] == "off"
    assert 12 in state["available"]
    assert parse_method_return("<ReturnValue>0</ReturnValue>") == 0
    from wakehub.clients.amt import AmtClient, POWER_COMMANDS, return_error
    from wakehub.errors import UpstreamError, WakeHubError

    assert return_error("shutdown", 2) == "AMT refused graceful shutdown (needs the Intel LMS/OS agent running); use Off"
    assert return_error("shutdown", 1).startswith("AMT refused graceful shutdown")
    assert return_error("shutdown", 4) == "AMT refused shutdown (return 4)"
    assert return_error("off", 4) == "AMT refused off (return 4)"
    try:
        parse_method_return("<ReturnValue>2</ReturnValue>", action="shutdown")
    except UpstreamError as exc:
        assert "Intel LMS" in str(exc)
    else:
        raise AssertionError("nonzero ReturnValue was accepted")
    calls = []

    def poster(_uri, payload):
        if "Enumerate" in payload:
            return 200, """<body><PowerState>2</PowerState>
              <AvailableRequestedPowerStates>2</AvailableRequestedPowerStates>
              <AvailableRequestedPowerStates>8</AvailableRequestedPowerStates>
              <AvailableRequestedPowerStates>10</AvailableRequestedPowerStates>
            </body>"""
        calls.append(payload)
        return 200, "<ReturnValue>0</ReturnValue>"

    client = AmtClient("10.0.0.8", "admin", "secret", poster=poster)
    assert POWER_COMMANDS["off"] == 8
    sent = client.request_power("off")
    assert sent["power_state"] == 8
    assert "<n1:PowerState>8</n1:PowerState>" in calls[-1]
    try:
        client.request_power("shutdown")
    except WakeHubError as exc:
        assert "does not advertise shutdown" in str(exc)
        assert "12" in str(exc)
    else:
        raise AssertionError("unadvertised shutdown was sent")
    try:
        client.request_power("off_hard")
    except WakeHubError as exc:
        assert str(exc) == "use off"
    else:
        raise AssertionError("off_hard was accepted")
    running = []

    def already_on(_uri, payload):
        if "Enumerate" in payload:
            return 200, """<body><PowerState>2</PowerState>
              <AvailableRequestedPowerStates>8</AvailableRequestedPowerStates>
              <AvailableRequestedPowerStates>5</AvailableRequestedPowerStates>
            </body>"""
        running.append(payload)
        return 200, "<ReturnValue>0</ReturnValue>"

    awake = AmtClient("10.0.0.8", "admin", "secret", poster=already_on)
    noop = awake.request_power("on")
    assert noop["noop"] is True
    assert noop["reason"] == "already on"
    assert running == []
    off_host = []

    def already_off(_uri, payload):
        if "Enumerate" in payload:
            return 200, "<body><PowerState>8</PowerState><AvailableRequestedPowerStates>2</AvailableRequestedPowerStates></body>"
        off_host.append(payload)
        return 200, "<ReturnValue>0</ReturnValue>"

    quiet = AmtClient("10.0.0.8", "admin", "secret", poster=already_off)
    assert quiet.request_power("off")["reason"] == "already off"
    assert quiet.request_power("shutdown")["reason"] == "already off"
    assert off_host == []
    sent_anyway = []

    def status_down(_uri, payload):
        if "Enumerate" in payload:
            raise OSError("timed out")
        sent_anyway.append(payload)
        return 200, "<ReturnValue>0</ReturnValue>"

    blind = AmtClient("10.0.0.8", "admin", "secret", poster=status_down)
    cycle = blind.request_power("cycle")
    assert cycle["power_state"] == 5
    assert "<n1:PowerState>5</n1:PowerState>" in sent_anyway[-1]


def test_jetkvm_rpc_and_signaling():
    raw = rpc_request("setATXPowerAction", {"action": "power-short"}, 7)
    assert json.loads(raw)["method"] == "setATXPowerAction"
    parsed = parse_rpc('{"jsonrpc":"2.0","id":7,"result":{"power":true,"hdd":false}}')
    assert parsed["result"]["power"] is True
    assert parse_device_status({"isSetup": True, "sku": "jetkvm"})["sku"] == "jetkvm"
    offer = signaling_offer({"type": "offer", "sdp": "v=0"})
    import base64

    answer = parse_signaling_answer({"type": "answer", "data": offer["data"]["sd"]})
    assert "sdp" in answer
    assert base64.b64decode(offer["data"]["sd"])


def test_shelly_gen2_status():
    status = parse_switch_status(
        {"result": {"output": True, "apower": 12.5, "voltage": 120.1, "current": 0.11, "aenergy": {"total": 40.0}}}
    )
    assert status == {"on": True, "power_w": 12.5, "voltage_v": 120.1, "current_a": 0.11, "energy_wh": 40.0}
    assert parse_shelly_info({"model": "S4PL-00116US", "gen": 4, "auth_en": False})["generation"] == 4


def test_kasa_xor_and_klap_vectors():
    payload = b'{"system":{"get_sysinfo":{}}}'
    assert xor_decrypt(xor_encrypt(payload)) == payload
    framed = xor_tcp_frame(payload)
    assert xor_tcp_unframe(framed) == payload
    info = parse_sysinfo({"system": {"get_sysinfo": {"err_code": 0, "relay_state": 1, "model": "KP125M", "alias": "Lamp", "mac": "AA:BB:CC:DD:EE:FF"}}})
    assert info["on"] is True
    assert info["model"] == "KP125M"
    energy = parse_energy({"emeter": {"get_realtime": {"err_code": 0, "power_mw": 2500, "voltage_mv": 120000, "current_ma": 21, "total_wh": 1500}}})
    assert energy["power_w"] == 2.5
    assert energy["energy_kwh"] == 1.5
    local = bytes.fromhex("00112233445566778899aabbccddeeff")
    remote = bytes.fromhex("ffeeddccbbaa99887766554433221100")
    auth = auth_hash_v1("user@example.com", "secret")
    assert auth.hex() == "9d6ce791ce44316e9e52fc1bc9d36496"
    assert handshake1_hash(local, remote, auth).hex() == "e13bb39c47f0a7bbd9356ee8b3468778ee6209f3864071128b5248231c1aa3a8"
    assert handshake2_hash(local, remote, auth).hex() == "8aaef31a1dbfb44003d8667c6ae190c10e406e2dfbc7d408cf70fb40b32cc01a"
    assert handshake1_hash_v1(local, remote, auth) == __import__("hashlib").sha256(local + auth).digest()
    assert handshake2_hash_v1(local, remote, auth) == __import__("hashlib").sha256(remote + auth).digest()
    session = KlapSession.derive(local, remote, auth)
    assert session.key.hex() == "98168e67f7beab02d61ea5a81aee8628"
    sequence, blob = session.encrypt(b'{"system":{"set_relay_state":{"state":1}}}')
    assert session.decrypt(sequence, blob).startswith(b"{")


def test_ups_mib_scaling_and_destructive_commands():
    values = {
        OIDS["model"]: "CP1500",
        OIDS["output_status"]: 3,
        OIDS["battery_status"]: 2,
        OIDS["capacity_pct"]: 80,
        OIDS["runtime_ticks"]: 180000,
        OIDS["input_voltage_raw"]: 1180,
        OIDS["output_voltage_raw"]: 1200,
        OIDS["load_pct"]: 25,
        OIDS["current_raw"]: 21,
        OIDS["power_w"]: 240,
    }
    status = status_from_varbinds(values)
    assert status["on_battery"] is True
    assert status["output_status"] == "on_battery"
    assert status["runtime_s"] == 1800
    assert status["input_voltage_v"] == 118
    assert status["current_a"] == 2.1
    assert status["power_w"] == 240
    graceful = command_set("shutdown", delay_seconds=60)
    assert graceful[0] == (OIDS["shutoff_delay"], 6000, "TimeTicks")
    assert graceful[1] == (OIDS["ups_off"], 3, "Integer")
    assert command_set("turn_off") == [(OIDS["ups_off"], 2, "Integer")]
    assert command_set("outlet_off", outlet=2)[0][1] == 2
    assert status["runtime_raw"]["value"] == 180000
