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


def _input_name_page() -> str:
    labels = ("Attic POE", "HDMI Streaming", "Home PC", "Internet Fiber Jack", "Network Gear", "Work HP", "Work Peplink")
    inputs = "".join(f'<input type="text" name="oName{index}" value="{label}">' for index, label in enumerate(labels, start=1))
    return f"<html><body><form>{inputs}</form></body></html>"


def _status_table_page() -> str:
    rows = (
        ("1", "Attic POE"),
        ("2", "It's HDMI"),
        ("3", "Work (HP)"),
        ("4", "Rack]"),
    )
    body = "".join(f"<tr><td>{number}</td><td>{label}</td><td>ON</td></tr>" for number, label in rows)
    return "<html><table><tr><th>No.</th><th>Name</th><th>State</th></tr>" + body + "</table></html>"


def test_outlet_name_fixtures_match_their_format(monkeypatch):
    monkeypatch.undo()
    assert parse_outlet_names("$A5\n1111111111111111,0.42,0.18,27") == {}
    inputs = parse_outlet_names(_input_name_page())
    assert inputs[1] == "Attic POE"
    assert inputs[4] == "Internet Fiber Jack"
    table = parse_outlet_names(_status_table_page())
    assert table == {1: "Attic POE", 2: "It's HDMI", 3: "Work (HP)", 4: "Rack]"}
    script = 'var olName = new Array("It\'s Attic", "Work (HP)", "Rack]");'
    assert parse_outlet_names(f"<script>{script}</script>") == {1: "It's Attic", 2: "Work (HP)", 3: "Rack]"}
    mixed = """var outletname = ["It's", 'say "hi"', "end]"];"""
    assert parse_outlet_names(mixed) == {1: "It's", 2: 'say "hi"', 3: "end]"}

    def handler(request):
        if request.url.path == "/pwr.htm":
            return httpx.Response(404, text="missing")
        if request.url.path == "/":
            return httpx.Response(200, text=_status_table_page(), headers={"content-type": "text/html"})
        return httpx.Response(404, text="later")

    client = SynaccessClient("192.168.0.8", "admin", "secret-pass", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.read_outlet_names()[2] == "It's HDMI"
    assert client.name_pages[0]["path"] == "/pwr.htm"
    assert client.name_pages[1]["path"] == "/"
    assert "secret-pass" not in str(client.name_pages)
    client.close()


def _np05b_status_page() -> str:
    # Outlet 2 has no opening <tr>. Outlet 3's name is empty. A later table has an Outlet List column.
    return """
    <html><body>
    <table border="1">
    <tr><td>Outlet</td><td>Name</td><td>Status</td></tr>
    <tr><td>1</td><td>Attic POE</td><td>ON</td></tr>
    <td>2</td><td>HDMI Streaming</td><td>ON</td></tr>
    <tr><td>3</td><td></td><td>OFF</td></tr>
    </table>
    <table>
    <tr><td>Group</td><td>Outlet List</td></tr>
    <tr><td>Studio</td><td>3</td></tr>
    </table>
    </body></html>
    """


def test_status_table_ignores_a_missing_tr_and_the_next_table():
    names = parse_outlet_names(_np05b_status_page())
    assert names[1] == "Attic POE"
    assert names[2] == "HDMI Streaming"
    assert 3 not in names
    assert "3" not in names.values()
    assert "Outlet List" not in names.values()


_NP_REAL = {
    1: "Internet Fiber J",
    2: "Network Gear",
    3: "Atic POE",
    6: "Home PC",
    7: "Work HP",
    8: "Peplink",
    9: "HDMI-Streaming",
}


def _np_label(number: int) -> str:
    return _NP_REAL.get(number, f"Outlet{number}")


def _operation_status_page() -> str:
    rows = []
    for number in range(1, 17):
        index = number - 1
        prefix = "\n\r\n\t\t\t\t\t" if number == 10 else ""
        rows.append(
            f"{prefix}<tr><td>{number} </td>\n"
            f"\t\t<td><a onclick=\"ajxCmd('cmd.cgi?rly={index}');\">\n"
            f"\t\t<img src=\"btn.gif\"/></a></td>\n"
            f"\t\t<td><a onclick=\"ajxCmd('cmd.cgi?rb={index}');\">\n"
            f"\t\t<img src=\"btn.gif\" /></a></td>\n"
            f"\t\t<td id=\"rly{index}\"></td>\n"
            f"\t\t<td>{_np_label(number)}</td>\n"
            "\t\t<td> </td></tr>"
        )
    page = (
        '<div class="subttl">Power Outlet Status</div>\r\n'
        '\t<span class="errstr" id="err1"></span>\r\n'
        "\t\t<table>\r\n"
        "\t\t\t<tr><td>Outlet</td><td>On/Off</td><td>Reboot</td><td>Status</td><td>Name</td><td>Reservation</td></td></tr>\r\n"
        "\r\n\t\t\t\t\t"
        + "".join(rows)
        + "\n \r\n\t\t\t \r\n\r\n\t\t</table>"
        "<table><tr><td></td><td>On</td><td>Off</td><td>Reboot</td><td>Outlet List</td></tr>"
        "<tr>\t<td>Group 1</td><td>a</td><td>b</td><td>c</td><td>1,2,3</td></tr></table>"
    )
    return ("x" * 9000) + page


def _outlet_setup_page() -> str:
    rows = []
    for index in range(16):
        rows.append(
            f"<tr><td>{index + 1}</td>\n"
            f'\t\t<td><input type="text" name="ON{index}" value="{_np_label(index + 1)}" size="22" maxlength="16"  /></td>\n'
            f'\t\t<td><input type="checkbox" value="{index}" name="drch"    /></td>\n'
            f'\t\t<td><input type="text" name="DR{index}" value="02:00" size="6" maxlength="5"  /></td>\n'
            f'\t\t<td><input type="text" name="DB{index}" value="20" size="6" maxlength="5"  /></td>\n'
            f'\t\t<td><select name="ri{index}"><option value="0">Prev State</option>'
            '<option value="1" selected="SELECTED">ON</option></select></td>\r\n</tr>'
        )
    return (
        '<form class="synform"  method="post" action="pwr.htm" name="config">\r\n'
        "\t<table>\r\n\t\t<tr>\r\n"
        "\t\t\t<th>Outlet</th>\r\n\t\t\t<th>Name</th>\r\n"
        "\t\t\t<th>Enable Daily<br />Power Recycle</th>\r\n"
        "\t\t</tr>\r\n"
        + "".join(rows)
        + "</table>"
        '<input type="text" name="wkS0" value="skip">'
        '<input type="checkbox" name="gst0">'
        '<input name="odly" value="1">'
        '<input name="tcH" value=45>'
        "</form>"
    )


def _status_xml() -> str:
    relays = "".join(f"<rly{index}>1</rly{index}>\n" for index in range(8))
    relays += "\n" + "".join(f"<rly{index}>1</rly{index}>\n" for index in range(8, 16))
    empty = "".join(f"<ac{index}> </ac{index}>\n" for index in range(2, 31))
    return (
        "<response>\n"
        + relays
        + "<rly16>0</rly16>\n\n"
        + "<ac0>1.90 - 2.64</ac0>\n<ac1>1.76 - 2.53</ac1>\n"
        + empty
        + "\n<tcp1>X</tcp1>\n<tcp2>X</tcp2>\n\n"
        + "<tp0>20/68</tp0>\n<tp1>31/87</tp1>\n<tp2>13/55</tp2>\n"
        + "<tp3>Time: 01/10/2011-10:00:00 UpTime: 0169:20:15:53    </tp3>\n"
        + "<apa30>39411/40447</apa30>\n<err1>.</err1>\n</response>"
    )


def test_np1601_pages_and_status_xml(monkeypatch, caplog):
    import logging

    from wakehub.clients.synaccess import parse_status_xml

    monkeypatch.undo()
    assert parse_outlet_names(_operation_status_page()) == _NP_REAL
    assert "Group 1" not in parse_outlet_names(_operation_status_page()).values()
    assert "1,2,3" not in parse_outlet_names(_operation_status_page()).values()
    assert parse_outlet_names(_outlet_setup_page()) == _NP_REAL
    parsed = parse_status_xml(_status_xml(), {1: "Internet Fiber J"})
    assert len(parsed.outlets) == 16
    assert all(item.on for item in parsed.outlets)
    assert parsed.outlets[0].name == "Internet Fiber J"
    assert all(item.number <= 16 for item in parsed.outlets)
    assert parsed.bank_ranges == ("1.90 - 2.64", "1.76 - 2.53")
    assert parsed.temperature_c == 20
    assert parsed.temperature_text == "20°C / 68°F"

    seen = []

    def setup(request):
        seen.append(request.url.path)
        if request.url.path == "/pwr.htm":
            return httpx.Response(200, text=_outlet_setup_page())
        return httpx.Response(404, text="404: File not found")

    client = SynaccessClient("192.168.0.8", "admin", "secret", http=httpx.Client(transport=httpx.MockTransport(setup)))
    assert client.read_outlet_names() == _NP_REAL
    assert client.outlet_count == 16
    assert seen == ["/pwr.htm"]
    assert len(client.name_pages[0]["body"]) <= 8192
    client.close()

    seen.clear()

    def fallback(request):
        seen.append(request.url.path)
        if request.url.path == "/":
            return httpx.Response(200, text=_operation_status_page(), headers={"content-type": "text/html"})
        return httpx.Response(404, text="404: File not found")

    client = SynaccessClient("192.168.0.8", "admin", "secret", http=httpx.Client(transport=httpx.MockTransport(fallback)))
    assert client.read_outlet_names() == _NP_REAL
    assert seen == ["/pwr.htm", "/"]
    client.close()

    seen.clear()

    def live(request):
        seen.append(request.url.path)
        if request.url.path == "/status.xml":
            return httpx.Response(200, text=_status_xml(), headers={"content-type": "text/xml"})
        raise AssertionError(request.url.path)

    client = SynaccessClient("192.168.0.8", "admin", "secret", http=httpx.Client(transport=httpx.MockTransport(live)))
    state = client.status({1: "Internet Fiber J"})
    assert len(state.outlets) == 16
    assert seen == ["/status.xml"]
    assert client.status_pages[0]["path"] == "/status.xml"
    client.close()

    seen.clear()

    def legacy(request):
        seen.append(request.url.path)
        if request.url.path == "/status.xml":
            return httpx.Response(404, text="missing")
        return httpx.Response(200, text="<html>raw-a5-body</html>")

    client = SynaccessClient("192.168.0.11", "admin", "secret", http=httpx.Client(transport=httpx.MockTransport(legacy)))
    with caplog.at_level(logging.INFO, logger="wakehub.synaccess"):
        try:
            client.status()
        except Exception:
            pass
        try:
            client.status()
        except Exception:
            pass
    client.close()
    assert seen[:2] == ["/status.xml", "/cmd.cgi"]
    assert caplog.text.count("raw-a5-body") == 1


def test_unknown_relay_and_xml_names_and_default_page_stops(monkeypatch):
    from wakehub.clients.synaccess import parse_status_xml

    monkeypatch.undo()
    body = "<response><rly0>1</rly0><rly1>x</rly1><rly2>0</rly2></response>"
    parsed = parse_status_xml(body)
    assert [item.on for item in parsed.outlets] == [True, None, False]
    assert parse_outlet_names('<input type="text" name="ON0" value="A &amp; B">') == {1: "A & B"}
    seen = []

    def handler(request):
        seen.append(request.url.path)
        inputs = "".join(
            f'<input type="text" name="ON{index}" value="Outlet{index + 1}">' for index in range(16)
        )
        if request.url.path == "/pwr.htm":
            return httpx.Response(200, text=f"<form>{inputs}</form>")
        return httpx.Response(200, text="should not be fetched")

    client = SynaccessClient("192.168.0.12", "admin", "secret", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.read_outlet_names() == {}
    assert client.outlet_count == 16
    assert seen == ["/pwr.htm"]
    client.close()


def test_diagnostics_redact_every_form_of_the_password():
    import base64
    import html
    from urllib.parse import quote

    from wakehub.clients.synaccess import redact_diagnostics

    secret = "S3cr&t<pw>!"
    username = "admin"
    escaped = html.escape(secret, quote=True)
    encoded = quote(secret, safe="")
    token = base64.b64encode(f"{username}:{secret}".encode()).decode()
    page = "\n".join(
        (
            f'<input type="password" name="pw" value="{escaped}">',
            '<input name="again" type="password" value="other-secret">',
            f'<a href="/go?password={encoded}">open</a>',
            "Cookie: sid=1; session=abc",
            "Set-Cookie: theme=dark; sid=2",
            token,
        )
    )
    cleaned = redact_diagnostics(page, secret, username)
    assert secret not in cleaned
    assert escaped not in cleaned
    assert encoded not in cleaned
    assert "other-secret" not in cleaned
    assert "sid=1" not in cleaned
    assert "session=abc" not in cleaned
    assert "theme=dark" not in cleaned
    assert token not in cleaned
    assert "[redacted]" in cleaned


def test_name_read_reports_the_first_non_404_and_a_login_page(monkeypatch, caplog):
    import logging

    from wakehub.clients.synaccess import LOGIN_MESSAGE

    monkeypatch.undo()

    def login_handler(request):
        if request.url.path == "/pwr.htm":
            return httpx.Response(404, text="last-must-not-win")
        if request.url.path == "/":
            return httpx.Response(200, text="<html><body>Please login<form><input type='password'></form></body></html>")
        return httpx.Response(404, text="last-must-not-win")

    client = SynaccessClient("192.168.0.8", "admin", "secret-pass", http=httpx.Client(transport=httpx.MockTransport(login_handler)))
    with caplog.at_level(logging.INFO, logger="wakehub.synaccess"):
        try:
            client.read_outlet_names()
        except Exception as exc:
            message = str(exc)
        else:
            message = ""
    client.close()
    assert message == LOGIN_MESSAGE
    assert "last-must-not-win" not in message
    assert caplog.text.count("PDU outlet names") == 1

    def plain_handler(request):
        if request.url.path == "/pwr.htm":
            return httpx.Response(404, text="skip")
        if request.url.path == "/":
            return httpx.Response(200, text="<html><body>no names TOKEN</body></html>")
        return httpx.Response(401, text="later-login")

    client = SynaccessClient("192.168.0.9", "admin", "secret-pass", http=httpx.Client(transport=httpx.MockTransport(plain_handler)))
    try:
        client.read_outlet_names()
    except Exception as exc:
        message = str(exc)
    else:
        message = ""
    client.close()
    assert "/ HTTP 200" in message
    assert "TOKEN" in message
    assert "later-login" not in message

    def rejected(request):
        if request.url.path == "/pwr.htm":
            return httpx.Response(401, text="denied")
        return httpx.Response(404, text="later")

    from wakehub.clients.synaccess import AUTH_MESSAGE

    client = SynaccessClient("192.168.0.10", "admin", "secret-pass", http=httpx.Client(transport=httpx.MockTransport(rejected)))
    try:
        client.read_outlet_names()
    except Exception as exc:
        message = str(exc)
    else:
        message = ""
    client.close()
    assert message == AUTH_MESSAGE


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
