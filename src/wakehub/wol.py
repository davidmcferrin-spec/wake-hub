"""Wake-on-LAN magic packets and reachability probes."""

from __future__ import annotations

import re
import socket
import subprocess
import time

from wakehub.errors import UpstreamError, WakeHubError

_MAC_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
_HEX_PASSWORD = re.compile(r"^[0-9a-fA-F]{12}$")


def normalize_mac(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(cleaned) != 12:
        raise WakeHubError("MAC address must be 6 bytes, written as AA:BB:CC:DD:EE:FF")
    mac = ":".join(cleaned[i : i + 2] for i in range(0, 12, 2)).upper()
    if not _MAC_RE.match(mac):
        raise WakeHubError("MAC address must be 6 bytes, written as AA:BB:CC:DD:EE:FF")
    return mac


def mac_bytes(mac: str) -> bytes:
    return bytes.fromhex(mac.replace(":", ""))


def parse_secureon(value: str) -> bytes:
    """SecureOn is a 6-byte password appended to the magic packet."""
    raw = value.strip()
    if _HEX_PASSWORD.fullmatch(raw):
        return bytes.fromhex(raw)
    try:
        data = raw.encode("ascii")
    except UnicodeEncodeError as exc:
        raise WakeHubError("SecureOn password must be 6 ASCII characters or 12 hex digits") from exc
    if len(data) != 6:
        raise WakeHubError("SecureOn password must be 6 ASCII characters or 12 hex digits")
    return data


def build_magic_packet(mac: str, secureon: bytes | None = None) -> bytes:
    payload = b"\xff" * 6 + mac_bytes(mac) * 16
    if secureon is not None:
        if len(secureon) != 6:
            raise WakeHubError("SecureOn password must be 6 bytes")
        payload += secureon
    return payload


def send_magic_packet(packet: bytes, broadcast: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.sendto(packet, (broadcast, port))
        except OSError as exc:
            raise UpstreamError(f"could not send magic packet to {broadcast}:{port}: {exc}") from exc
    finally:
        sock.close()


def ping(host: str, timeout: float = 1) -> bool:
    wait = max(1, int(timeout))
    try:
        completed = subprocess.run(
            ["ping", "-c", "1", "-W", str(wait), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=wait + 2,
            check=False,
        )
    except FileNotFoundError as exc:
        raise UpstreamError("ping is not installed; use TCP reachability or install iputils-ping") from exc
    except subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


def tcp_open(host: str, port: int, timeout: float = 1) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_until_reachable(
    host: str | None,
    mode: str,
    port: int | None,
    timeout: float,
) -> tuple[bool | None, float]:
    """Poll until the host answers or the timeout elapses.

    Returns (None, 0) when there is no host to probe. The packet was still sent.
    """
    if not host:
        return None, 0.0
    if mode == "tcp" and not port:
        raise WakeHubError("TCP reachability needs a port")
    started = time.monotonic()
    deadline = started + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, time.monotonic() - started
        probe_timeout = min(1.0, remaining)
        if mode == "tcp":
            up = tcp_open(host, int(port), probe_timeout)
        elif mode == "icmp":
            up = ping(host, probe_timeout)
        else:
            raise WakeHubError("reach_mode must be icmp or tcp")
        if up:
            return True, time.monotonic() - started
        if time.monotonic() >= deadline:
            return False, time.monotonic() - started
        time.sleep(min(0.4, max(0.0, deadline - time.monotonic())))
