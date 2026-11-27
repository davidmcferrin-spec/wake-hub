"""JetKVM local control.

HTTP covers login, reachability and the console URL. Power and LED state
use the device's JSON-RPC methods. The live transport is a WebRTC data
channel negotiated on /webrtc/signaling/client. Tests inject a transport.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import urlencode

import httpx

from wakehub.errors import UpstreamError, WakeHubError

ATX_ACTIONS = {"power-short", "power-long", "reset"}
DESTRUCTIVE_ATX = {"power-long", "reset"}


def parse_device_status(payload: dict) -> dict:
    if "isSetup" not in payload and "sku" not in payload:
        raise UpstreamError("response is not a JetKVM device status")
    return {"is_setup": bool(payload.get("isSetup")), "sku": payload.get("sku") or ""}


def parse_device(payload: dict) -> dict:
    return {
        "auth_mode": payload.get("authMode") or "",
        "device_id": payload.get("deviceId") or "",
        "loopback_only": bool(payload.get("loopbackOnly")),
    }


def rpc_request(method: str, params: dict | None, request_id: int) -> str:
    body: dict = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params:
        body["params"] = params
    return json.dumps(body)


def parse_rpc(message: str) -> dict:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as exc:
        raise UpstreamError("JetKVM RPC message was not JSON") from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise UpstreamError("JetKVM RPC message was not JSON-RPC 2.0")
    if payload.get("error"):
        error = payload["error"]
        text = error.get("message") if isinstance(error, dict) else str(error)
        raise UpstreamError(f"JetKVM RPC error: {text}")
    return payload


def signaling_offer(session_description: dict) -> dict:
    encoded = base64.b64encode(json.dumps(session_description).encode("utf-8")).decode("ascii")
    return {"type": "offer", "data": {"sd": encoded}}


def parse_signaling_answer(message: dict) -> dict:
    if message.get("type") != "answer":
        raise UpstreamError("JetKVM signaling message was not an answer")
    data = message.get("data")
    if not isinstance(data, str):
        raise UpstreamError("JetKVM answer was not a base64 session description")
    try:
        raw = base64.b64decode(data)
        description = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise UpstreamError("JetKVM answer could not be decoded") from exc
    if "sdp" not in description:
        raise UpstreamError("JetKVM answer did not include SDP")
    return description


def parse_atx_state(result: dict) -> dict:
    return {"power_led": bool(result.get("power")), "hdd_led": bool(result.get("hdd"))}


def parse_dc_state(result: dict) -> dict:
    return {
        "on": bool(result.get("isOn")),
        "voltage_v": result.get("voltage"),
        "current_a": result.get("current"),
        "power_w": result.get("power"),
        "restore_state": result.get("restoreState"),
    }


class JetKvmClient:
    def __init__(
        self,
        host: str,
        password: str = "",
        *,
        port: int = 80,
        use_tls: bool = False,
        insecure_tls: bool = True,
        timeout: float = 8,
        http: httpx.Client | None = None,
        rpc=None,
    ):
        scheme = "https" if use_tls else "http"
        self.base = f"{scheme}://{host}:{port}"
        self.password = password
        self._rpc = rpc
        self._owns = http is None
        self._http = http or httpx.Client(timeout=timeout, verify=not insecure_tls)

    def close(self) -> None:
        if self._owns:
            self._http.close()

    def console_url(self) -> str:
        return self.base + "/"

    def reachable(self) -> dict:
        try:
            response = self._http.get(self.base + "/device/status")
        except httpx.HTTPError as exc:
            raise UpstreamError(f"JetKVM did not answer: {exc}") from exc
        if response.status_code >= 400:
            raise UpstreamError(f"JetKVM HTTP {response.status_code}")
        try:
            info = parse_device_status(response.json())
        except json.JSONDecodeError as exc:
            raise UpstreamError("JetKVM status was not JSON") from exc
        info["reachable"] = True
        info["console_url"] = self.console_url()
        return info

    def device(self) -> dict:
        self._login_if_needed()
        response = self._request("GET", "/device")
        try:
            return parse_device(response.json())
        except json.JSONDecodeError as exc:
            raise UpstreamError("JetKVM device info was not JSON") from exc

    def status(self) -> dict:
        info = self.reachable()
        if self._rpc is None and not self.password and info.get("is_setup"):
            try:
                info.update(self.device())
            except UpstreamError:
                pass
        extension = self._call("getActiveExtension", None)
        info["extension"] = extension if isinstance(extension, str) else ""
        if info["extension"] == "dc-power":
            info["dc"] = parse_dc_state(self._call("getDCPowerState", None) or {})
            info["atx"] = None
        else:
            info["atx"] = parse_atx_state(self._call("getATXState", None) or {})
            info["dc"] = None
        return info

    def atx_action(self, action: str) -> dict:
        if action not in ATX_ACTIONS:
            raise WakeHubError("JetKVM ATX action must be power-short, power-long, or reset")
        self._call("setATXPowerAction", {"action": action})
        return {"action": action, "extension": "atx-power"}

    def dc_set(self, on: bool) -> dict:
        self._call("setDCPowerState", {"enabled": on})
        return {"on": on, "extension": "dc-power"}

    def _call(self, method: str, params: dict | None):
        if self._rpc is not None:
            return self._rpc(method, params)
        from wakehub.clients.jetkvm_webrtc import rpc_call

        self._login_if_needed()
        cookie = self._http.cookies.get("authToken", "")
        return rpc_call(self.base, cookie, method, params)

    def _login_if_needed(self) -> None:
        if not self.password:
            return
        if self._http.cookies.get("authToken"):
            return
        response = self._request("POST", "/auth/login-local", {"password": self.password})
        if response.status_code == 401:
            raise UpstreamError("JetKVM rejected the password")
        if response.status_code >= 400:
            raise UpstreamError(f"JetKVM login HTTP {response.status_code}")

    def _request(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        try:
            return self._http.request(method, self.base + path, json=body)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"JetKVM request failed: {exc}") from exc


def discovery_query(ip: str) -> str:
    return urlencode({"ip": ip})
