"""Synaccess netBooter HTTP command interface.

NP-1601DU and the other DU models report inlet (bank) current, not per-outlet current.
The status string's right-most bit is outlet 1.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from wakehub.errors import UpstreamError
from wakehub.inventory import host_for_url


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


def synaccess_realm(header: str) -> bool:
    return "synaccess" in header.lower() or "netbooter" in header.lower()


def parse_status(body: str, names: dict[int, str] | None = None) -> PduStatus:
    text = _payload(body)
    if text.startswith("$A0,"):
        text = text[4:]
    elif text.startswith("$A0"):
        text = text[3:].lstrip(",").strip()
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts or any(ch not in "01" for ch in parts[0]):
        raise UpstreamError(f"Synaccess status was not understood: {text!r}")
    bits = parts[0]
    tail = parts[1:]
    temperature: float | None = None
    # Some firmware reports temperature as XX when the probe is absent.
    if tail and not _is_float(tail[-1]):
        if tail[-1].upper() not in {"XX", "X", "N/A", "NA", "--"}:
            raise UpstreamError(f"Synaccess status field {tail[-1]!r} is not a number")
        tail = tail[:-1]
    numbers: list[float] = []
    for part in tail:
        if not _is_float(part):
            raise UpstreamError(f"Synaccess status field {part!r} is not a number")
        numbers.append(float(part))
    # One current plus temperature, or two bank currents plus temperature.
    if len(numbers) >= 3:
        currents = tuple(numbers[:-1])
        temperature = numbers[-1]
    elif len(numbers) == 2 and temperature is None and _looks_like_temperature(numbers):
        currents = (numbers[0],)
        temperature = numbers[1]
    else:
        currents = tuple(numbers)
    labels = names or {}
    outlets = tuple(
        Outlet(number=index, on=bit == "1", name=labels.get(index) or f"Outlet {index}")
        for index, bit in enumerate(reversed(bits), start=1)
    )
    return PduStatus(outlets=outlets, bank_amps=currents, temperature_c=temperature, raw=text)


def _is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _looks_like_temperature(numbers: list[float]) -> bool:
    # A single-bank reply is current, temperature. Two small readings are both currents.
    return numbers[1] > 10 or numbers[0] < 1


def parse_result(body: str) -> None:
    text = _payload(body)
    if "$A0" in text and "$AF" not in text:
        return
    if "$AF" in text:
        raise UpstreamError("Synaccess refused the command")
    raise UpstreamError(f"Synaccess returned an unknown result: {text!r}")


_OUTLET_INPUT = re.compile(r"^(?:outlet[_-]?)?name[_-]?(\d+)$", re.IGNORECASE)


def parse_outlet_names(body: str) -> dict[int, str]:
    text = body.strip()
    if not text:
        return {}
    if text[0] in "[{":
        try:
            return _names_from_json(json.loads(text))
        except json.JSONDecodeError:
            pass
    return _names_from_html(text)


def _names_from_json(data: object) -> dict[int, str]:
    rows = data
    if isinstance(data, dict):
        rows = next((data[key] for key in ("outlets", "data", "items") if isinstance(data.get(key), list)), None)
    if not isinstance(rows, list):
        return {}
    names: dict[int, str] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        index = item.get("outletIndex", item.get("index", item.get("outlet")))
        label = item.get("outletName", item.get("name"))
        if index is None or label is None or not str(label).strip():
            continue
        names[int(index)] = str(label).strip()
    if 0 in names:
        names = {key + 1: value for key, value in names.items()}
    return {key: value for key, value in names.items() if key >= 1}


def _names_from_html(text: str) -> dict[int, str]:
    names: dict[int, str] = {}
    for match in re.finditer(r"<input\b([^>]*)>", text, re.IGNORECASE):
        attrs: dict[str, str] = {}
        for attr in re.finditer(
            r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
            match.group(1),
        ):
            attrs[attr.group(1).lower()] = next(group for group in attr.groups()[1:] if group is not None)
        found = _OUTLET_INPUT.match(attrs.get("name", ""))
        label = attrs.get("value", "").strip()
        if found and label:
            names[int(found.group(1))] = label
    if names:
        return names
    array = re.search(r"outlet[_ \-]*names?\s*=\s*(?:new\s+Array)?\s*\(?\s*\[(.*?)\]", text, re.IGNORECASE | re.DOTALL)
    if not array:
        return {}
    labels = re.findall(r"""["']([^"']*)["']""", array.group(1))
    return {index: label for index, label in enumerate(labels, start=1) if label.strip()}


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
        insecure_tls: bool = False,
        timeout: float = 8,
        http: httpx.Client | None = None,
    ):
        scheme = "https" if use_tls else "http"
        self._base = f"{scheme}://{host_for_url(host)}:{port}/cmd.cgi?"
        self._owns = http is None
        self._http = http or httpx.Client(
            auth=(username, password),
            timeout=timeout,
            verify=not insecure_tls,
        )

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

    def read_outlet_names(self) -> dict[int, str]:
        # $A5 reports on/off bits, not the names typed into Outlet Setup.
        origin = self._base.split("/cmd.cgi", 1)[0]
        for path in ("/api/outlets", "/", "/outletsetup.htm"):
            try:
                response = self._http.get(origin + path, timeout=2.0)
            except httpx.HTTPError:
                continue
            if response.status_code >= 400:
                continue
            names = parse_outlet_names(response.text)
            if names:
                return names
        raise UpstreamError("the PDU did not return outlet names")

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
