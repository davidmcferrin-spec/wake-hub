"""Suggest what a discovered host is, from its vendor and non-destructive probes."""

from __future__ import annotations


def _has(vendor: str, needles: tuple[str, ...]) -> bool:
    text = vendor.lower()
    return any(needle in text for needle in needles)


def suggest(
    *,
    vendor: str,
    mac: str,
    ports: set[int],
    http_kinds: list[str],
    mdns: list[str],
) -> dict:
    """Pick one likely type. High means a signature matched; low means only a MAC."""
    names = [item.lower() for item in mdns]
    http = set(http_kinds)
    ranked: list[tuple[int, str, str, str, list[str]]] = []

    def add(rank: int, kind: str, confidence: str, reason: str, capabilities: list[str]) -> None:
        ranked.append((rank, kind, confidence, reason, capabilities))

    if "jetkvm" in http or any("jetkvm" in name for name in names):
        add(100, "jetkvm", "high", "JetKVM status page or mDNS", ["jetkvm"])
    if "synaccess" in http:
        add(100, "synaccess", "high", "Synaccess netBooter response", ["pdu"])
    if "shelly" in http or any("shelly" in name for name in names):
        add(100, "shelly", "high", "Shelly Gen2 endpoint or _shelly._tcp", ["plug"])
    elif _has(vendor, ("shelly", "espressif")) and (80 in ports or 443 in ports):
        add(60, "shelly", "medium", "Shelly or Espressif vendor on HTTP", ["plug"])
    if "ups" in http or (_has(vendor, ("cyberpower", "cyber power")) and 161 in ports):
        add(100, "ups", "high", "CyberPower card or RCCARD SNMP", ["ups"])
    elif _has(vendor, ("cyberpower", "cyber power")):
        add(40, "ups", "low", "CyberPower vendor, SNMP not confirmed", ["ups"])
    intel = _has(vendor, ("intel",))
    if (16992 in ports or 16993 in ports) and intel:
        add(90, "amt", "high", "Intel NIC with AMT port 16992 or 16993", ["amt", "wol"])
    elif 16992 in ports or 16993 in ports:
        add(70, "amt", "medium", "AMT port is open", ["amt"])
    tplink = _has(vendor, ("tp-link", "tplink"))
    if 9999 in ports and tplink:
        add(90, "kasa", "high", "TP-Link vendor with the Kasa port", ["plug"])
    elif 9999 in ports:
        add(70, "kasa", "medium", "Port 9999 is open", ["plug"])
    if not ranked and mac:
        add(10, "pc", "low", "MAC address, no device signature", ["wol"])
    if not ranked:
        add(0, "unknown", "low", "No signature", [])
    _rank, kind, confidence, reason, capabilities = sorted(ranked, key=lambda item: item[0], reverse=True)[0]
    if mac and "wol" not in capabilities and kind in {"pc", "amt"}:
        capabilities = [*capabilities, "wol"]
    prefill = {"kind": _prefill_kind(kind), "name": ""}
    if kind == "shelly":
        prefill["plug_kind"] = "shelly"
    if kind == "kasa":
        prefill["plug_kind"] = "kasa"
    if kind == "amt":
        prefill["username"] = "admin"
    return {
        "type": kind,
        "confidence": confidence,
        "reason": reason,
        "capabilities": capabilities,
        "prefill": prefill,
    }


def _prefill_kind(kind: str) -> str:
    return {
        "pc": "device",
        "amt": "amt",
        "jetkvm": "jetkvm",
        "synaccess": "pdu",
        "shelly": "plug",
        "kasa": "plug",
        "ups": "ups",
    }.get(kind, "device")
