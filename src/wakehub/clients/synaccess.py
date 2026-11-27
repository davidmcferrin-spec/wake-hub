"""Synaccess netBooter HTTP command interface.

NP-1601DU and the other DU models report inlet (bank) current, not per-outlet current.
The status string's right-most bit is outlet 1.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote, quote_plus

import httpx

from wakehub.errors import UpstreamError
from wakehub.inventory import host_for_url

log = logging.getLogger("wakehub.synaccess")


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
    bank_ranges: tuple[str, ...] = ()
    temperature_text: str = ""


def synaccess_realm(header: str) -> bool:
    return "synaccess" in header.lower() or "netbooter" in header.lower()


def synaccess_http(headers: dict[str, str] | None, body: str, status_code: int = 200) -> bool:
    """True when a port-80 reply looks like a netBooter, including a 401 challenge."""
    safe = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    title = ""
    match = _TITLE.search(body or "")
    if match:
        title = match.group(1)
    blob = " ".join(
        (
            safe.get("server", ""),
            safe.get("www-authenticate", ""),
            title,
            body or "",
        )
    ).lower()
    if "synaccess" in blob or "netbooter" in blob:
        return True
    return status_code == 401 and synaccess_realm(safe.get("www-authenticate", ""))


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


def parse_status_xml(body: str, names: dict[int, str] | None = None, outlet_count: int | None = None) -> PduStatus:
    # rly0 is outlet 1. rly16 is an extra relay on the NP-1601DU, not a 17th outlet.
    relays: dict[int, bool] = {}
    for match in re.finditer(r"<rly(\d+)>([^<]*)</rly\1>", body or "", re.IGNORECASE):
        index = int(match.group(1))
        if index >= 16:
            continue
        value = match.group(2).strip()
        if value not in {"0", "1"}:
            continue
        relays[index] = value == "1"
    if not relays:
        raise UpstreamError("status.xml did not include outlet relays")
    limit = outlet_count if outlet_count else max(relays) + 1
    labels = names or {}
    outlets = tuple(
        Outlet(number=index + 1, on=relays[index], name=labels.get(index + 1) or f"Outlet {index + 1}")
        for index in range(min(limit, 16))
        if index in relays
    )
    ranges: list[str] = []
    amps: list[float] = []
    for tag in ("ac0", "ac1"):
        text = _xml_text(body, tag)
        if not text:
            continue
        ranges.append(text)
        first = text.split("-", 1)[0].strip()
        if _is_float(first):
            amps.append(float(first))
    temperature_text, temperature = _temperature_text(_xml_text(body, "tp0"))
    return PduStatus(
        outlets=outlets,
        bank_amps=tuple(amps),
        temperature_c=temperature,
        raw=body or "",
        bank_ranges=tuple(ranges),
        temperature_text=temperature_text,
    )


def _xml_text(body: str, tag: str) -> str:
    match = re.search(rf"<{tag}>([^<]*)</{tag}>", body or "", re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _temperature_text(raw: str) -> tuple[str, float | None]:
    if not raw or raw.upper() in {"X", "XX"}:
        return "", None
    celsius, _sep, fahrenheit = raw.partition("/")
    celsius = celsius.strip()
    if not _is_float(celsius):
        return raw, None
    text = f"{celsius}°C"
    if fahrenheit.strip() and _is_float(fahrenheit.strip()):
        text = f"{text} / {fahrenheit.strip()}°F"
    return text, float(celsius)


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


# $A5 is on/off bits and bank current. Names, when the firmware has them, are on a web page.
_OUTLET_INPUT = re.compile(
    r"^(?:outlet[_-]?name|outletname|out[_-]?name|o[_-]?name|nm|name|custom)[_-]?(\d+)$",
    re.IGNORECASE,
)
_JUNK_NAME = {"0", "1", "on", "off", "true", "false"}
_TITLE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_NAME_ASSIGN = re.compile(
    r"(?:outlet[_ \-]*names?|ol[_ \-]*names?|name[_ \-]*array)\s*=\s*",
    re.IGNORECASE,
)
_PASSWORD_INPUT = re.compile(r"<input\b[^>]*type\s*=\s*[\"']?password", re.IGNORECASE)
_LOGIN_WORD = re.compile(r"\blogin\b|\bsign in\b", re.IGNORECASE)
LOGIN_MESSAGE = "The PDU web UI requires a session login; outlet names could not be read"
AUTH_MESSAGE = "The PDU rejected the username or password"
_LOGGED_NAME_READS: dict[str, str] = {}
_LOGGED_A5: set[str] = set()


def firmware_default_name(label: str, number: int) -> bool:
    # The NP-1601DU fills an unnamed outlet with Outlet4, Outlet10, and so on.
    compact = re.sub(r"\s+", "", label or "").lower()
    return compact == f"outlet{number}"


def _usable_name(label: str, number: int) -> str:
    text = html.unescape(label or "").strip()
    if not text or text.lower() in _JUNK_NAME or firmware_default_name(text, number):
        return ""
    return text


def parse_outlet_names(body: str) -> dict[int, str]:
    names, _span = collect_outlet_names(body)
    return names


def collect_outlet_names(body: str) -> tuple[dict[int, str], int]:
    # The whole page is parsed. The 8 KB cut is only for the diagnostics copy.
    text = (body or "").strip()
    if not text:
        return {}, 0
    if text[0] in "[{":
        try:
            names = _names_from_json(json.loads(text))
        except json.JSONDecodeError:
            names = {}
        else:
            return names, max(names) if names else 0
    names, span = _names_from_inputs(text)
    if names or span:
        return names, span
    names, span = _names_from_table(text)
    if names or span:
        return names, span
    names = _names_from_array(text)
    return names, max(names) if names else 0


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
        names[int(index)] = html.unescape(str(label)).strip()
    if 0 in names:
        names = {key + 1: value for key, value in names.items()}
    return {key: value for key, value in names.items() if key >= 1}


def looks_like_login(body: str) -> bool:
    text = body or ""
    if _PASSWORD_INPUT.search(text):
        return True
    sample = re.sub(r"<[^>]+>", " ", text[:4000])
    return bool(_LOGIN_WORD.search(sample))


def _blank_password_values(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if not re.search(r"type\s*=\s*[\"']?password", tag, re.IGNORECASE):
            return tag
        return re.sub(
            r"""(value\s*=\s*)(?:"[^"]*"|'[^']*'|[^\s>]+)""",
            r'\1"[redacted]"',
            tag,
            count=1,
            flags=re.IGNORECASE,
        )

    return re.sub(r"<input\b[^>]*>", repl, text, flags=re.IGNORECASE)


def redact_diagnostics(text: str, secret: str = "", username: str = "") -> str:
    cleaned = _blank_password_values(text or "")
    cleaned = re.sub(r"(?i)(cookie:[^\r\n]*)", "Cookie: [redacted]", cleaned)
    cleaned = re.sub(r"(?i)(set-cookie:[^\r\n]*)", "Set-Cookie: [redacted]", cleaned)
    cleaned = re.sub(r"(?i)(authorization:\s*basic\s+)\S+", r"\1[redacted]", cleaned)
    if secret:
        forms = [html.escape(secret, quote=True), quote(secret, safe=""), quote_plus(secret), secret]
        if username:
            token = base64.b64encode(f"{username}:{secret}".encode()).decode()
            forms.insert(0, token)
        for form in forms:
            if form:
                cleaned = cleaned.replace(form, "[redacted]")
    return cleaned[:8192]


def _names_from_inputs(text: str) -> tuple[dict[int, str], int]:
    names: dict[int, str] = {}
    span = 0
    for match in re.finditer(r"<input\b([^>]*)>", text, re.IGNORECASE):
        attrs: dict[str, str] = {}
        for attr in re.finditer(
            r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
            match.group(1),
        ):
            attrs[attr.group(1).lower()] = next(group for group in attr.groups()[1:] if group is not None)
        kind = attrs.get("type", "text").lower()
        if kind not in {"text", ""}:
            continue
        raw_name = attrs.get("name", "")
        # pwr.htm names outlets ON0..ON15. ON0 is outlet 1.
        on = re.fullmatch(r"ON(\d+)", raw_name, re.IGNORECASE)
        if on:
            number = int(on.group(1)) + 1
        else:
            found = _OUTLET_INPUT.match(raw_name)
            if not found:
                continue
            number = int(found.group(1))
        span = max(span, number)
        label = _usable_name(attrs.get("value", ""), number)
        if label:
            names[number] = label
    return names, span


def _cell_text(cell: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", cell)
    return html.unescape(re.sub(r"\s+", " ", plain)).strip()


def _table_with_name(text: str) -> str:
    for table in re.findall(r"<table\b[^>]*>(.*?)</table>", text, re.IGNORECASE | re.DOTALL):
        if re.search(r">\s*Name\s*<", table, re.IGNORECASE):
            return table
    return ""


def _names_from_table(text: str) -> tuple[dict[int, str], int]:
    # Stay inside the table that has the Name header. A following table is a different list.
    table = _table_with_name(text)
    if not table:
        return {}, 0
    rows = []
    for chunk in re.split(r"</tr\s*>", table, flags=re.IGNORECASE):
        # Some firmware omits the opening <tr> on later rows.
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", chunk, re.IGNORECASE | re.DOTALL)
        if cells:
            rows.append([_cell_text(cell) for cell in cells])
    header = None
    name_col = None
    outlet_col = None
    for index, cells in enumerate(rows):
        lowered = [cell.lower() for cell in cells]
        if "name" not in lowered:
            continue
        header = index
        name_col = lowered.index("name")
        for label in ("outlet", "no.", "no", "#", "id", "index", "port"):
            if label in lowered:
                outlet_col = lowered.index(label)
                break
        break
    if header is None or name_col is None:
        return {}, 0
    names: dict[int, str] = {}
    span = 0
    for cells in rows[header + 1 :]:
        if name_col >= len(cells):
            continue
        number = _outlet_number(cells, outlet_col)
        if not number:
            continue
        span = max(span, number)
        label = _usable_name(cells[name_col], number)
        if label and number not in names:
            names[number] = label
    return names, span


def _outlet_number(cells: list[str], outlet_col: int | None) -> int:
    if outlet_col is not None and outlet_col < len(cells):
        match = re.match(r"(\d+)", cells[outlet_col].strip())
        if match:
            return int(match.group(1))
    for cell in cells:
        match = re.fullmatch(r"(\d+)", cell.strip())
        if match:
            return int(match.group(1))
    return 0


def _quoted_strings(body: str) -> list[str]:
    # A quote, apostrophe, ) or ] inside a quoted name is part of the name.
    labels: list[str] = []
    index = 0
    size = len(body)
    while index < size:
        quote = body[index]
        if quote not in "\"'":
            index += 1
            continue
        index += 1
        chars: list[str] = []
        while index < size:
            char = body[index]
            if char == "\\" and index + 1 < size:
                chars.append(body[index + 1])
                index += 2
                continue
            if char == quote:
                index += 1
                break
            chars.append(char)
            index += 1
        labels.append("".join(chars))
    return labels


def _assigned_list(text: str) -> str:
    found = _NAME_ASSIGN.search(text)
    if not found:
        return ""
    rest = text[found.end() :].lstrip()
    if rest[:9].lower() == "new array":
        rest = rest[9:].lstrip()
    if not rest or rest[0] not in "[(":
        return ""
    opener = rest[0]
    closer = "]" if opener == "[" else ")"
    depth = 0
    quote = ""
    index = 0
    while index < len(rest):
        char = rest[index]
        if quote:
            if char == "\\" and index + 1 < len(rest):
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "\"'":
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return rest[1:index]
        index += 1
    return ""


def _names_from_array(text: str) -> dict[int, str]:
    body = _assigned_list(text)
    if not body:
        return {}
    labels = _quoted_strings(body)
    return {
        index: html.unescape(label).strip()
        for index, label in enumerate(labels, start=1)
        if label.strip()
    }


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
        self._username = username or ""
        self._secret = password or ""
        self._timeout = timeout
        self.outlet_count = 0
        self.name_pages: list[dict[str, object]] = []
        self.status_pages: list[dict[str, object]] = []
        self._http = http or httpx.Client(
            auth=(username, password),
            timeout=timeout,
            verify=not insecure_tls,
        )

    def close(self) -> None:
        if self._owns:
            self._http.close()

    def status(self, names: dict[int, str] | None = None) -> PduStatus:
        # status.xml is the page this firmware's own UI polls. $A5 is only the fallback.
        self.status_pages = []
        origin = self._base.split("/cmd.cgi", 1)[0]
        try:
            response = self._http.get(origin + "/status.xml", timeout=min(2.0, self._timeout))
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Synaccess status.xml request failed: {exc}") from exc
        self.status_pages.append(
            {
                "path": "/status.xml",
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "body": redact_diagnostics(response.text or "", self._secret, self._username),
            }
        )
        if response.status_code < 400:
            try:
                return parse_status_xml(response.text or "", names, getattr(self, "_relay_limit", None))
            except UpstreamError:
                pass
        elif response.status_code != 404:
            raise UpstreamError(f"Synaccess status.xml HTTP {response.status_code}")
        try:
            raw = self._command("$A5")
        except UpstreamError as exc:
            self._log_a5_once(str(exc))
            raise
        self.status_pages.append(
            {
                "path": "/cmd.cgi?$A5",
                "status": 200,
                "content_type": "text/plain",
                "body": redact_diagnostics(raw, self._secret, self._username),
            }
        )
        try:
            return parse_status(raw, names)
        except UpstreamError:
            self._log_a5_once(raw)
            raise

    def _log_a5_once(self, raw: str) -> None:
        origin = self._base.split("/cmd.cgi", 1)[0]
        if origin in _LOGGED_A5:
            return
        _LOGGED_A5.add(origin)
        log.info("PDU $A5 status was not understood: %s", (raw or "")[:500])

    def set_outlet(self, outlet: int, on: bool) -> None:
        parse_result(self._command(f"$A3 {int(outlet)} {1 if on else 0}"))

    def reboot_outlet(self, outlet: int) -> None:
        parse_result(self._command(f"$A4 {int(outlet)}"))

    def set_all(self, on: bool) -> None:
        parse_result(self._command(f"$A7 {1 if on else 0}"))

    def read_outlet_names(self) -> dict[int, str]:
        # Names are not in $A5. Try the web pages and keep the first one that has them.
        origin = self._base.split("/cmd.cgi", 1)[0]
        paths = ("/pwr.htm", "/", "/index.htm")
        self.name_pages = []
        first_useful: dict[str, object] | None = None
        first_page: dict[str, object] | None = None
        for path in paths:
            try:
                response = self._http.get(origin + path, timeout=min(2.0, self._timeout))
            except httpx.HTTPError as exc:
                page = {
                    "path": path,
                    "status": 0,
                    "content_type": "",
                    "body": redact_diagnostics(str(exc), self._secret, self._username),
                }
                self.name_pages.append(page)
                if first_page is None:
                    first_page = page
                continue
            body = response.text or ""
            content_type = response.headers.get("content-type", "")
            page = {
                "path": path,
                "status": response.status_code,
                "content_type": content_type,
                "body": redact_diagnostics(body, self._secret, self._username),
            }
            self.name_pages.append(page)
            if first_page is None:
                first_page = page
            if response.status_code != 404 and first_useful is None:
                first_useful = page
            names, span = collect_outlet_names(body) if response.status_code < 400 else ({}, 0)
            if span:
                self.outlet_count = max(self.outlet_count, span)
            if names:
                return names
        chosen = first_useful or first_page
        self._log_name_miss(origin, chosen)
        if chosen and int(chosen["status"]) == 401:
            raise UpstreamError(AUTH_MESSAGE)
        if chosen and looks_like_login(str(chosen["body"])):
            raise UpstreamError(LOGIN_MESSAGE)
        if chosen is None:
            raise UpstreamError("Couldn't read outlet names from the PDU (no page answered)")
        snippet = str(chosen["body"])[:120]
        reason = f"{chosen['path']} HTTP {chosen['status']}"
        if snippet:
            reason = f"{reason}: {snippet}"
        raise UpstreamError(f"Couldn't read outlet names from the PDU ({reason})")

    def _log_name_miss(self, origin: str, page: dict[str, object] | None) -> None:
        if page is None:
            signature = "no response"
            line = "PDU outlet names: no page answered"
        else:
            body = str(page["body"])[:500]
            signature = f"{page['path']} {page['status']} {body}"
            line = f"PDU outlet names {page['path']} HTTP {page['status']} {body}"
        if _LOGGED_NAME_READS.get(origin) == signature:
            return
        _LOGGED_NAME_READS[origin] = signature
        log.info("%s", line)

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
