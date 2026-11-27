"""CyberPower RCCARD SNMP client.

OIDs come from the published CPS-MIB. Voltage and current are tenths.
Battery runtime is TimeTicks (hundredths of a second). The card was not
attached during tests, so the scaling follows the MIB text.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from wakehub.errors import UpstreamError, WakeHubError

ENTERPRISE = "1.3.6.1.4.1.3808"
UPS = ENTERPRISE + ".1.1.1"
OIDS = {
    "model": UPS + ".1.1.1.0",
    "battery_status": UPS + ".2.1.1.0",
    "capacity_pct": UPS + ".2.2.1.0",
    "runtime_ticks": UPS + ".2.2.4.0",
    "input_voltage_raw": UPS + ".3.2.1.0",
    "output_status": UPS + ".4.1.1.0",
    "output_voltage_raw": UPS + ".4.2.1.0",
    "load_pct": UPS + ".4.2.3.0",
    "current_raw": UPS + ".4.2.4.0",
    "power_w": UPS + ".4.2.5.0",
    "shutoff_delay": UPS + ".5.2.10.0",
    "ups_off": UPS + ".6.2.1.0",
    "reboot": UPS + ".6.2.2.0",
    "sleep": UPS + ".6.2.3.0",
    "turn_on": UPS + ".6.2.6.0",
    "battery_test": UPS + ".7.2.2.0",
}
STATUS_OIDS = (
    "model",
    "battery_status",
    "capacity_pct",
    "runtime_ticks",
    "input_voltage_raw",
    "output_status",
    "output_voltage_raw",
    "load_pct",
    "current_raw",
    "power_w",
)
OUTLET_PREFIX = UPS + ".8.1.1.1.2."

OUTPUT_STATUS = {
    1: "unknown",
    2: "on_line",
    3: "on_battery",
    4: "on_boost",
    5: "on_sleep",
    6: "off",
    7: "rebooting",
    8: "on_eco",
    9: "on_bypass",
    10: "on_buck",
    11: "on_overload",
}
BATTERY_STATUS = {1: "unknown", 2: "normal", 3: "low", 4: "not_present"}

# Commands that drop or cycle the load. The caller must already have confirmed.
DESTRUCTIVE = {"shutdown", "reboot", "turn_off", "sleep", "battery_test", "outlet_off", "outlet_cycle"}


def outlet_oid(index: int) -> str:
    if index < 1 or index > 24:
        raise WakeHubError("UPS outlet bank must be between 1 and 24")
    return OUTLET_PREFIX + str(index)


def _unpack(value: object) -> tuple[object, str | None]:
    if isinstance(value, dict) and "value" in value:
        return value.get("value"), value.get("asn_type")
    return value, None


def status_from_varbinds(values: dict[str, object]) -> dict:
    """Turn a fixture or a live GET into the fields the UI and metrics use."""

    def raw(name: str):
        value, _asn = _unpack(values.get(OIDS[name]))
        if value is None or value == "":
            return None
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="replace").strip()
        return value

    def number(name: str):
        value = raw(name)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    output_code = number("output_status")
    battery_code = number("battery_status")
    runtime_value, runtime_asn = _unpack(values.get(OIDS["runtime_ticks"]))
    runtime = None
    if runtime_value not in (None, ""):
        try:
            runtime = float(runtime_value)
        except (TypeError, ValueError):
            runtime = None
    return {
        "model": raw("model") or "",
        "output_status": OUTPUT_STATUS.get(int(output_code), "unknown") if output_code is not None else "unknown",
        "on_battery": output_code == 3,
        "battery": BATTERY_STATUS.get(int(battery_code), "unknown") if battery_code is not None else "unknown",
        "capacity_pct": number("capacity_pct"),
        "runtime_s": None if runtime is None else runtime / 100,
        "runtime_raw": None if runtime is None else {"value": runtime_value, "asn_type": runtime_asn},
        "input_voltage_v": _tenths(number("input_voltage_raw")),
        "output_voltage_v": _tenths(number("output_voltage_raw")),
        "load_pct": number("load_pct"),
        "current_a": _tenths(number("current_raw")),
        "power_w": number("power_w"),
    }


def command_set(action: str, *, delay_seconds: int | None = None, outlet: int | None = None) -> list[tuple[str, int, str]]:
    """The SNMP SETs for one UPS action, in order. The third item is the ASN type."""
    sets: list[tuple[str, int, str]] = []
    if action in {"shutdown", "turn_off"} and delay_seconds:
        delay = max(60, min(int(delay_seconds), 5940))
        # The MIB types this delay as TimeTicks, which are hundredths of a second.
        sets.append((OIDS["shutoff_delay"], delay * 100, "TimeTicks"))
        sets.append((OIDS["ups_off"], 3, "Integer"))
        return sets
    if action in {"shutdown", "turn_off"}:
        sets.append((OIDS["ups_off"], 2, "Integer"))
        return sets
    if action == "reboot":
        sets.append((OIDS["reboot"], 2, "Integer"))
        return sets
    if action == "sleep":
        sets.append((OIDS["sleep"], 3 if delay_seconds else 2, "Integer"))
        return sets
    if action == "turn_on":
        sets.append((OIDS["turn_on"], 2, "Integer"))
        return sets
    if action == "battery_test":
        sets.append((OIDS["battery_test"], 2, "Integer"))
        return sets
    if action == "outlet_on":
        sets.append((outlet_oid(outlet or 0), 1, "Integer"))
        return sets
    if action == "outlet_off":
        sets.append((outlet_oid(outlet or 0), 2, "Integer"))
        return sets
    if action == "outlet_cycle":
        sets.append((outlet_oid(outlet or 0), 2, "Integer"))
        sets.append((outlet_oid(outlet or 0), 1, "Integer"))
        return sets
    raise WakeHubError(
        "UPS action must be shutdown, reboot, turn_off, turn_on, sleep, battery_test, outlet_on, outlet_off, or outlet_cycle"
    )


def _tenths(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 10


@dataclass
class MemorySnmp:
    """Test double that records SETs and serves a varbind fixture."""

    values: dict[str, object]
    sets: list[tuple[str, int]]

    def get(self, oids: list[str]) -> dict[str, object]:
        return {oid: self.values[oid] for oid in oids if oid in self.values}

    def set(self, oid: str, value: int, asn_type: str = "Integer") -> None:
        self.sets.append((oid, value, asn_type))
        self.values[oid] = {"value": value, "asn_type": asn_type}


class PysnmpTransport:
    def __init__(self, host: str, port: int, version: str, community: str, v3_user: str, auth_proto: str, auth_key: str, priv_proto: str, priv_key: str, timeout: float = 3):
        self.host = host
        self.port = port
        self.version = version
        self.community = community
        self.v3_user = v3_user
        self.auth_proto = auth_proto
        self.auth_key = auth_key
        self.priv_proto = priv_proto
        self.priv_key = priv_key
        self.timeout = timeout

    def get(self, oids: list[str]) -> dict[str, object]:
        return asyncio.run(self._get(oids))

    def set(self, oid: str, value: int, asn_type: str = "Integer") -> None:
        asyncio.run(self._set(oid, value, asn_type))

    async def _get(self, oids: list[str]) -> dict[str, object]:
        engine, auth, target, context, ObjectType, ObjectIdentity, get_cmd = await self._session()
        error, status, index, varbinds = await get_cmd(
            engine,
            auth,
            target,
            context,
            *[ObjectType(ObjectIdentity(oid)) for oid in oids],
            lookupMib=False,
        )
        self._check(error, status, index)
        return {_oid_text(item[0]): _value(item[1]) for item in varbinds}

    async def _set(self, oid: str, value: int, asn_type: str) -> None:
        from pysnmp.proto.rfc1902 import Integer32, TimeTicks

        engine, auth, target, context, ObjectType, ObjectIdentity, _get = await self._session()
        from pysnmp.hlapi.v3arch.asyncio import set_cmd

        encoded = TimeTicks(value) if asn_type == "TimeTicks" else Integer32(value)
        error, status, index, _binds = await set_cmd(
            engine,
            auth,
            target,
            context,
            ObjectType(ObjectIdentity(oid), encoded),
            lookupMib=False,
        )
        self._check(error, status, index)

    async def _session(self):
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            UsmUserData,
            get_cmd,
            usmHMACMD5AuthProtocol,
            usmHMACSHAAuthProtocol,
            usmAesCfb128Protocol,
            usmDESPrivProtocol,
        )

        if self.version in {"1", "v1"}:
            auth = CommunityData(self.community, mpModel=0)
        elif self.version in {"2", "2c", "v2c"}:
            auth = CommunityData(self.community, mpModel=1)
        elif self.version in {"3", "v3"}:
            auth_map = {"md5": usmHMACMD5AuthProtocol, "sha": usmHMACSHAAuthProtocol, "": None, "none": None}
            priv_map = {"des": usmDESPrivProtocol, "aes": usmAesCfb128Protocol, "": None, "none": None}
            auth_protocol = auth_map.get(self.auth_proto.lower())
            priv_protocol = priv_map.get(self.priv_proto.lower())
            if auth_protocol is None and self.auth_proto.lower() not in {"", "none"}:
                raise WakeHubError("UPS SNMPv3 auth protocol must be md5, sha, or none")
            if priv_protocol is None and self.priv_proto.lower() not in {"", "none"}:
                raise WakeHubError("UPS SNMPv3 privacy protocol must be des, aes, or none")
            kwargs = {}
            if auth_protocol is not None:
                kwargs["authProtocol"] = auth_protocol
                kwargs["authKey"] = self.auth_key
            if priv_protocol is not None:
                kwargs["privProtocol"] = priv_protocol
                kwargs["privKey"] = self.priv_key
            auth = UsmUserData(self.v3_user, **kwargs)
        else:
            raise WakeHubError("SNMP version must be 1, 2c, or 3")
        target = await UdpTransportTarget.create((self.host, self.port), timeout=self.timeout, retries=0)
        return SnmpEngine(), auth, target, ContextData(), ObjectType, ObjectIdentity, get_cmd

    def _check(self, error, status, index) -> None:
        if error:
            raise UpstreamError(f"SNMP error: {error}")
        if status:
            raise UpstreamError(f"SNMP status {status} at index {index}")


def _oid_text(identity) -> str:
    text = str(identity)
    if text.startswith("."):
        return text[1:]
    return text


def _value(item):
    asn_type = type(item).__name__
    if hasattr(item, "prettyPrint"):
        text = item.prettyPrint()
        if text.lstrip("-").isdigit():
            return {"value": int(text), "asn_type": asn_type}
        return {"value": text, "asn_type": asn_type}
    return {"value": item, "asn_type": asn_type}


class UpsClient:
    def __init__(self, transport, *, cycle_pause: float = 2):
        self.transport = transport
        self.cycle_pause = cycle_pause

    def status(self) -> dict:
        try:
            values = self.transport.get([OIDS[name] for name in STATUS_OIDS])
        except OSError as exc:
            raise UpstreamError(f"UPS SNMP request failed: {exc}") from exc
        return status_from_varbinds(values)

    def act(self, action: str, *, delay_seconds: int | None = None, outlet: int | None = None) -> dict:
        import time

        applied = []
        steps = command_set(action, delay_seconds=delay_seconds, outlet=outlet)
        for index, (oid, value, asn_type) in enumerate(steps):
            if action == "outlet_cycle" and index > 0 and self.cycle_pause:
                time.sleep(self.cycle_pause)
            try:
                self.transport.set(oid, value, asn_type)
            except OSError as exc:
                raise UpstreamError(f"UPS SNMP set failed: {exc}") from exc
            applied.append({"oid": oid, "value": value, "asn_type": asn_type})
        return {"action": action, "sets": applied}
