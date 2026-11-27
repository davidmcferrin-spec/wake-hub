"""Intel AMT power control over WS-Management.

Speaks CIM_PowerManagementService.RequestPowerStateChange with HTTP digest.
Self-signed certificates are allowed when the endpoint says so.
"""

from __future__ import annotations

import ssl
import uuid
import xml.etree.ElementTree as ET
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener

from wakehub.errors import UpstreamError, WakeHubError

POWER_COMMANDS = {
    "on": 2,
    "cycle": 5,
    "off": 8,
    "reboot": 10,
    "shutdown": 12,
}

POWER_NAMES = {
    2: "on",
    3: "sleep_light",
    4: "sleep_deep",
    5: "power_cycle",
    6: "off_hard",
    7: "hibernate",
    8: "off",
    9: "power_cycle_hard",
    10: "reset",
    11: "nmi",
    12: "shutdown",
    14: "reset_graceful",
}

_NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
_NS_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
_NS_WSMAN = "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
_NS_ENUM = "http://schemas.xmlsoap.org/ws/2004/09/enumeration"
_CIM_POWER = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_PowerManagementService"
_CIM_ASSOC = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_AssociatedPowerManagementService"
_CIM_SYSTEM = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ComputerSystem"


def build_enumerate_power(uri: str, message_id: str | None = None) -> str:
    message_id = message_id or f"uuid:{uuid.uuid4()}"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="{_NS_SOAP}" xmlns:wsa="{_NS_WSA}" xmlns:wsman="{_NS_WSMAN}" xmlns:wsen="{_NS_ENUM}">
  <s:Header>
    <wsa:Action s:mustUnderstand="true">{_NS_ENUM}/Enumerate</wsa:Action>
    <wsa:To s:mustUnderstand="true">{_xml(uri)}</wsa:To>
    <wsman:ResourceURI s:mustUnderstand="true">{_CIM_ASSOC}</wsman:ResourceURI>
    <wsa:MessageID s:mustUnderstand="true">{message_id}</wsa:MessageID>
    <wsa:ReplyTo><wsa:Address>{_NS_WSA}/role/anonymous</wsa:Address></wsa:ReplyTo>
    <wsman:OperationTimeout>PT30S</wsman:OperationTimeout>
  </s:Header>
  <s:Body>
    <wsen:Enumerate>
      <wsman:OptimizeEnumeration/>
      <wsman:MaxElements>4</wsman:MaxElements>
    </wsen:Enumerate>
  </s:Body>
</s:Envelope>
"""


def build_power_change(uri: str, power_state: int, message_id: str | None = None) -> str:
    if power_state not in POWER_NAMES:
        raise WakeHubError(f"AMT power state {power_state} is not a known CIM value")
    message_id = message_id or f"uuid:{uuid.uuid4()}"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="{_NS_SOAP}" xmlns:wsa="{_NS_WSA}" xmlns:wsman="{_NS_WSMAN}" xmlns:n1="{_CIM_POWER}">
  <s:Header>
    <wsa:Action s:mustUnderstand="true">{_CIM_POWER}/RequestPowerStateChange</wsa:Action>
    <wsa:To s:mustUnderstand="true">{_xml(uri)}</wsa:To>
    <wsman:ResourceURI s:mustUnderstand="true">{_CIM_POWER}</wsman:ResourceURI>
    <wsa:MessageID s:mustUnderstand="true">{message_id}</wsa:MessageID>
    <wsa:ReplyTo><wsa:Address>{_NS_WSA}/role/anonymous</wsa:Address></wsa:ReplyTo>
    <wsman:SelectorSet>
      <wsman:Selector Name="Name">Intel(r) AMT Power Management Service</wsman:Selector>
    </wsman:SelectorSet>
  </s:Header>
  <s:Body>
    <n1:RequestPowerStateChange_INPUT>
      <n1:PowerState>{power_state}</n1:PowerState>
      <n1:ManagedElement>
        <wsa:Address>{_NS_WSA}/role/anonymous</wsa:Address>
        <wsa:ReferenceParameters>
          <wsman:ResourceURI>{_CIM_SYSTEM}</wsman:ResourceURI>
          <wsman:SelectorSet>
            <wsman:Selector Name="Name">ManagedSystem</wsman:Selector>
          </wsman:SelectorSet>
        </wsa:ReferenceParameters>
      </n1:ManagedElement>
    </n1:RequestPowerStateChange_INPUT>
  </s:Body>
</s:Envelope>
"""


def parse_power_state(body: str) -> dict:
    root = _root(body)
    state = _first_int(root, "PowerState")
    available = [int(node.text) for node in _named(root, "AvailableRequestedPowerStates") if node.text and node.text.strip().isdigit()]
    if state is None:
        raise UpstreamError("AMT response did not include PowerState")
    return {
        "power_state": state,
        "power_name": POWER_NAMES.get(state, f"state_{state}"),
        "available": available,
    }


def parse_method_return(body: str) -> int:
    root = _root(body)
    value = _first_int(root, "ReturnValue")
    if value is None:
        fault = _first_text(root, "Text") or _first_text(root, "Reason")
        raise UpstreamError(fault or "AMT did not return a method result")
    if value != 0:
        raise UpstreamError(f"AMT RequestPowerStateChange returned {value}")
    return value


def _root(body: str) -> ET.Element:
    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise UpstreamError("AMT response was not XML") from exc


def _named(root: ET.Element, local: str) -> list[ET.Element]:
    return [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == local]


def _first_int(root: ET.Element, local: str) -> int | None:
    for node in _named(root, local):
        if node.text and node.text.strip().lstrip("-").isdigit():
            return int(node.text.strip())
    return None


def _first_text(root: ET.Element, local: str) -> str | None:
    for node in _named(root, local):
        if node.text and node.text.strip():
            return node.text.strip()
    return None


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class AmtClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 16992,
        use_tls: bool = False,
        insecure_tls: bool = True,
        timeout: float = 15,
        poster=None,
    ):
        scheme = "https" if use_tls else "http"
        self.uri = f"{scheme}://{host}:{port}/wsman"
        self._timeout = timeout
        self._poster = poster
        if poster is None:
            password_mgr = HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(None, self.uri, username, password)
            handlers = [HTTPDigestAuthHandler(password_mgr)]
            if use_tls and insecure_tls:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                import urllib.request

                handlers.append(urllib.request.HTTPSHandler(context=context))
            self._opener = build_opener(*handlers)

    def power_state(self) -> dict:
        body = self._post(build_enumerate_power(self.uri))
        return parse_power_state(body)

    def request_power(self, action: str) -> dict:
        if action not in POWER_COMMANDS:
            raise WakeHubError("AMT action must be on, off, cycle, reboot, or shutdown")
        code = POWER_COMMANDS[action]
        if action == "shutdown":
            current = self.power_state()
            if current["available"] and 12 not in current["available"]:
                code = POWER_COMMANDS["off"]
                action = "off"
        self._post(build_power_change(self.uri, code))
        parsed = parse_method_return(self._last_body)
        return {"action": action, "power_state": code, "return_value": parsed}

    def _post(self, payload: str) -> str:
        if self._poster is not None:
            status, body = self._poster(self.uri, payload)
        else:
            request = Request(
                self.uri,
                data=payload.encode("utf-8"),
                headers={"Content-Type": "application/soap+xml;charset=UTF-8"},
                method="POST",
            )
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    status = response.status
                    body = response.read().decode("utf-8", errors="replace")
            except OSError as exc:
                raise UpstreamError(f"AMT request failed: {exc}") from exc
        self._last_body = body
        if status == 401:
            raise UpstreamError("AMT rejected the digest credentials")
        if status >= 400:
            raise UpstreamError(f"AMT HTTP {status}")
        return body
