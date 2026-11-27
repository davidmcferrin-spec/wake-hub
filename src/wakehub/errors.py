"""Errors the API and MCP turn into specific responses."""


class WakeHubError(Exception):
    status = 400
    code = "invalid"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code

    @property
    def message(self) -> str:
        return str(self)


class NotFound(WakeHubError):
    status = 404
    code = "not_found"


class Conflict(WakeHubError):
    status = 409
    code = "conflict"


class ConfirmationRequired(WakeHubError):
    status = 409
    code = "confirmation_required"


class DisabledDevice(WakeHubError):
    status = 409
    code = "device_disabled"


class Unauthorized(WakeHubError):
    status = 401
    code = "unauthorized"


class UpstreamError(WakeHubError):
    status = 502
    code = "upstream"


# Turning a machine off, or cycling power, must be explicit on the API and MCP.
DESTRUCTIVE_ACTIONS = frozenset({"off", "cycle", "reboot", "shutdown"})


def require_confirm(action: str, confirm: bool) -> None:
    if action in DESTRUCTIVE_ACTIONS and confirm is not True:
        raise ConfirmationRequired(f"{action} is destructive; set confirm to true")
