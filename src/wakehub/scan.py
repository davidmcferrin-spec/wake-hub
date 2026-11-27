"""Subnet discovery. ARP and directed broadcast need host networking on Unraid."""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx

from wakehub.clients.synaccess import parse_status, synaccess_realm
from wakehub.errors import Conflict, NotFound, WakeHubError
from wakehub.hub import Hub
from wakehub.inventory import add_device, utcnow
from wakehub.oui import vendor
from wakehub.wol import ping

Discover = Callable[[str, Callable[[int, int], None]], list[dict[str, Any]]]


def default_cidr() -> str:
    try:
        route = json.loads(subprocess.check_output(["ip", "-4", "-j", "route", "show", "default"], text=True, timeout=3))
        device = route[0]["dev"]
        addrs = json.loads(subprocess.check_output(["ip", "-4", "-j", "addr", "show", "dev", device], text=True, timeout=3))
        for item in addrs[0].get("addr_info", []):
            if item.get("family") == "inet":
                network = ipaddress.ip_network(f"{item['local']}/{item['prefixlen']}", strict=False)
                return str(network)
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, ValueError, json.JSONDecodeError):
        return "192.168.1.0/24"
    return "192.168.1.0/24"


def start_scan(hub: Hub, cidr: str | None = None, discover: Discover | None = None) -> dict[str, Any]:
    running = hub.query_one("SELECT id FROM scans WHERE status = 'running'")
    if running is not None:
        raise Conflict("a scan is already running")
    network = _network(cidr or default_cidr())
    scan_id = hub.write(
        "INSERT INTO scans (cidr, status, progress, total, message, created_at) VALUES (?, 'running', 0, ?, '', ?)",
        (str(network), network.num_addresses, utcnow()),
    )
    worker = discover or discover_subnet
    thread = threading.Thread(target=_run, args=(hub, scan_id, str(network), worker), daemon=True)
    thread.start()
    return get_scan(hub, scan_id)


def _run(hub: Hub, scan_id: int, cidr: str, discover: Discover) -> None:
    def progress(done: int, total: int) -> None:
        hub.write("UPDATE scans SET progress = ?, total = ? WHERE id = ?", (done, total, scan_id))

    try:
        hosts = discover(cidr, progress)
        for host in hosts:
            hub.write(
                """
                INSERT INTO scan_hosts (scan_id, ip, mac, hostname, vendor, kinds, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    host.get("ip"),
                    host.get("mac"),
                    host.get("hostname") or "",
                    host.get("vendor") or vendor(host.get("mac")),
                    json.dumps(host.get("kinds") or []),
                    json.dumps(host.get("detail") or {}),
                ),
            )
        hub.write(
            "UPDATE scans SET status = 'done', progress = total, finished_at = ?, message = ? WHERE id = ?",
            (utcnow(), f"{len(hosts)} hosts", scan_id),
        )
    except Exception as exc:
        hub.write(
            "UPDATE scans SET status = 'error', error = ?, finished_at = ? WHERE id = ?",
            (str(exc), utcnow(), scan_id),
        )


def list_scans(hub: Hub) -> list[dict[str, Any]]:
    return [_public_scan(row) for row in hub.query("SELECT * FROM scans ORDER BY id DESC LIMIT 20")]


def get_scan(hub: Hub, scan_id: int) -> dict[str, Any]:
    row = hub.query_one("SELECT * FROM scans WHERE id = ?", (scan_id,))
    if row is None:
        raise NotFound(f"scan {scan_id} was not found")
    hosts = hub.query("SELECT * FROM scan_hosts WHERE scan_id = ? ORDER BY ip", (scan_id,))
    result = _public_scan(row)
    result["hosts"] = [
        {
            "id": host["id"],
            "ip": host["ip"],
            "mac": host["mac"],
            "hostname": host["hostname"],
            "vendor": host["vendor"],
            "kinds": json.loads(host["kinds"]),
            "detail": json.loads(host["detail"]),
        }
        for host in hosts
    ]
    return result


def add_from_scan(hub: Hub, scan_id: int, host_id: int, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from wakehub.endpoints import add_amt, add_jetkvm, add_pdu, add_plug, add_ups

    scan = get_scan(hub, scan_id)
    host = next((item for item in scan["hosts"] if item["id"] == host_id), None)
    if host is None:
        raise NotFound(f"scan host {host_id} was not found")
    extra = dict(payload or {})
    name = extra.pop("name", None) or host.get("hostname") or host["ip"]
    if kind == "device":
        return add_device(
            hub,
            {
                "name": name,
                "mac": host.get("mac"),
                "host": host["ip"],
                "notes": f"Added from scan of {scan['cidr']}",
                "tags": ["discovered"],
            },
        )
    if kind == "pdu":
        return add_pdu(hub, {"name": name, "host": host["ip"], **extra})
    if kind == "amt":
        return add_amt(hub, {"name": name, "host": host["ip"], **extra})
    if kind == "jetkvm":
        return add_jetkvm(hub, {"name": name, "host": host["ip"], **extra})
    if kind == "plug":
        plug_kind = extra.pop("plug_kind", None) or ("shelly" if "shelly" in host["kinds"] else "kasa")
        return add_plug(hub, {"name": name, "host": host["ip"], "kind": plug_kind, **extra})
    if kind == "ups":
        return add_ups(hub, {"name": name, "host": host["ip"], **extra})
    raise WakeHubError("kind must be device, pdu, amt, jetkvm, plug, or ups")


def discover_subnet(cidr: str, progress: Callable[[int, int], None]) -> list[dict[str, Any]]:
    network = _network(cidr)
    hosts = [str(ip) for ip in network.hosts()] or [str(network.network_address)]
    total = len(hosts)
    live: list[str] = []
    done = 0

    def probe(ip: str) -> str | None:
        return ip if ping(ip, timeout=1) else None

    with ThreadPoolExecutor(max_workers=32) as pool:
        for result in pool.map(probe, hosts):
            done += 1
            if result:
                live.append(result)
            if done % 16 == 0 or done == total:
                progress(done, total)
    arp = _arp_table()
    for ip, mac in arp.items():
        try:
            if ipaddress.ip_address(ip) in network and ip not in live and mac:
                live.append(ip)
        except ValueError:
            continue

    def describe(ip: str) -> dict[str, Any]:
        mac = arp.get(ip, "")
        kinds, detail = _fingerprint(ip, mac)
        return {
            "ip": ip,
            "mac": mac or None,
            "hostname": _hostname(ip),
            "vendor": vendor(mac),
            "kinds": kinds,
            "detail": detail,
        }

    if not live:
        return []
    with ThreadPoolExecutor(max_workers=min(32, len(live))) as pool:
        return list(pool.map(describe, live))


def _network(cidr: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise WakeHubError("cidr must be an IPv4 network such as 192.168.1.0/24") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise WakeHubError("only IPv4 subnets can be scanned")
    if network.prefixlen < 22:
        raise WakeHubError("scan a /22 or smaller so the sweep stays bounded")
    return network


def _arp_table() -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        lines = open("/proc/net/arp", encoding="utf-8").read().splitlines()[1:]
    except OSError:
        return table
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
            table[parts[0]] = parts[3].upper()
    return table


def _hostname(ip: str) -> str:
    from concurrent.futures import ThreadPoolExecutor as _Pool

    try:
        with _Pool(max_workers=1) as pool:
            return pool.submit(socket.gethostbyaddr, ip).result(timeout=0.4)[0]
    except (OSError, TimeoutError):
        return ""


def _fingerprint(ip: str, mac: str) -> tuple[list[str], dict[str, Any]]:
    kinds: list[str] = []
    detail: dict[str, Any] = {}
    if mac:
        kinds.append("wol")
    if _port_open(ip, 16992) or _port_open(ip, 16993):
        kinds.append("amt")
    if _port_open(ip, 9999):
        kinds.append("kasa")
    http = _http_kinds(ip)
    for kind in http:
        if kind not in kinds:
            kinds.append(kind)
    if _snmp_cyberpower(ip):
        if "ups" not in kinds:
            kinds.append("ups")
    return kinds, detail


def _port_open(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), 0.3):
            return True
    except OSError:
        return False


def _http_kinds(ip: str) -> list[str]:
    kinds = []
    try:
        with httpx.Client(timeout=0.6, verify=True) as client:
            status = client.get(f"http://{ip}/device/status")
            if status.status_code == 200 and "isSetup" in status.text:
                kinds.append("jetkvm")
            shelly = client.get(f"http://{ip}/shelly")
            if shelly.status_code == 200 and "gen" in shelly.text:
                kinds.append("shelly")
            pdu = client.get(f"http://{ip}/cmd.cgi?$A5")
            if pdu.status_code == 401 and synaccess_realm(pdu.headers.get("www-authenticate", "")):
                kinds.append("synaccess")
            elif pdu.status_code == 200:
                try:
                    parse_status(pdu.text)
                    kinds.append("synaccess")
                except WakeHubError:
                    if "netBooter" in pdu.text or "Synaccess" in pdu.text:
                        kinds.append("synaccess")
            root = client.get(f"http://{ip}/")
            if any(token in root.text for token in ("CyberPower", "RCCARD", "RMCARD")):
                kinds.append("ups")
    except httpx.HTTPError:
        return kinds
    return kinds


def _snmp_cyberpower(ip: str) -> bool:
    try:
        from wakehub.clients.ups import PysnmpTransport

        transport = PysnmpTransport(ip, 161, "2c", "public", "", "", "", "", "", timeout=0.4)
        values = transport.get(["1.3.6.1.2.1.1.2.0"])
    except Exception:
        return False
    text = " ".join(str(value) for value in values.values())
    return "1.3.6.1.4.1.3808" in text


def _public_scan(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "cidr": row["cidr"],
        "status": row["status"],
        "progress": row["progress"],
        "total": row["total"],
        "message": row["message"],
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }
