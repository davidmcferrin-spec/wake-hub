"""Synaccess netBooter HTTP command interface.

NP-1601DU and the other DU models report inlet (bank) current, not per-outlet current.
The status string's right-most bit is outlet 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from wakehub.errors import UpstreamError


@dataclass(frozen=True)
class Outlet:
    number: int
    on: bool
    name: str


@dataclass(frozen=True)
class PduStatus:
    outlets: tuple[Outlet, ...]
    bank_amps: tuple[float, ...]
    temperature_c: float | None
    raw: str


def parse_status(body: str, names: dict[int, str] | None = None) -> PduStatus:
    text = _payload(body)
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) < 2 or not parts[0] or any(ch not in "01" for ch in parts[0]):
        raise UpstreamError(f"Synaccess status was not understood: {text!r}")
    bits = parts[0]
    numbers: list[float] = []
    for part in parts[1:]:
        try:
            numbers.append(float(part))
        except ValueError as exc:
            raise UpstreamError(f"Synaccess status field {part!r} is not a number") from exc
    # One current plus temperature, or two bank currents plus temperature.
    if len(numbers) >= 3:
        currents = tuple(numbers[:-1])
        temperature = numbers[-1]
    elif len(numbers) == 2:
        currents = (numbers[0],)
        temperature = numbers[1]
    else:
        currents = tuple(numbers)
        temperature = None
    labels = names or {}
    outlets = tuple(
        Outlet(number=index, on=bit == "1", name=labels.get(index) or f"Outlet {index}")
        for index, bit in enumerate(reversed(bits), start=1)
    )
    return PduStatus(outlets=outlets, bank_amps=currents, temperature_c=temperature, raw=text)


def parse_result(body: str) -> None:
    text = _payload(body)
    if "$A0" in text and "$AF" not in text:
        return
    if "$AF" in text:
        raise UpstreamError("Synaccess refused the command")
    raise UpstreamError(f"Synaccess returned an unknown result: {text!r}")


def _payload(body: str) -> str:
    lines = [line.strip() for line in body.replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        raise UpstreamError("Synaccess returned an empty body")
    return lines[-1]


class SynaccessClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 80,
        use_tls: bool = False,
        timeout: float = 8,
        http: httpx.Client | None = None,
    ):
        scheme = "https" if use_tls else "http"
        self._base = f"{scheme}://{host}:{port}/cmd.cgi?"
        self._owns = http is None
        self._http = http or httpx.Client(auth=(username, password), timeout=timeout, verify=False)

    def close(self) -> None:
        if self._owns:
            self._http.close()

    def status(self, names: dict[int, str] | None = None) -> PduStatus:
        return parse_status(self._command("$A5"), names)

    def set_outlet(self, outlet: int, on: bool) -> None:
        parse_result(self._command(f"$A3 {int(outlet)} {1 if on else 0}"))

    def reboot_outlet(self, outlet: int) -> None:
        parse_result(self._command(f"$A4 {int(outlet)}"))

    def set_all(self, on: bool) -> None:
        parse_result(self._command(f"$A7 {1 if on else 0}"))

    def _command(self, command: str) -> str:
        url = self._base + quote(command, safe="$")
        try:
            response = self._http.get(url)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Synaccess request failed: {exc}") from exc
        if response.status_code == 401:
            raise UpstreamError("Synaccess rejected the username or password")
        if response.status_code >= 400:
            raise UpstreamError(f"Synaccess HTTP {response.status_code}")
        return response.text
