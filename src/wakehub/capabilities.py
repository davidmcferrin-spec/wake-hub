"""Every user-facing capability, shared by the UI, REST API and MCP.

The parity test fails when a row is missing from any of the three.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    summary: str
    method: str
    path: str
    mcp_tool: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability("list_devices", "List inventory devices", "GET", "/api/v1/devices", "list_devices"),
    Capability("get_device", "Read one device", "GET", "/api/v1/devices/{device_id}", "get_device"),
    Capability("add_device", "Add a device", "POST", "/api/v1/devices", "add_device"),
    Capability("update_device", "Edit a device", "PATCH", "/api/v1/devices/{device_id}", "update_device"),
    Capability("remove_device", "Remove a device", "DELETE", "/api/v1/devices/{device_id}", "remove_device"),
    Capability(
        "set_device_enabled",
        "Enable or disable a device",
        "POST",
        "/api/v1/devices/{device_id}/enabled",
        "set_device_enabled",
    ),
    Capability("wake_device", "Send Wake-on-LAN and wait for reachability", "POST", "/api/v1/devices/{device_id}/wake", "wake_device"),
    Capability("power_action", "Power on, off, cycle, reboot or shutdown", "POST", "/api/v1/devices/{device_id}/power", "power_action"),
    Capability("device_status", "Probe one device", "GET", "/api/v1/devices/{device_id}/status", "device_status"),
    Capability("list_status", "Probe every enabled device", "GET", "/api/v1/status", "list_status"),
    Capability("list_actions", "Read the action log", "GET", "/api/v1/actions", "list_actions"),
    Capability("get_settings", "Read settings", "GET", "/api/v1/settings", "get_settings"),
    Capability("update_settings", "Change settings", "PATCH", "/api/v1/settings", "update_settings"),
    Capability("get_access_token", "Show the API token", "GET", "/api/v1/access-token", "get_access_token"),
    Capability("rotate_token", "Rotate the API token", "POST", "/api/v1/access-token/rotate", "rotate_token"),
    Capability("ui_login", "Sign in to the web UI when a password is set", "POST", "/api/v1/ui/login", "ui_login"),
    Capability("ui_setup", "Set the UI password using the API token", "POST", "/api/v1/ui/setup", "ui_setup"),
    Capability("get_ui_session", "Read the UI session", "GET", "/api/v1/ui/session", "get_ui_session"),
)


def capability_ids() -> list[str]:
    return [item.id for item in CAPABILITIES]
