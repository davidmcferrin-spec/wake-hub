"""Shelly Gen2+ local RPC. Plug US Gen4 uses the same Switch methods."""

from __future__ import annotations

import json
import ssl
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener

from wakehub.errors import UpstreamError


def parse_switch_status(payload: dict) -> dict:
    data = payload.get("result", payload)
    if not isinstance(data, dict):
        raise UpstreamError("Shelly status was not an object")
    energy = data.get("aenergy") if isinstance(data.get("aenergy"), dict) else {}
    return {
        "on": bool(data.get("output")),
        "power_w": _num(data.get("apower")),
        "voltage_v": _num(data.get("voltage")),
        "current_a": _num(data.get("current")),
        "energy_wh": _num(energy.get("total")),
    }


def parse_shelly_info(payload: dict) -> dict:
    return {
        "model": payload.get("model") or payload.get("app") or "",
        "generation": payload.get("gen"),
        "mac": payload.get("mac") or "",
        "auth_required": bool(payload.get("auth_en")),
        "name": payload.get("name") or "",
    }


def _num(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


class ShellyClient:
    def __init__(self, host: str, username: str = "", password: str = "", *, port: int = 80, use_tls: bool = False, switch_id: int = 0, timeout: float = 8, poster=None):
        scheme = "https" if use_tls else "http"
        self.base = f"{scheme}://{host}:{port}"
        self.switch_id = switch_id
        self._timeout = timeout
        self._poster = poster
        if poster is None and username:
            manager = HTTPPasswordMgrWithDefaultRealm()
            manager.add_password(None, self.base, username, password)
            handlers = [HTTPDigestAuthHandler(manager)]
            if use_tls:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                import urllib.request

                handlers.append(urllib.request.HTTPSHandler(context=context))
            self._opener = build_opener(*handlers)
        else:
            self._opener = build_opener()

    def info(self) -> dict:
        return parse_shelly_info(self._json("GET", "/shelly", None))

    def status(self) -> dict:
        return parse_switch_status(self._rpc("Switch.GetStatus", {"id": self.switch_id}))

    def set_on(self, on: bool) -> dict:
        self._rpc("Switch.Set", {"id": self.switch_id, "on": on})
        return {"on": on}

    def toggle(self) -> dict:
        self._rpc("Switch.Toggle", {"id": self.switch_id})
        return self.status()

    def _rpc(self, method: str, params: dict) -> dict:
        return self._json("POST", f"/rpc/{method}", params)

    def _json(self, method: str, path: str, body: dict | None) -> dict:
        raw = None if body is None else json.dumps(body).encode("utf-8")
        if self._poster is not None:
            status, text = self._poster(method, path, raw)
        else:
            request = Request(self.base + path, data=raw, method=method)
            if raw is not None:
                request.add_header("Content-Type", "application/json")
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    status = response.status
                    text = response.read().decode("utf-8", errors="replace")
            except OSError as exc:
                raise UpstreamError(f"Shelly request failed: {exc}") from exc
        if status == 401:
            raise UpstreamError("Shelly rejected the digest credentials")
        if status >= 400:
            raise UpstreamError(f"Shelly HTTP {status}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpstreamError("Shelly response was not JSON") from exc
