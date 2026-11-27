"""MCP tools for PDUs, AMT, JetKVM, plugs, UPS, scans and metrics."""

from __future__ import annotations

from typing import Any

from wakehub import endpoints as ends
from wakehub import metrics as series
from wakehub import power as actions
from wakehub import scan as scansvc
from wakehub.hub import get_hub


def register(server) -> None:
    from wakehub.mcp_server import expose

    @server.tool()
    @expose
    def list_pdus() -> list[dict[str, Any]]:
        """List Synaccess PDUs. Passwords are not included."""
        return ends.list_pdus(get_hub())

    @server.tool()
    @expose
    def add_pdu(name: str, host: str, username: str = "admin", password: str = "", port: int = 80, use_tls: bool = False, insecure_tls: bool = False, outlet_names: dict[str, str] | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Add a Synaccess netBooter by IP. The password is stored encrypted. insecure_tls skips certificate checks for that PDU only. credential_profile_id uses a saved login instead."""
        return ends.add_pdu(get_hub(), {"name": name, "host": host, "username": username, "password": password, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "outlet_names": outlet_names, "credential_profile_id": credential_profile_id})

    @server.tool()
    @expose
    def update_pdu(pdu_id: int, name: str | None = None, host: str | None = None, username: str | None = None, password: str | None = None, port: int | None = None, use_tls: bool | None = None, insecure_tls: bool | None = None, outlet_names: dict[str, str] | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Edit a PDU. Omit a field to leave it unchanged."""
        payload = {key: value for key, value in {"name": name, "host": host, "username": username, "password": password, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "outlet_names": outlet_names, "credential_profile_id": credential_profile_id}.items() if value is not None}
        return ends.update_pdu(get_hub(), pdu_id, payload)

    @server.tool()
    @expose
    def remove_pdu(pdu_id: int) -> dict[str, Any]:
        """Remove a PDU record. This does not switch its outlets."""
        ends.remove_pdu(get_hub(), pdu_id)
        return {"removed": pdu_id}

    @server.tool()
    @expose
    def list_pdu_outlets(pdu_id: int) -> dict[str, Any]:
        """List outlet names and on/off state. Current is per inlet bank, not per outlet, on an NP-1601DU."""
        return actions.list_pdu_outlets(get_hub(), pdu_id)

    @server.tool()
    @expose
    def set_pdu_outlet(pdu_id: int, outlet: int, action: str, confirm: bool = False) -> dict[str, Any]:
        """Turn a PDU outlet on or off, or reboot it. off and reboot require confirm=true."""
        return actions.set_pdu_outlet(get_hub(), pdu_id, outlet, action, confirm=confirm, source="mcp")

    @server.tool()
    @expose
    def list_amt() -> list[dict[str, Any]]:
        """List Intel AMT endpoints. Passwords are not included."""
        return ends.list_amt(get_hub())

    @server.tool()
    @expose
    def add_amt(name: str, host: str, password: str, username: str = "admin", port: int | None = None, use_tls: bool = False, insecure_tls: bool = False, device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Add an Intel AMT or vPro endpoint. Port 16992 is HTTP and 16993 is TLS. insecure_tls allows that device's self-signed certificate."""
        return ends.add_amt(get_hub(), {"name": name, "host": host, "password": password, "username": username, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "device_id": device_id, "credential_profile_id": credential_profile_id})

    @server.tool()
    @expose
    def update_amt(amt_id: int, name: str | None = None, host: str | None = None, password: str | None = None, port: int | None = None, use_tls: bool | None = None, insecure_tls: bool | None = None, username: str | None = None, device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Edit an AMT endpoint."""
        payload = {key: value for key, value in {"name": name, "host": host, "password": password, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "username": username, "device_id": device_id, "credential_profile_id": credential_profile_id}.items() if value is not None}
        return ends.update_amt(get_hub(), amt_id, payload)

    @server.tool()
    @expose
    def remove_amt(amt_id: int) -> dict[str, Any]:
        """Remove an AMT endpoint."""
        ends.remove_amt(get_hub(), amt_id)
        return {"removed": amt_id}

    @server.tool()
    @expose
    def amt_power_state(amt_id: int) -> dict[str, Any]:
        """Read the AMT power state and which power changes the firmware advertises."""
        return actions.amt_state(get_hub(), amt_id)

    @server.tool()
    @expose
    def list_jetkvm() -> list[dict[str, Any]]:
        """List JetKVM endpoints, including the console URL. Passwords are not included."""
        return ends.list_jetkvm(get_hub())

    @server.tool()
    @expose
    def add_jetkvm(name: str, host: str, password: str = "", username: str = "", port: int | None = None, use_tls: bool = False, insecure_tls: bool = False, extension: str = "", poll_metrics: bool = False, device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Add a JetKVM by IP. Leave password empty when the device is in no-password mode. insecure_tls skips certificate checks for that device only. extension is atx-power or dc-power. poll_metrics opens a WebRTC session on the metrics interval and should stay off unless the DC extension is installed."""
        return ends.add_jetkvm(get_hub(), {"name": name, "host": host, "password": password, "username": username, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "extension": extension, "poll_metrics": poll_metrics, "device_id": device_id, "credential_profile_id": credential_profile_id})

    @server.tool()
    @expose
    def update_jetkvm(jetkvm_id: int, name: str | None = None, host: str | None = None, password: str | None = None, username: str | None = None, port: int | None = None, use_tls: bool | None = None, insecure_tls: bool | None = None, extension: str | None = None, poll_metrics: bool | None = None, device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Edit a JetKVM endpoint. poll_metrics is off by default because a poll takes the device's single WebRTC session."""
        payload = {key: value for key, value in {"name": name, "host": host, "password": password, "username": username, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "extension": extension, "poll_metrics": poll_metrics, "device_id": device_id, "credential_profile_id": credential_profile_id}.items() if value is not None}
        return ends.update_jetkvm(get_hub(), jetkvm_id, payload)

    @server.tool()
    @expose
    def remove_jetkvm(jetkvm_id: int) -> dict[str, Any]:
        """Remove a JetKVM endpoint."""
        ends.remove_jetkvm(get_hub(), jetkvm_id)
        return {"removed": jetkvm_id}

    @server.tool()
    @expose
    def jetkvm_status(jetkvm_id: int) -> dict[str, Any]:
        """Read JetKVM reachability. When the WebRTC session connects, also returns ATX power and HDD LEDs or DC power."""
        return actions.jetkvm_status(get_hub(), jetkvm_id)

    @server.tool()
    @expose
    def jetkvm_power(jetkvm_id: int, action: str, confirm: bool = False, extension: str = "auto") -> dict[str, Any]:
        """JetKVM power. ATX actions are power-short, power-long and reset. DC actions are dc-on and dc-off. power-long, reset and dc-off require confirm=true. extension is auto, atx-power, or dc-power."""
        return actions.jetkvm_power(get_hub(), jetkvm_id, action, confirm=confirm, source="mcp", extension=extension)

    @server.tool()
    @expose
    def jetkvm_console(jetkvm_id: int) -> dict[str, Any]:
        """Return the URL that opens this JetKVM's web console in a browser."""
        from wakehub.endpoints import _row, public_jetkvm

        row = _row(get_hub(), "jetkvm", jetkvm_id)
        return {"url": public_jetkvm(row)["console_url"], "jetkvm_id": jetkvm_id}

    @server.tool()
    @expose
    def list_plugs() -> list[dict[str, Any]]:
        """List Shelly and Kasa smart plugs. Credentials are not included."""
        return ends.list_plugs(get_hub())

    @server.tool()
    @expose
    def add_plug(name: str, kind: str, host: str, username: str = "", password: str = "", protocol: str = "auto", port: int = 80, insecure_tls: bool = False, switch_id: int = 0, device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Add a plug. kind is shelly or kasa. Kasa protocol is auto, xor (port 9999) or klap. Kasa username is the TP-Link account email."""
        return ends.add_plug(get_hub(), {"name": name, "kind": kind, "host": host, "username": username, "password": password, "protocol": protocol, "port": port, "insecure_tls": insecure_tls, "switch_id": switch_id, "device_id": device_id, "credential_profile_id": credential_profile_id})

    @server.tool()
    @expose
    def update_plug(plug_id: int, name: str | None = None, host: str | None = None, password: str | None = None, protocol: str | None = None, kind: str | None = None, port: int | None = None, username: str | None = None, insecure_tls: bool | None = None, switch_id: int | None = None, device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Edit a plug."""
        payload = {key: value for key, value in {"name": name, "host": host, "password": password, "protocol": protocol, "kind": kind, "port": port, "username": username, "insecure_tls": insecure_tls, "switch_id": switch_id, "device_id": device_id, "credential_profile_id": credential_profile_id}.items() if value is not None}
        return ends.update_plug(get_hub(), plug_id, payload)

    @server.tool()
    @expose
    def remove_plug(plug_id: int) -> dict[str, Any]:
        """Remove a plug record. This does not switch the plug."""
        ends.remove_plug(get_hub(), plug_id)
        return {"removed": plug_id}

    @server.tool()
    @expose
    def plug_status(plug_id: int) -> dict[str, Any]:
        """Read a plug's on/off state and any power, voltage or energy the model reports."""
        return actions.plug_status(get_hub(), plug_id)

    @server.tool()
    @expose
    def plug_power(plug_id: int, action: str, confirm: bool = False, cycle_seconds: float = 5) -> dict[str, Any]:
        """Switch a plug. action is on, off, toggle or cycle. off, cycle, and a toggle that would turn the plug off require confirm=true."""
        return actions.plug_power(get_hub(), plug_id, action, confirm=confirm, source="mcp", cycle_seconds=cycle_seconds)

    @server.tool()
    @expose
    def list_ups() -> list[dict[str, Any]]:
        """List CyberPower RCCARD UPS endpoints. Community strings and SNMPv3 keys are not included."""
        return ends.list_ups(get_hub())

    @server.tool()
    @expose
    def add_ups(name: str, host: str, snmp_version: str = "2c", community: str = "public", port: int = 161, v3_user: str = "", v3_auth_proto: str = "sha", v3_auth: str = "", v3_priv_proto: str = "aes", v3_priv: str = "", device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Add a CyberPower network card. snmp_version is 1, 2c or 3. v3_auth and v3_priv are stored encrypted."""
        return ends.add_ups(get_hub(), {"name": name, "host": host, "snmp_version": snmp_version, "community": community, "port": port, "v3_user": v3_user, "v3_auth_proto": v3_auth_proto, "v3_auth": v3_auth, "v3_priv_proto": v3_priv_proto, "v3_priv": v3_priv, "device_id": device_id, "credential_profile_id": credential_profile_id})

    @server.tool()
    @expose
    def update_ups(ups_id: int, name: str | None = None, host: str | None = None, community: str | None = None, snmp_version: str | None = None, port: int | None = None, v3_user: str | None = None, v3_auth_proto: str | None = None, v3_auth: str | None = None, v3_priv_proto: str | None = None, v3_priv: str | None = None, device_id: int | None = None, credential_profile_id: int | None = None) -> dict[str, Any]:
        """Edit a UPS card."""
        payload = {key: value for key, value in {"name": name, "host": host, "community": community, "snmp_version": snmp_version, "port": port, "v3_user": v3_user, "v3_auth_proto": v3_auth_proto, "v3_auth": v3_auth, "v3_priv_proto": v3_priv_proto, "v3_priv": v3_priv, "device_id": device_id, "credential_profile_id": credential_profile_id}.items() if value is not None}
        return ends.update_ups(get_hub(), ups_id, payload)

    @server.tool()
    @expose
    def remove_ups(ups_id: int) -> dict[str, Any]:
        """Remove a UPS card record. This does not change the UPS output."""
        ends.remove_ups(get_hub(), ups_id)
        return {"removed": ups_id}

    @server.tool()
    @expose
    def ups_status(ups_id: int) -> dict[str, Any]:
        """Read UPS line/battery state, capacity, runtime, voltages, load and power from the CyberPower MIB."""
        return actions.ups_status(get_hub(), ups_id)

    @server.tool()
    @expose
    def ups_action(ups_id: int, action: str, confirm: bool = False, delay_seconds: int | None = None, outlet: int | None = None) -> dict[str, Any]:
        """UPS command. shutdown, turn_off, reboot, sleep, battery_test, outlet_off and outlet_cycle require confirm=true. delay_seconds uses the card's graceful delay. This can drop every load on the UPS."""
        return actions.ups_action(get_hub(), ups_id, action, confirm=confirm, source="mcp", delay_seconds=delay_seconds, outlet=outlet)

    @server.tool()
    @expose
    def scan_subnet(cidr: str | None = None) -> dict[str, Any]:
        """Start a background subnet scan. Omit cidr to use this host's subnet. Requires host networking for ARP. Returns the scan id immediately; poll scan_results."""
        return scansvc.start_scan(get_hub(), cidr)

    @server.tool()
    @expose
    def list_scans() -> list[dict[str, Any]]:
        """List recent subnet scans and their progress."""
        return scansvc.list_scans(get_hub())

    @server.tool()
    @expose
    def scan_results(scan_id: int) -> dict[str, Any]:
        """Read a scan, including discovered hosts and the kinds detected (wol, synaccess, amt, jetkvm, shelly, kasa, ups)."""
        return scansvc.get_scan(get_hub(), scan_id)

    @server.tool()
    @expose
    def add_from_scan(scan_id: int, host_id: int, kind: str, name: str | None = None, password: str | None = None, username: str | None = None, community: str | None = None, plug_kind: str | None = None) -> dict[str, Any]:
        """Add one discovered host. kind is device, pdu, amt, jetkvm, plug or ups. AMT needs password. UPS can take community."""
        payload = {key: value for key, value in {"name": name, "password": password, "username": username, "community": community, "plug_kind": plug_kind}.items() if value is not None}
        return scansvc.add_from_scan(get_hub(), scan_id, host_id, kind, payload)

    @server.tool()
    @expose
    def device_metrics(device_id: int, limit: int = 400) -> list[dict[str, Any]]:
        """Electrical history for a device and the PDU, plug or UPS linked to it."""
        return series.device_metrics(get_hub(), device_id, limit=limit)

    @server.tool()
    @expose
    def list_metrics(source_kind: str | None = None, source_id: int | None = None, device_id: int | None = None, metric: str | None = None, limit: int = 400) -> list[dict[str, Any]]:
        """Read stored current, power, voltage, energy or load samples."""
        return series.query_metrics(get_hub(), source_kind=source_kind, source_id=source_id, device_id=device_id, metric=metric, limit=limit)

    @server.tool()
    @expose
    def list_interfaces() -> list[dict[str, Any]]:
        """Host IPv4 subnets that are safe to scan. Docker, veth and bridge interfaces are skipped. primary is the default route."""
        return scansvc.list_interfaces()

    @server.tool()
    @expose
    def test_target(kind: str, host: str | None = None, mac: str | None = None, broadcast: str | None = None, username: str | None = None, password: str | None = None, port: int | None = None, use_tls: bool = False, insecure_tls: bool = False, confirm: bool = False, plug_kind: str | None = None, community: str | None = None, snmp_version: str | None = None) -> dict[str, Any]:
        """Check settings without saving. kind is wol, amt, pdu, plug, jetkvm or ups. WOL only sends a packet when confirm is true."""
        from wakehub.probe import test_target as run_test

        return run_test(get_hub(), {"kind": kind, "host": host, "mac": mac, "broadcast": broadcast, "username": username, "password": password, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "confirm": confirm, "plug_kind": plug_kind, "community": community, "snmp_version": snmp_version})

    @server.tool()
    @expose
    def list_credential_profiles() -> list[dict[str, Any]]:
        """List saved logins. Passwords are not included."""
        from wakehub.credentials import list_profiles

        return list_profiles(get_hub())

    @server.tool()
    @expose
    def add_credential_profile(name: str, username: str = "", password: str | None = None) -> dict[str, Any]:
        """Save a username and password that several devices can share."""
        from wakehub.credentials import add_profile

        return add_profile(get_hub(), {"name": name, "username": username, "password": password})

    @server.tool()
    @expose
    def update_credential_profile(profile_id: int, name: str | None = None, username: str | None = None, password: str | None = None) -> dict[str, Any]:
        """Edit a saved login."""
        from wakehub.credentials import update_profile

        payload = {key: value for key, value in {"name": name, "username": username, "password": password}.items() if value is not None}
        return update_profile(get_hub(), profile_id, payload)

    @server.tool()
    @expose
    def remove_credential_profile(profile_id: int) -> dict[str, Any]:
        """Remove a saved login. Devices keep their own stored passwords."""
        from wakehub.credentials import remove_profile

        remove_profile(get_hub(), profile_id)
        return {"removed": profile_id}
