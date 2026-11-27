"""Roku local External Control Protocol. HTTP on port 8060, no account."""

from __future__ import annotations

import re
import socket
import time
import xml.etree.ElementTree as ET

import httpx

from wakehub.errors import UpstreamError, WakeHubError
from wakehub.inventory import host_for_url

KEYS = {"on": "PowerOn", "off": "PowerOff", "toggle": "Power"}
_LOCATION = re.compile(r"https?://([^/:\s]+):(\d+)")


def parse_device_info(body: str) -> dict[str, str | bool]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise UpstreamError("Roku device-info was not XML") from exc

    def text(tag: str) -> str:
        node = root.find(tag)
        if node is None or not node.text:
            return ""
        return node.text.strip()

    power = text("power-mode")
    state = {"PowerOn": "On", "DisplayOff": "Standby", "Ready": "Standby", "Headless": "Off", "Suspend": "Off"}.get(power, "Off")
    name = text("user-device-name") or text("friendly-device-name") or text("default-device-name")
    model = text("model-name") or text("friendly-model-name")
    vendor = text("vendor-name")
    if root.tag != "device-info" and not power and "roku" not in vendor.lower():
        raise UpstreamError("Roku device-info was not recognized")
    return {
        "name": name,
        "model": model,
        "power_mode": power,
        "power_state": state,
        "on": power == "PowerOn",
        "vendor": vendor,
        "serial": text("serial-number"),
    }


def parse_ssdp(body: str, sender: str | None = None) -> dict[str, str | int] | None:
    if "roku:ecp" not in body.lower():
        return None
    location = ""
    for line in body.splitlines():
        if line.lower().startswith("location:"):
            location = line.split(":", 1)[1].strip()
            break
    match = _LOCATION.match(location) if location else None
    # The packet's source address is the player. LOCATION can name a different host.
    if sender:
        port = int(match.group(2)) if match else 8060
        return {"ip": sender, "port": port, "location": location}
    if not match:
        return None
    return {"ip": match.group(1), "port": int(match.group(2)), "location": location}


def discover_ecp(timeout: float = 0.8) -> list[dict[str, str | int]]:
    """Ask the LAN for roku:ecp. Silence means none answered."""
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: roku:ecp\r\n"
        "\r\n"
    )
    found: list[dict[str, str | int]] = []
    seen: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.settimeout(0.2)
        sock.sendto(message.encode("ascii"), ("239.255.255.250", 1900))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                packet, addr = sock.recvfrom(4096)
            except (TimeoutError, OSError):
                continue
            parsed = parse_ssdp(packet.decode("utf-8", "replace"), addr[0])
            if parsed and str(parsed["ip"]) not in seen:
                seen.add(str(parsed["ip"]))
                found.append(parsed)
        sock.close()
    except OSError:
        return found
    return found


class RokuClient:
    def __init__(self, host: str, *, port: int = 8060, timeout: float = 4, http: httpx.Client | None = None):
        self._base = f"http://{host_for_url(host)}:{int(port)}"
        self._owns = http is None
        self._http = http or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns:
            self._http.close()

    def device_info(self) -> dict[str, str | bool]:
        return parse_device_info(self._request("GET", "/query/device-info").text)

    def keypress(self, key: str) -> None:
        if key not in KEYS.values():
            raise WakeHubError("Roku key must be Power, PowerOn, or PowerOff")
        self._request("POST", f"/keypress/{key}")

    def _request(self, method: str, path: str) -> httpx.Response:
        try:
            response = self._http.request(method, self._base + path)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Roku request failed: {exc}") from exc
        if response.status_code in {401, 403}:
            raise UpstreamError("Roku refused the command. Enable Control by mobile apps on the TV.")
        if response.status_code >= 400:
            raise UpstreamError(f"Roku HTTP {response.status_code}")
        return response
