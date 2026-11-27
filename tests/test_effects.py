import pytest

from wakehub.clients.amt import POWER_COMMANDS
from wakehub.clients.ups import OIDS, command_set
from wakehub.power import _ACTION_KINDS, client_command, effect_note, effect_table

# The note is the command the client sends, so Shutdown and Off on a UPS share one row.
CASES = [
    ("wol", "on", "magic packet"),
    ("amt", "on", "power on"),
    ("amt", "off", "hard power off"),
    ("amt", "reboot", "reset"),
    ("amt", "cycle", "power cycle"),
    ("amt", "shutdown", "soft graceful off"),
    ("amt", "off_hard", "power off hard"),
    ("plug", "on", "turns the plug on"),
    ("plug", "off", "cuts power"),
    ("plug", "reboot", "power cycle"),
    ("plug", "cycle", "power cycle"),
    ("pdu", "on", "turns the outlet on"),
    ("pdu", "off", "cuts power"),
    ("pdu", "reboot", "power cycle"),
    ("pdu", "cycle", "power cycle"),
    ("ups", "on", "turns the UPS on"),
    ("ups", "off", "cuts power"),
    ("ups", "reboot", "reboots the UPS"),
    ("ups", "cycle", "reboots the UPS"),
    ("ups", "shutdown", "cuts power"),
    ("jetkvm", "on", "presses the power button"),
    ("jetkvm", "off", "holds the power button"),
    ("jetkvm", "reboot", "reset"),
    ("jetkvm", "cycle", "reset"),
    ("jetkvm", "shutdown", "presses the power button"),
    ("roku", "on", "PowerOn key"),
    ("roku", "off", "PowerOff key"),
]


@pytest.mark.parametrize(("kind", "action", "note"), CASES)
def test_effect_note_follows_the_client_command(kind, action, note):
    sent = client_command(kind, action)
    assert effect_note(kind, action) == note
    if kind == "amt":
        assert sent["code"] == POWER_COMMANDS[action]
    if kind == "ups" and note == "cuts power":
        assert sent["oids"] == [OIDS["ups_off"]]
    if kind == "roku":
        assert sent["key"] in note
    if kind == "jetkvm":
        assert sent["atx"]
    if kind == "pdu" and note == "cuts power":
        assert sent == {"command": "$A3", "on": False}
    if kind == "plug" and note == "cuts power":
        assert sent == {"set_on": False, "cycle": False}


def test_ups_shutdown_sends_the_same_load_off_as_off():
    assert command_set("shutdown") == command_set("turn_off")
    assert command_set("shutdown")[0][0] == OIDS["ups_off"]
    assert effect_note("ups", "off") == effect_note("ups", "shutdown") == "cuts power"


def test_amt_off_and_shutdown_match_the_power_state_codes():
    assert POWER_COMMANDS["off"] == 8
    assert POWER_COMMANDS["shutdown"] == 12
    assert effect_note("amt", "off") == "hard power off"
    assert effect_note("amt", "shutdown") == "soft graceful off"


def test_every_supported_pair_is_in_the_table():
    covered = {(kind, action) for kind, action, _note in CASES}
    for action, kinds in _ACTION_KINDS.items():
        for kind in kinds:
            assert (kind, action) in covered
    table = effect_table()
    assert table["ups"]["off"] == table["ups"]["shutdown"] == "cuts power"
    assert table["amt"]["off"] == "hard power off"
    assert table["amt"]["shutdown"] == "soft graceful off"
    assert table["amt"]["off_hard"] == "power off hard"


def test_device_payload_includes_the_effect_table(client):
    device = client.post("/api/v1/devices", json={"name": "UNRAID", "mac": "02:00:00:00:00:71", "host": "10.8.8.9"}).json()
    assert device["effects"]["ups"]["shutdown"] == "cuts power"
    assert device["effects"]["amt"]["off"] == "hard power off"
    assert device["effects"]["amt"]["shutdown"] == "soft graceful off"
