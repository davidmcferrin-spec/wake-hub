"""REST API. The browser, scripts and Life-Dashboard all use these routes."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from wakehub import __version__
from wakehub.errors import Unauthorized, WakeHubError
from wakehub.hub import Hub, get_hub, set_hub
from wakehub import sessions as ui_sessions
from wakehub.inventory import (
    add_device,
    get_device,
    list_actions,
    list_devices,
    power_action,
    probe_all,
    probe_device,
    public_settings,
    remove_device,
    set_enabled,
    token_matches,
    ui_login,
    ui_setup,
    update_device,
    update_settings,
    wake_device,
)

STATIC = Path(__file__).resolve().parent / "web" / "static"

PUBLIC = {
    ("GET", "/"),
    ("GET", "/healthz"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("GET", "/favicon.ico"),
    ("POST", "/api/v1/ui/login"),
    ("POST", "/api/v1/ui/logout"),
    ("POST", "/api/v1/ui/setup"),
    ("GET", "/api/v1/ui/session"),
}


def request_source(request: Request) -> str:
    if request.headers.get("x-wake-hub-source", "").lower() == "ui":
        return "ui"
    return "api"


def is_public(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return True
    if path.startswith("/static/"):
        return True
    return (method, path) in PUBLIC


class DeviceIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    mac: str | None = None
    host: str | None = None
    broadcast: str = "255.255.255.255"
    wol_port: int = 9
    secureon: str | None = None
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    reach_mode: Literal["icmp", "tcp"] = "icmp"
    reach_port: int | None = None
    reach_timeout: float = 30
    wake_strategy: Literal["wol_only", "power_then_wol"] = "wol_only"
    methods: list[dict[str, Any]] | None = None


class DevicePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    mac: str | None = None
    host: str | None = None
    broadcast: str | None = None
    wol_port: int | None = None
    secureon: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None
    reach_mode: Literal["icmp", "tcp"] | None = None
    reach_port: int | None = None
    reach_timeout: float | None = None
    wake_strategy: Literal["wol_only", "power_then_wol"] | None = None
    methods: list[dict[str, Any]] | None = None


class EnabledIn(BaseModel):
    enabled: bool


class WakeIn(BaseModel):
    timeout: float | None = None


class PowerIn(BaseModel):
    action: Literal["on", "off", "cycle", "reboot", "shutdown"]
    method: str = "wol"
    confirm: bool = False


class SettingsIn(BaseModel):
    ui_password: str | None = None
    clear_ui_password: bool = False
    cors_origins: list[str] | None = None
    metrics_poll_seconds: int | None = None
    metrics_retention_days: int | None = None
    session_days: int | None = None


class LoginIn(BaseModel):
    password: str


class SetupIn(BaseModel):
    api_token: str
    password: str


bearer_scheme = HTTPBearer(auto_error=False)


def require_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise Unauthorized("Bearer token required")
    if not token_matches(credentials.credentials, get_hub().token):
        raise Unauthorized("Bearer token is wrong")
    return credentials.credentials


def _cors_headers(origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Wake-Hub-Source",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    allowed = get_hub().cors_origins()
    return "*" in allowed or origin in allowed


class DynamicCORS:
    """CORS origins are a setting, so they are read on each request."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        origin = Headers(scope=scope).get("origin")
        allowed = bool(origin) and _origin_allowed(origin)
        if scope["method"] == "OPTIONS" and origin:
            response = Response(status_code=204, headers=_cors_headers(origin) if allowed else {})
            await response(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start" and origin and allowed:
                headers = MutableHeaders(scope=message)
                for key, value in _cors_headers(origin).items():
                    headers[key] = value
            await send(message)

        await self.app(scope, receive, send_with_cors)


class BearerAuth:
    """Rejects /api and /mcp calls that do not carry the bearer token.

    Implemented as raw ASGI so the MCP stream is not buffered by BaseHTTPMiddleware.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if is_public(method, path):
            await self.app(scope, receive, send)
            return
        header = Headers(scope=scope).get("authorization", "")
        presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not presented or not token_matches(presented, get_hub().token):
            response = JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthorized", "message": "Bearer token required"}},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(hub: Hub) -> FastAPI:
    from contextlib import asynccontextmanager

    from mcp.server.transport_security import TransportSecuritySettings

    from wakehub.mcp_server import build_server

    set_hub(hub)
    # Built before FastAPI so the lifespan can enter the session manager. The inner path is /
    # because the app is mounted at /mcp. DNS-rebinding protection is off: callers use a LAN IP.
    mcp_server = build_server()
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from wakehub.metrics import start_poller

        stop_metrics = start_poller(hub)
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            stop_metrics.set()

    app = FastAPI(
        title="Wake Hub",
        version=__version__,
        lifespan=lifespan,
        summary="LAN power control for Wake-on-LAN, Synaccess, Intel AMT, JetKVM, Shelly, Kasa and CyberPower UPS.",
        description=(
            "Versioned REST API at /api/v1. Send Authorization: Bearer <token>. "
            "The token is written to /config/token and the container log. "
            "The web UI requires a password. A signed-in browser can read the token from the session. "
            "The same token authenticates the MCP endpoint at /mcp."
        ),
    )
    app.add_exception_handler(WakeHubError, _error_response)
    app.add_middleware(BearerAuth)
    app.add_middleware(DynamicCORS)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/mcp", mcp_app)
    from wakehub.routes_control import control_router

    app.include_router(_public_router())
    app.include_router(_api_router())
    app.include_router(control_router())

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app


def _client_key(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _start_ui_session(hub: Hub, response: Response) -> None:
    ui_sessions.issue(hub, response)


def _error_response(_request: Request, exc: WakeHubError) -> JSONResponse:
    error = {"code": exc.code, "message": exc.message}
    existing = getattr(exc, "existing", None)
    if existing:
        error["existing"] = existing
    return JSONResponse(status_code=exc.status, content={"error": error})


def _public_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post("/ui/setup", tags=["settings"])
    def setup(body: SetupIn, request: Request, response: Response) -> dict[str, Any]:
        hub = get_hub()
        result = ui_setup(hub, body.api_token, body.password, client=_client_key(request))
        _start_ui_session(hub, response)
        return result

    @router.post("/ui/login", tags=["settings"])
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        hub = get_hub()
        result = ui_login(hub, body.password, client=_client_key(request))
        _start_ui_session(hub, response)
        return result

    @router.post("/ui/logout", tags=["settings"])
    def logout(request: Request, response: Response) -> dict[str, Any]:
        hub = get_hub()
        ui_sessions.drop(hub, request.cookies.get(ui_sessions.COOKIE, ""))
        ui_sessions.clear_cookie(response)
        return {"ok": True}

    @router.get("/ui/session", tags=["settings"])
    def session(request: Request):
        hub = get_hub()
        password_set = bool(hub.setting("ui_password"))
        cookie = request.cookies.get(ui_sessions.COOKIE, "")
        if not password_set or not ui_sessions.valid(hub, cookie):
            # No token in this body. The API token is only for the first setup.
            return JSONResponse(
                status_code=401,
                content={
                    "error": {"code": "unauthorized", "message": "UI login required"},
                    "setup_required": not password_set,
                    "password_required": True,
                },
            )
        response = JSONResponse(
            {"token": hub.token, "password_required": True, "setup_required": False}
        )
        ui_sessions.slide(hub, response, cookie)
        return response

    return router


def _api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_bearer)])

    @router.get("/devices", tags=["devices"])
    def devices(tag: str | None = None, tags: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        return list_devices(get_hub(), tag=tag, tags=tags, q=q)

    @router.post("/devices", tags=["devices"], status_code=201)
    def create_device(body: DeviceIn) -> dict[str, Any]:
        return add_device(get_hub(), body.model_dump())

    @router.get("/devices/{device_id}", tags=["devices"])
    def read_device(device_id: int) -> dict[str, Any]:
        return get_device(get_hub(), device_id)

    @router.patch("/devices/{device_id}", tags=["devices"])
    def patch_device(device_id: int, body: DevicePatch) -> dict[str, Any]:
        return update_device(get_hub(), device_id, body.model_dump(exclude_unset=True))

    @router.delete("/devices/{device_id}", tags=["devices"], status_code=204)
    def delete_device(device_id: int) -> Response:
        remove_device(get_hub(), device_id)
        return Response(status_code=204)

    @router.post("/devices/{device_id}/enabled", tags=["devices"])
    def enable_device(device_id: int, body: EnabledIn) -> dict[str, Any]:
        return set_enabled(get_hub(), device_id, body.enabled)

    @router.post("/devices/{device_id}/wake", tags=["power"])
    def wake(device_id: int, request: Request, body: WakeIn | None = Body(default=None)) -> dict[str, Any]:
        timeout = body.timeout if body else None
        return wake_device(get_hub(), device_id, source=request_source(request), timeout=timeout)

    @router.post("/devices/{device_id}/power", tags=["power"])
    def power(device_id: int, body: PowerIn, request: Request) -> dict[str, Any]:
        return power_action(
            get_hub(),
            device_id,
            action=body.action,
            method=body.method,
            confirm=body.confirm,
            source=request_source(request),
        )

    @router.get("/devices/{device_id}/status", tags=["power"])
    def status(device_id: int) -> dict[str, Any]:
        return probe_device(get_hub(), device_id)

    @router.get("/status", tags=["power"])
    def status_all() -> list[dict[str, Any]]:
        return probe_all(get_hub())

    @router.get("/actions", tags=["actions"])
    def actions(
        limit: int = Query(default=100, ge=1, le=500),
        device_id: int | None = None,
    ) -> list[dict[str, Any]]:
        return list_actions(get_hub(), limit=limit, device_id=device_id)

    @router.get("/settings", tags=["settings"])
    def read_settings() -> dict[str, Any]:
        return public_settings(get_hub())

    @router.patch("/settings", tags=["settings"])
    def patch_settings(body: SettingsIn) -> dict[str, Any]:
        return update_settings(get_hub(), body.model_dump(exclude_unset=True))

    @router.get("/access-token", tags=["settings"])
    def access_token() -> dict[str, str]:
        return {"token": get_hub().token}

    @router.post("/access-token/rotate", tags=["settings"])
    def rotate() -> dict[str, str]:
        return {"token": get_hub().rotate_token()}

    return router

