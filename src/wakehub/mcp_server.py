"""MCP tools. Each one calls the same functions as the REST API."""

from __future__ import annotations

from functools import wraps
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from wakehub import __version__
from wakehub.errors import WakeHubError
from wakehub.hub import get_hub
from wakehub import inventory as records

INSTRUCTIONS = (
    "Wake Hub controls computers on the local network. "
    "list_devices shows the inventory. wake_device sends a Wake-on-LAN magic packet "
    "to an enabled device and reports whether it became reachable. "
    "power_action turns a device on; off, cycle, reboot and shutdown require confirm=true. "
    "Disabled devices cannot be powered. Never invent a device id; call list_devices first."
)


def expose(fn):
    """Turn a domain error into a tool error the model can read."""

    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except WakeHubError as exc:
            raise ToolError(f"{exc.code}: {exc.message}") from exc

    return wrapped


def build_server() -> MCPServer:
    server = MCPServer("Wake Hub", instructions=INSTRUCTIONS, version=__version__)

    @server.tool()
    @expose
    def list_devices(tag: str | None = None, tags: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        """List inventory devices, including disabled ones. Does not change power state. Filter with a tag, a comma-separated tags list (all must match), or a name, host or MAC substring. q understands #tag."""
        return records.list_devices(get_hub(), tag=tag, tags=tags, q=q)

    @server.tool()
    @expose
    def get_device(device_id: int) -> dict[str, Any]:
        """Read one device by id. Secrets such as a SecureOn password are not included; secureon_set says whether one is stored."""
        return records.get_device(get_hub(), device_id)

    @server.tool()
    @expose
    def add_device(
        name: str,
        mac: str | None = None,
        host: str | None = None,
        broadcast: str = "255.255.255.255",
        wol_port: int = 9,
        secureon: str | None = None,
        notes: str = "",
        tags: list[str] | None = None,
        enabled: bool = True,
        reach_mode: str = "icmp",
        reach_port: int | None = None,
        reach_timeout: float | None = None,
        wake_strategy: str = "wol_only",
        power_method: str = "auto",
        methods: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Add a device. mac is required later to wake it. broadcast is the directed broadcast address. wol_port is usually 9 or 7. reach_mode is icmp or tcp. wake_strategy is wol_only or power_then_wol."""
        return records.add_device(
            get_hub(),
            {
                "name": name,
                "mac": mac,
                "host": host,
                "broadcast": broadcast,
                "wol_port": wol_port,
                "secureon": secureon,
                "notes": notes,
                "tags": tags or [],
                "enabled": enabled,
                "reach_mode": reach_mode,
                "reach_port": reach_port,
                "reach_timeout": reach_timeout,
                "wake_strategy": wake_strategy,
                "power_method": power_method,
                "methods": methods,
            },
        )

    @server.tool()
    @expose
    def update_device(
        device_id: int,
        name: str | None = None,
        mac: str | None = None,
        host: str | None = None,
        broadcast: str | None = None,
        wol_port: int | None = None,
        secureon: str | None = None,
        notes: str | None = None,
        tags: list[str] | None = None,
        enabled: bool | None = None,
        reach_mode: str | None = None,
        reach_port: int | None = None,
        reach_timeout: float | None = None,
        wake_strategy: str | None = None,
        power_method: str | None = None,
        methods: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Edit a device. Omit a field to leave it unchanged. Pass an empty mac or secureon to clear it."""
        payload: dict[str, Any] = {}
        for key, value in {
            "name": name,
            "mac": mac,
            "host": host,
            "broadcast": broadcast,
            "wol_port": wol_port,
            "secureon": secureon,
            "notes": notes,
            "tags": tags,
            "enabled": enabled,
            "reach_mode": reach_mode,
            "reach_port": reach_port,
            "reach_timeout": reach_timeout,
            "wake_strategy": wake_strategy,
            "power_method": power_method,
            "methods": methods,
        }.items():
            if value is not None:
                payload[key] = value
        return records.update_device(get_hub(), device_id, payload)

    @server.tool()
    @expose
    def remove_device(device_id: int) -> dict[str, Any]:
        """Remove a device from the inventory. The action log is kept."""
        records.remove_device(get_hub(), device_id)
        return {"removed": device_id}

    @server.tool()
    @expose
    def set_device_enabled(device_id: int, enabled: bool) -> dict[str, Any]:
        """Enable or disable a device. Disabled devices stay in the list but wake and power actions are refused."""
        return records.set_enabled(get_hub(), device_id, enabled)

    @server.tool()
    @expose
    def wake_device(device_id: int, timeout: float | None = None, method: str = "auto") -> dict[str, Any]:
        """Wake an enabled device using its method priority, or method when that override is set. Wake-on-LAN then waits until the host answers or the timeout elapses."""
        return records.wake_device(get_hub(), device_id, source="mcp", timeout=timeout, method=method)

    @server.tool()
    @expose
    def power_action(
        device_id: int,
        action: str,
        method: str = "auto",
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Change power. action is on, off, cycle, reboot or shutdown. method is wol for Wake-on-LAN, which only supports on. off, cycle, reboot and shutdown require confirm=true."""
        return records.power_action(
            get_hub(),
            device_id,
            action=action,
            method=method,
            confirm=confirm,
            source="mcp",
        )

    @server.tool()
    @expose
    def device_status(device_id: int) -> dict[str, Any]:
        """Probe one device and report whether it is reachable. This does not send a magic packet."""
        return records.probe_device(get_hub(), device_id)

    @server.tool()
    @expose
    def list_status() -> list[dict[str, Any]]:
        """Probe every enabled device and report reachability. Disabled devices are skipped."""
        return records.probe_all(get_hub())

    @server.tool()
    @expose
    def list_actions(limit: int = 100, device_id: int | None = None) -> list[dict[str, Any]]:
        """Read the power and wake log. Each row has source ui, api or mcp, the time, and whether it succeeded."""
        return records.list_actions(get_hub(), limit=limit, device_id=device_id)

    @server.tool()
    @expose
    def get_settings() -> dict[str, Any]:
        """Read settings. The UI password itself is never returned; ui_password_set says whether one is stored."""
        return records.public_settings(get_hub())

    @server.tool()
    @expose
    def update_settings(
        ui_password: str | None = None,
        clear_ui_password: bool = False,
        cors_origins: list[str] | None = None,
        metrics_poll_seconds: int | None = None,
        metrics_retention_days: int | None = None,
        session_days: int | None = None,
        scan_keep: int | None = None,
        scan_keep_days: int | None = None,
        default_wake_timeout: float | None = None,
    ) -> dict[str, Any]:
        """Change settings. Set ui_password to require a password in the browser. clear_ui_password removes it. cors_origins is the list of allowed browser origins. An empty list blocks cross-origin calls."""
        payload: dict[str, Any] = {"clear_ui_password": clear_ui_password}
        if ui_password is not None:
            payload["ui_password"] = ui_password
        if cors_origins is not None:
            payload["cors_origins"] = cors_origins
        if metrics_poll_seconds is not None:
            payload["metrics_poll_seconds"] = metrics_poll_seconds
        if metrics_retention_days is not None:
            payload["metrics_retention_days"] = metrics_retention_days
        if session_days is not None:
            payload["session_days"] = session_days
        if scan_keep is not None:
            payload["scan_keep"] = scan_keep
        if scan_keep_days is not None:
            payload["scan_keep_days"] = scan_keep_days
        if default_wake_timeout is not None:
            payload["default_wake_timeout"] = default_wake_timeout
        return records.update_settings(get_hub(), payload)

    @server.tool()
    @expose
    def get_access_token() -> dict[str, str]:
        """Return the bearer token used by the REST API and MCP. The caller already presented this token."""
        return {"token": get_hub().token}

    @server.tool()
    @expose
    def rotate_token() -> dict[str, str]:
        """Replace the bearer token. The old token stops working immediately, including the one this session used."""
        return {"token": get_hub().rotate_token()}

    @server.tool()
    @expose
    def ui_login(password: str) -> dict[str, Any]:
        """Check the web UI password. Fails when no UI password is set or the password is wrong. Does not return the bearer token."""
        return records.ui_login(get_hub(), password, client="mcp")

    @server.tool()
    @expose
    def ui_setup(api_token: str, password: str) -> dict[str, Any]:
        """Set the web UI password on first run. api_token is the bearer token from /config/token or the container log. The password must be at least 8 characters."""
        return records.ui_setup(get_hub(), api_token, password, client="mcp")

    @server.tool()
    @expose
    def get_ui_session() -> dict[str, Any]:
        """Report whether the web UI still needs first-run setup. Does not return the bearer token."""
        hub = get_hub()
        password_set = bool(hub.setting("ui_password"))
        return {"password_required": True, "setup_required": not password_set}

    @server.tool()
    @expose
    def ui_logout() -> dict[str, Any]:
        """Sign the web UI out. Clears every browser session. Rotating the API token does the same."""
        from wakehub.sessions import drop_all

        drop_all(get_hub())
        return {"ok": True}

    from wakehub.mcp_extra import register

    register(server)
    return server
