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
    Capability("ui_logout", "Sign out of the web UI", "POST", "/api/v1/ui/logout", "ui_logout"),
    Capability("get_ui_session", "Read the UI session", "GET", "/api/v1/ui/session", "get_ui_session"),
    Capability("list_interfaces", "List host subnets for scanning", "GET", "/api/v1/interfaces", "list_interfaces"),
    Capability("test_target", "Test credentials without saving", "POST", "/api/v1/test", "test_target"),
    Capability("list_credential_profiles", "List saved logins", "GET", "/api/v1/credential-profiles", "list_credential_profiles"),
    Capability("add_credential_profile", "Save a shared login", "POST", "/api/v1/credential-profiles", "add_credential_profile"),
    Capability("update_credential_profile", "Edit a saved login", "PATCH", "/api/v1/credential-profiles/{profile_id}", "update_credential_profile"),
    Capability("remove_credential_profile", "Remove a saved login", "DELETE", "/api/v1/credential-profiles/{profile_id}", "remove_credential_profile"),
    Capability("list_pdus", "List Synaccess PDUs", "GET", "/api/v1/pdus", "list_pdus"),
    Capability("add_pdu", "Add a Synaccess PDU", "POST", "/api/v1/pdus", "add_pdu"),
    Capability("update_pdu", "Edit a PDU", "PATCH", "/api/v1/pdus/{pdu_id}", "update_pdu"),
    Capability("remove_pdu", "Remove a PDU", "DELETE", "/api/v1/pdus/{pdu_id}", "remove_pdu"),
    Capability("list_pdu_outlets", "List PDU outlets and bank current", "GET", "/api/v1/pdus/{pdu_id}/outlets", "list_pdu_outlets"),
    Capability("refresh_pdu_outlet_names", "Read outlet names from the PDU", "POST", "/api/v1/pdus/{pdu_id}/outlet-names", "refresh_pdu_outlet_names"),
    Capability("set_pdu_outlet", "Switch a PDU outlet", "POST", "/api/v1/pdus/{pdu_id}/outlets/{outlet}", "set_pdu_outlet"),
    Capability("list_amt", "List Intel AMT endpoints", "GET", "/api/v1/amt", "list_amt"),
    Capability("add_amt", "Add an Intel AMT endpoint", "POST", "/api/v1/amt", "add_amt"),
    Capability("update_amt", "Edit an AMT endpoint", "PATCH", "/api/v1/amt/{amt_id}", "update_amt"),
    Capability("remove_amt", "Remove an AMT endpoint", "DELETE", "/api/v1/amt/{amt_id}", "remove_amt"),
    Capability("amt_power_state", "Read AMT power state", "GET", "/api/v1/amt/{amt_id}/power", "amt_power_state"),
    Capability("list_jetkvm", "List JetKVM endpoints", "GET", "/api/v1/jetkvm", "list_jetkvm"),
    Capability("add_jetkvm", "Add a JetKVM endpoint", "POST", "/api/v1/jetkvm", "add_jetkvm"),
    Capability("update_jetkvm", "Edit a JetKVM endpoint", "PATCH", "/api/v1/jetkvm/{jetkvm_id}", "update_jetkvm"),
    Capability("remove_jetkvm", "Remove a JetKVM endpoint", "DELETE", "/api/v1/jetkvm/{jetkvm_id}", "remove_jetkvm"),
    Capability("jetkvm_status", "Read JetKVM reachability and power state", "GET", "/api/v1/jetkvm/{jetkvm_id}/status", "jetkvm_status"),
    Capability("jetkvm_power", "Press JetKVM ATX or switch DC power", "POST", "/api/v1/jetkvm/{jetkvm_id}/power", "jetkvm_power"),
    Capability("jetkvm_console", "URL of the JetKVM web console", "GET", "/api/v1/jetkvm/{jetkvm_id}/console", "jetkvm_console"),
    Capability("list_plugs", "List Shelly and Kasa plugs", "GET", "/api/v1/plugs", "list_plugs"),
    Capability("add_plug", "Add a Shelly or Kasa plug", "POST", "/api/v1/plugs", "add_plug"),
    Capability("update_plug", "Edit a plug", "PATCH", "/api/v1/plugs/{plug_id}", "update_plug"),
    Capability("remove_plug", "Remove a plug", "DELETE", "/api/v1/plugs/{plug_id}", "remove_plug"),
    Capability("plug_status", "Read plug state and energy", "GET", "/api/v1/plugs/{plug_id}/status", "plug_status"),
    Capability("plug_power", "Switch a plug", "POST", "/api/v1/plugs/{plug_id}/power", "plug_power"),
    Capability("list_ups", "List CyberPower UPS cards", "GET", "/api/v1/ups", "list_ups"),
    Capability("add_ups", "Add a CyberPower UPS card", "POST", "/api/v1/ups", "add_ups"),
    Capability("update_ups", "Edit a UPS card", "PATCH", "/api/v1/ups/{ups_id}", "update_ups"),
    Capability("remove_ups", "Remove a UPS card", "DELETE", "/api/v1/ups/{ups_id}", "remove_ups"),
    Capability("ups_status", "Read UPS status", "GET", "/api/v1/ups/{ups_id}/status", "ups_status"),
    Capability("ups_action", "Run a UPS command", "POST", "/api/v1/ups/{ups_id}/action", "ups_action"),
    Capability("scan_subnet", "Start a subnet scan", "POST", "/api/v1/scans", "scan_subnet"),
    Capability("list_scans", "List scans", "GET", "/api/v1/scans", "list_scans"),
    Capability("scan_results", "Read one scan and its hosts", "GET", "/api/v1/scans/{scan_id}", "scan_results"),
    Capability("delete_scan", "Delete one scan", "DELETE", "/api/v1/scans/{scan_id}", "delete_scan"),
    Capability("clear_scans", "Clear scan history", "POST", "/api/v1/scans/clear", "clear_scans"),
    Capability("rescan", "Run a scan again", "POST", "/api/v1/scans/{scan_id}/rescan", "rescan"),
    Capability("add_from_scan", "Add a discovered host", "POST", "/api/v1/scans/{scan_id}/hosts/{host_id}/add", "add_from_scan"),
    Capability("device_metrics", "Read electrical history for a device", "GET", "/api/v1/devices/{device_id}/metrics", "device_metrics"),
    Capability("list_metrics", "Read stored electrical samples", "GET", "/api/v1/metrics", "list_metrics"),
    Capability("list_rokus", "List Roku devices", "GET", "/api/v1/rokus", "list_rokus"),
    Capability("add_roku", "Add a Roku", "POST", "/api/v1/rokus", "add_roku"),
    Capability("update_roku", "Edit a Roku", "PATCH", "/api/v1/rokus/{roku_id}", "update_roku"),
    Capability("remove_roku", "Remove a Roku", "DELETE", "/api/v1/rokus/{roku_id}", "remove_roku"),
    Capability("roku_status", "Read Roku power mode, model and name", "GET", "/api/v1/rokus/{roku_id}/status", "roku_status"),
    Capability("roku_power", "Send a Roku power key", "POST", "/api/v1/rokus/{roku_id}/power", "roku_power"),
    Capability("list_tags", "List tags used on devices and hardware", "GET", "/api/v1/tags", "list_tags"),
    Capability("tag_action", "Wake or power records that share tags", "POST", "/api/v1/tags/action", "tag_action"),
    Capability("list_salvos", "List saved salvos", "GET", "/api/v1/salvos", "list_salvos"),
    Capability("add_salvo", "Save a salvo", "POST", "/api/v1/salvos", "add_salvo"),
    Capability("get_salvo", "Read one salvo", "GET", "/api/v1/salvos/{salvo}", "get_salvo"),
    Capability("update_salvo", "Edit a salvo", "PATCH", "/api/v1/salvos/{salvo}", "update_salvo"),
    Capability("remove_salvo", "Remove a salvo", "DELETE", "/api/v1/salvos/{salvo}", "remove_salvo"),
    Capability("duplicate_salvo", "Copy a salvo", "POST", "/api/v1/salvos/{salvo}/duplicate", "duplicate_salvo"),
    Capability("run_salvo", "Preview or run a salvo", "POST", "/api/v1/salvos/{salvo}/run", "run_salvo"),
)


def capability_ids() -> list[str]:
    return [item.id for item in CAPABILITIES]
