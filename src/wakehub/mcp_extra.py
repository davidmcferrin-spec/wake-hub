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
    def add_pdu(name: str, host: str, username: str = "admin", password: str = "", port: int = 80, use_tls: bool = False, insecure_tls: bool = False, outlet_names: dict[str, str] | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Add a Synaccess netBooter by IP. The password is stored encrypted. insecure_tls skips certificate checks for that PDU only. credential_profile_id uses a saved login instead. tags are free-form, such as #Office."""
        return ends.add_pdu(get_hub(), {"name": name, "host": host, "username": username, "password": password, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "outlet_names": outlet_names, "credential_profile_id": credential_profile_id, "tags": tags})

    @server.tool()
    @expose
    def update_pdu(pdu_id: int, name: str | None = None, host: str | None = None, username: str | None = None, password: str | None = None, port: int | None = None, use_tls: bool | None = None, insecure_tls: bool | None = None, outlet_names: dict[str, str] | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Edit a PDU. Omit a field to leave it unchanged."""
        payload = {key: value for key, value in {"name": name, "host": host, "username": username, "password": password, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "outlet_names": outlet_names, "credential_profile_id": credential_profile_id, "tags": tags}.items() if value is not None}
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
        """List outlet names and on/off state from the status command. Current is per inlet bank, not per outlet, on an NP-1601DU. This does not read names from the web UI."""
        return actions.list_pdu_outlets(get_hub(), pdu_id)

    @server.tool()
    @expose
    def pdu_name_diagnostics(pdu_id: int) -> dict[str, Any]:
        """Status code, content type and the first 8 KB of each page from the last outlet-name read. Credentials and cookies are redacted."""
        return ends.pdu_name_diagnostics(get_hub(), pdu_id)

    @server.tool()
    @expose
    def refresh_pdu_outlet_names(pdu_id: int) -> dict[str, Any]:
        """Read outlet names from the PDU and store them. Names typed on the PDU record are kept and win over the device."""
        return ends.refresh_pdu_outlet_names(get_hub(), pdu_id)

    @server.tool()
    @expose
    def update_pdu_outlet(pdu_id: int, outlet: int, tags: list[str] | None = None) -> dict[str, Any]:
        """Set the tags on one PDU outlet. Tags are matched without a leading # and are case-insensitive."""
        from wakehub.endpoints import update_pdu_outlet as save_outlet

        return save_outlet(get_hub(), pdu_id, outlet, {"tags": tags or []})

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
    def add_amt(name: str, host: str, password: str, username: str = "admin", port: int | None = None, use_tls: bool = False, insecure_tls: bool = False, device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Add an Intel AMT or vPro endpoint. Port 16992 is HTTP and 16993 is TLS. insecure_tls allows that device's self-signed certificate."""
        return ends.add_amt(get_hub(), {"name": name, "host": host, "password": password, "username": username, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags})

    @server.tool()
    @expose
    def update_amt(amt_id: int, name: str | None = None, host: str | None = None, password: str | None = None, port: int | None = None, use_tls: bool | None = None, insecure_tls: bool | None = None, username: str | None = None, device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Edit an AMT endpoint."""
        payload = {key: value for key, value in {"name": name, "host": host, "password": password, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "username": username, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags}.items() if value is not None}
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
    def amt_power(amt_id: int, action: str, confirm: bool = False) -> dict[str, Any]:
        """Change AMT power. action is on (2), off (8, hard off), reboot (10, reset), cycle (5), or shutdown (12, graceful). off, reboot, cycle, and shutdown require confirm=true. off_hard is refused: use off. An action the firmware does not list in AvailableRequestedPowerStates is refused. Works whether or not the endpoint is linked to a computer."""
        return actions.amt_power(get_hub(), amt_id, action, confirm=confirm, source="mcp")

    @server.tool()
    @expose
    def list_jetkvm() -> list[dict[str, Any]]:
        """List JetKVM endpoints, including the console URL. Passwords are not included."""
        return ends.list_jetkvm(get_hub())

    @server.tool()
    @expose
    def add_jetkvm(name: str, host: str, password: str = "", username: str = "", port: int | None = None, use_tls: bool = False, insecure_tls: bool = False, extension: str = "", poll_metrics: bool = False, device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Add a JetKVM by IP. Leave password empty when the device is in no-password mode. insecure_tls skips certificate checks for that device only. extension is atx-power or dc-power. poll_metrics opens a WebRTC session on the metrics interval and should stay off unless the DC extension is installed."""
        return ends.add_jetkvm(get_hub(), {"name": name, "host": host, "password": password, "username": username, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "extension": extension, "poll_metrics": poll_metrics, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags})

    @server.tool()
    @expose
    def update_jetkvm(jetkvm_id: int, name: str | None = None, host: str | None = None, password: str | None = None, username: str | None = None, port: int | None = None, use_tls: bool | None = None, insecure_tls: bool | None = None, extension: str | None = None, poll_metrics: bool | None = None, device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Edit a JetKVM endpoint. poll_metrics is off by default because a poll takes the device's single WebRTC session."""
        payload = {key: value for key, value in {"name": name, "host": host, "password": password, "username": username, "port": port, "use_tls": use_tls, "insecure_tls": insecure_tls, "extension": extension, "poll_metrics": poll_metrics, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags}.items() if value is not None}
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
    def add_plug(name: str, kind: str, host: str, username: str = "", password: str = "", protocol: str = "auto", port: int = 80, insecure_tls: bool = False, switch_id: int = 0, device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Add a plug. kind is shelly or kasa. Kasa protocol is auto, xor (port 9999) or klap. Kasa username is the TP-Link account email."""
        return ends.add_plug(get_hub(), {"name": name, "kind": kind, "host": host, "username": username, "password": password, "protocol": protocol, "port": port, "insecure_tls": insecure_tls, "switch_id": switch_id, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags})

    @server.tool()
    @expose
    def update_plug(plug_id: int, name: str | None = None, host: str | None = None, password: str | None = None, protocol: str | None = None, kind: str | None = None, port: int | None = None, username: str | None = None, insecure_tls: bool | None = None, switch_id: int | None = None, device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Edit a plug."""
        payload = {key: value for key, value in {"name": name, "host": host, "password": password, "protocol": protocol, "kind": kind, "port": port, "username": username, "insecure_tls": insecure_tls, "switch_id": switch_id, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags}.items() if value is not None}
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
    def add_ups(name: str, host: str, snmp_version: str = "2c", community: str = "public", port: int = 161, v3_user: str = "", v3_auth_proto: str = "sha", v3_auth: str = "", v3_priv_proto: str = "aes", v3_priv: str = "", device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Add a CyberPower network card. snmp_version is 1, 2c or 3. v3_auth and v3_priv are stored encrypted."""
        return ends.add_ups(get_hub(), {"name": name, "host": host, "snmp_version": snmp_version, "community": community, "port": port, "v3_user": v3_user, "v3_auth_proto": v3_auth_proto, "v3_auth": v3_auth, "v3_priv_proto": v3_priv_proto, "v3_priv": v3_priv, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags})

    @server.tool()
    @expose
    def update_ups(ups_id: int, name: str | None = None, host: str | None = None, community: str | None = None, snmp_version: str | None = None, port: int | None = None, v3_user: str | None = None, v3_auth_proto: str | None = None, v3_auth: str | None = None, v3_priv_proto: str | None = None, v3_priv: str | None = None, device_id: int | None = None, credential_profile_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Edit a UPS card."""
        payload = {key: value for key, value in {"name": name, "host": host, "community": community, "snmp_version": snmp_version, "port": port, "v3_user": v3_user, "v3_auth_proto": v3_auth_proto, "v3_auth": v3_auth, "v3_priv_proto": v3_priv_proto, "v3_priv": v3_priv, "device_id": device_id, "credential_profile_id": credential_profile_id, "tags": tags}.items() if value is not None}
        return ends.update_ups(get_hub(), ups_id, payload)

    @server.tool()
    @expose
    def remove_ups(ups_id: int) -> dict[str, Any]:
        """Remove a UPS card record. This does not change the UPS output."""
        ends.remove_ups(get_hub(), ups_id)
        return {"removed": ups_id}

    @server.tool()
    @expose
    def list_rokus() -> list[dict[str, Any]]:
        """List Roku players and TVs. Control uses the local External Control Protocol on port 8060."""
        return ends.list_rokus(get_hub())

    @server.tool()
    @expose
    def add_roku(name: str, host: str, port: int = 8060, device_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Add a Roku by IP. Control by mobile apps must be enabled on the TV. Some models need network standby to power back on."""
        return ends.add_roku(get_hub(), {"name": name, "host": host, "port": port, "device_id": device_id, "tags": tags})

    @server.tool()
    @expose
    def update_roku(roku_id: int, name: str | None = None, host: str | None = None, port: int | None = None, device_id: int | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Edit a Roku. Omit a field to leave it unchanged."""
        payload = {key: value for key, value in {"name": name, "host": host, "port": port, "device_id": device_id, "tags": tags}.items() if value is not None}
        return ends.update_roku(get_hub(), roku_id, payload)

    @server.tool()
    @expose
    def remove_roku(roku_id: int) -> dict[str, Any]:
        """Remove a Roku record. This does not change the TV."""
        ends.remove_roku(get_hub(), roku_id)
        return {"removed": roku_id}

    @server.tool()
    @expose
    def roku_status(roku_id: int) -> dict[str, Any]:
        """Read Roku power-mode, model and name from query/device-info."""
        return actions.roku_status(get_hub(), roku_id)

    @server.tool()
    @expose
    def roku_power(roku_id: int, action: str, confirm: bool = False) -> dict[str, Any]:
        """Send PowerOn, PowerOff or Power. off and toggle require confirm=true because they can turn the TV off."""
        return actions.roku_power(get_hub(), roku_id, action, confirm=confirm, source="mcp")

    @server.tool()
    @expose
    def list_tags() -> list[str]:
        """List the tags used on computers and hardware. Matching is case-insensitive."""
        from wakehub.tags import list_tags as collect

        return collect(get_hub())

    @server.tool()
    @expose
    def tag_action(tags: list[str], action: str, confirm: bool = False) -> dict[str, Any]:
        """Wake computers, or power plugs and Rokus, that have every named tag. wake, on and off all require confirm=true."""
        return actions.tag_action(get_hub(), tags, action, confirm=confirm, source="mcp")

    @server.tool()
    @expose
    def list_salvos() -> list[dict[str, Any]]:
        """List saved salvos, the named scenes such as Home Away or All Lights Off. Call this before run_salvo and use the slug it returns. This does not change power. schedule is unused."""
        from wakehub.salvos import list_salvos as collect

        return collect(get_hub())

    @server.tool()
    @expose
    def get_salvo(salvo: str) -> dict[str, Any]:
        """Read one salvo by slug or numeric id, including its ordered steps. Does not change power."""
        from wakehub.salvos import get_salvo as read

        return read(get_hub(), salvo)

    @server.tool()
    @expose
    def add_salvo(name: str, steps: list[dict] | None = None, on_error: str = "stop", slug: str | None = None) -> dict[str, Any]:
        """Save a salvo. Each step targets one device, plug, or Roku, or a tag list that must all match. action is wake, on, off, cycle, or shutdown. delay_seconds waits before that step. on_error is stop or continue. slug is the stable path; leave it empty to build one from the name."""
        from wakehub.salvos import add_salvo as create

        return create(get_hub(), {"name": name, "steps": steps or [], "on_error": on_error, "slug": slug})

    @server.tool()
    @expose
    def update_salvo(salvo: str, name: str | None = None, steps: list[dict] | None = None, on_error: str | None = None, slug: str | None = None) -> dict[str, Any]:
        """Edit a salvo by slug or numeric id. Omit a field to leave it unchanged. Renaming does not change the slug unless slug is sent."""
        from wakehub.salvos import update_salvo as edit

        payload = {key: value for key, value in {"name": name, "steps": steps, "on_error": on_error, "slug": slug}.items() if value is not None}
        return edit(get_hub(), salvo, payload)

    @server.tool()
    @expose
    def remove_salvo(salvo: str) -> dict[str, Any]:
        """Remove a salvo by slug or numeric id. This does not change power state."""
        from wakehub.salvos import remove_salvo as delete

        delete(get_hub(), salvo)
        return {"removed": salvo}

    @server.tool()
    @expose
    def duplicate_salvo(salvo: str) -> dict[str, Any]:
        """Copy a salvo to a new name and a new slug. The copy is not scheduled and does not run."""
        from wakehub.salvos import duplicate_salvo as copy

        return copy(get_hub(), salvo)

    @server.tool()
    @expose
    def run_salvo(salvo: str, confirm: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """Run one saved salvo by its slug, or by numeric id. Use this when the user asks to run a scene, a salvo, or a named sequence such as Home Away or All Lights Off. Do not wake or power devices one by one when a salvo already covers the request. dry_run=true lists each device that would be hit and changes nothing. A real run requires confirm=true. The results list is one entry per device, with action, kind, id, name, ok, and detail, and each device is also written to history."""
        from wakehub.salvos import run_salvo as execute

        return execute(get_hub(), salvo, confirm=confirm, dry_run=dry_run, source="mcp")

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
    def scan_subnet(cidr: str | None = None, replace: bool = False) -> dict[str, Any]:
        """Start a background subnet scan. Omit cidr to use this host's subnet. replace=true removes finished scans of that same subnet first and does not remove inventory devices. Requires host networking for ARP. Returns the scan id immediately; poll scan_results."""
        return scansvc.start_scan(get_hub(), cidr, replace=replace)

    @server.tool()
    @expose
    def bulk_remove(confirm: bool = False, targets: list[dict] | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        """Delete devices and hardware by id or by tag. confirm=false lists what would be deleted, including salvos that would lose a step, and changes nothing. confirm=true deletes them, unlinks plug and PDU outlet mappings, and drops salvo steps that targeted them. Tags must all match. Inventory is not affected by scan deletion; this tool is the one that deletes records."""
        from wakehub.removal import bulk_remove as remove

        return remove(get_hub(), confirm=confirm, targets=targets or [], tags=tags or [])

    @server.tool()
    @expose
    def delete_scan(scan_id: int) -> dict[str, Any]:
        """Delete one finished scan and its discovered hosts. Inventory devices are not removed. A running scan cannot be deleted."""
        return scansvc.delete_scan(get_hub(), scan_id)

    @server.tool()
    @expose
    def clear_scans(confirm: bool = False) -> dict[str, Any]:
        """Delete every finished scan and its discovered hosts. Requires confirm=true. Inventory devices are not removed. A scan that is still running is left in place."""
        return scansvc.clear_scans(get_hub(), confirm=confirm)

    @server.tool()
    @expose
    def rescan(scan_id: int, replace: bool = True) -> dict[str, Any]:
        """Run a past scan again with the same subnet. replace=true removes finished results for that subnet first. replace=false keeps them and starts a new scan. Inventory devices are not removed."""
        return scansvc.rescan(get_hub(), scan_id, replace=replace)

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
    def add_from_scan(scan_id: int, host_id: int, kind: str, name: str | None = None, password: str | None = None, username: str | None = None, community: str | None = None, plug_kind: str | None = None, device_id: int | None = None) -> dict[str, Any]:
        """Add one discovered host. kind is device, pdu, amt, jetkvm, plug or ups. Pass device_id to attach the hardware to that device. AMT needs password."""
        payload = {key: value for key, value in {"name": name, "password": password, "username": username, "community": community, "plug_kind": plug_kind, "device_id": device_id}.items() if value is not None}
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
    def remove_credential_profile(profile_id: int, force: bool = False) -> dict[str, Any]:
        """Remove a saved login. Refuses when a device still uses it, naming those devices, unless force is true. force clears the link on every hardware record and leaves each device's own password in place."""
        from wakehub.credentials import remove_profile

        remove_profile(get_hub(), profile_id, force=force)
        return {"removed": profile_id}
