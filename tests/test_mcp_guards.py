import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from wakehub.endpoints import add_jetkvm, add_plug
from wakehub.hub import set_hub
from wakehub.inventory import add_device
from wakehub.mcp_server import build_server


class _Plug:
    def __init__(self, on):
        self.on = on
        self.toggled = False

    def status(self):
        return {"on": self.on}

    def toggle(self):
        self.toggled = True
        self.on = not self.on
        return {"on": self.on}

    def set_on(self, on):
        self.on = on
        return {"on": on}


class _Jet:
    def __init__(self, led):
        self.led = led
        self.pressed = []
        self.dc = []

    def status(self):
        return {"atx": {"power_led": self.led}, "reachable": True, "console_url": "http://jet.local/"}

    def reachable(self):
        return self.status()

    def atx_action(self, action):
        self.pressed.append(action)
        return {"action": action}

    def dc_set(self, on):
        self.dc.append(on)
        return {"on": on, "extension": "dc-power"}

    def close(self):
        pass

    def console_url(self):
        return "http://jet.local/"


def _call(name, arguments):
    server = build_server()

    async def run():
        return await server.call_tool(name, arguments)

    return asyncio.run(run())


def test_power_action_rejects_toggle(hub):
    set_hub(hub)
    device = add_device(hub, {"name": "Box", "mac": "AA:BB:CC:DD:EE:01", "host": "10.0.0.8"})
    with pytest.raises(ToolError, match="action must be"):
        _call("power_action", {"device_id": device["id"], "action": "toggle", "method": "plug"})


def test_plug_toggle_off_requires_confirm(hub, monkeypatch):
    set_hub(hub)
    plug = add_plug(hub, {"name": "Lamp", "kind": "shelly", "host": "10.1.1.8"})
    fake = _Plug(True)

    def client(_hub, _plug_id):
        return type("Row", (), {"__getitem__": lambda self, key: {"kind": "shelly", "name": "Lamp"}[key]})(), fake

    monkeypatch.setattr("wakehub.power.plug_client", client)
    with pytest.raises(ToolError, match="confirm"):
        _call("plug_power", {"plug_id": plug["id"], "action": "toggle", "confirm": False})
    assert fake.toggled is False
    result = _call("plug_power", {"plug_id": plug["id"], "action": "toggle", "confirm": True})
    assert result.is_error is not True
    assert fake.toggled is True


def test_jetkvm_on_does_not_press_when_the_led_is_on(hub, monkeypatch):
    set_hub(hub)
    device = add_device(hub, {"name": "Desk", "mac": "AA:BB:CC:DD:EE:02", "host": "10.0.0.9"})
    jet = _Jet(True)
    endpoint = add_jetkvm(hub, {"name": "KVM", "host": "10.0.0.10", "device_id": device["id"]})
    monkeypatch.setattr("wakehub.power.jetkvm_client", lambda *_args, **_kwargs: (endpoint, jet))
    result = _call("power_action", {"device_id": device["id"], "action": "on", "method": "jetkvm"})
    assert result.is_error is not True
    assert jet.pressed == []
    jet.led = False
    result = _call("power_action", {"device_id": device["id"], "action": "on", "method": "jetkvm", "confirm": False})
    assert result.is_error is not True
    assert jet.pressed == ["power-short"]


def test_jetkvm_shutdown_is_a_short_press(hub, monkeypatch):
    set_hub(hub)
    device = add_device(hub, {"name": "Desk", "mac": "AA:BB:CC:DD:EE:03", "host": "10.0.0.11"})
    jet = _Jet(True)
    endpoint = add_jetkvm(hub, {"name": "KVM", "host": "10.0.0.12", "device_id": device["id"]})
    monkeypatch.setattr("wakehub.power.jetkvm_client", lambda *_args, **_kwargs: (endpoint, jet))
    with pytest.raises(ToolError, match="confirm"):
        _call("power_action", {"device_id": device["id"], "action": "shutdown", "method": "jetkvm", "confirm": False})
    assert jet.pressed == []
    result = _call("power_action", {"device_id": device["id"], "action": "shutdown", "method": "jetkvm", "confirm": True})
    assert result.is_error is not True
    assert jet.pressed == ["power-short"]


def test_jetkvm_on_uses_dc_when_that_extension_is_configured(hub, monkeypatch):
    set_hub(hub)
    device = add_device(hub, {"name": "Desk", "mac": "AA:BB:CC:DD:EE:04", "host": "10.0.0.13"})
    jet = _Jet(None)
    endpoint = add_jetkvm(hub, {"name": "KVM", "host": "10.0.0.14", "device_id": device["id"], "extension": "dc-power"})
    monkeypatch.setattr("wakehub.power.jetkvm_client", lambda *_args, **_kwargs: (endpoint, jet))
    result = _call("power_action", {"device_id": device["id"], "action": "on", "method": "jetkvm"})
    assert result.is_error is not True
    assert jet.pressed == []
    assert jet.dc == [True]
