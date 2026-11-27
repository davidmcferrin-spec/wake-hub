"""Subnet discovery. ARP and directed broadcast need host networking on Unraid."""

from __future__ import annotations

import ipaddress
import json
import select
import socket
import struct
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import httpx

from wakehub.clients.synaccess import parse_status, synaccess_realm
from wakehub.errors import ConfirmationRequired, Conflict, NotFound, WakeHubError
from wakehub.fingerprint import suggest
from wakehub.hub import Hub
from wakehub.inventory import add_device, host_for_url, utcnow
from wakehub.oui import vendor
from wakehub.wol import ping

_SKIPPED_IFACE = ("docker", "veth", "br-", "virbr", "cni", "flannel", "kube")

Discover = Callable[[str, Callable[[int, int], None]], list[dict[str, Any]]]


def _skipped_iface(name: str) -> bool:
    return name == "lo" or name.startswith(_SKIPPED_IFACE)


def interfaces_from(addrs: list[dict[str, Any]], routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = ""
    for route in routes:
        if route.get("dst") == "default" and route.get("dev"):
            primary = str(route["dev"])
            break
    found: list[dict[str, Any]] = []
    for item in addrs:
        name = str(item.get("ifname") or "")
        if _skipped_iface(name):
            continue
        for addr in item.get("addr_info") or []:
            if addr.get("family") not in (None, "inet", 2):
                continue
            local = str(addr.get("local") or "")
            if not local or local.startswith("127."):
                continue
            prefix = addr.get("prefixlen")
            if prefix is None:
                continue
            try:
                host = ipaddress.ip_address(local)
            except ValueError:
                continue
            if not isinstance(host, ipaddress.IPv4Address):
                continue
            # A LAN wider than /22 is offered as the /24 around this host.
            # The full network would be refused, and the picker would fall back to a placeholder.
            if int(prefix) < 22:
                cidr = str(ipaddress.ip_network(f"{host}/24", strict=False))
            else:
                network = ipaddress.ip_network(f"{host}/{int(prefix)}", strict=False)
                if not isinstance(network, ipaddress.IPv4Network):
                    continue
                cidr = str(network)
            found.append({"name": name, "cidr": cidr, "primary": bool(primary) and name == primary})
    return _merge_interfaces(found)


def _merge_interfaces(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One choice per subnet. Unraid shows the same LAN on br0, shim-br0 and vhost0."""
    merged: dict[str, dict[str, Any]] = {}
    for item in found:
        current = merged.get(item["cidr"])
        if current is None or _prefer_iface(item, current):
            merged[item["cidr"]] = item
    chosen = list(merged.values())
    if chosen and not any(item["primary"] for item in chosen):
        chosen[0]["primary"] = True
    return chosen


def _prefer_iface(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    if candidate["primary"] != current["primary"]:
        return bool(candidate["primary"])
    return _extra_iface(current["name"]) and not _extra_iface(candidate["name"])


def _extra_iface(name: str) -> bool:
    return name.startswith(("shim", "vhost"))


def list_interfaces() -> list[dict[str, Any]]:
    try:
        addrs = json.loads(subprocess.check_output(["ip", "-4", "-j", "addr"], text=True, timeout=3))
        routes = json.loads(subprocess.check_output(["ip", "-4", "-j", "route"], text=True, timeout=3))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return [{"name": "lan", "cidr": "192.168.1.0/24", "primary": True}]
    return interfaces_from(addrs, routes) or [{"name": "lan", "cidr": "192.168.1.0/24", "primary": True}]


def default_cidr() -> str:
    chosen = next((item for item in list_interfaces() if item["primary"]), None)
    return chosen["cidr"] if chosen else "192.168.1.0/24"


def start_scan(hub: Hub, cidr: str | None = None, discover: Discover | None = None, *, replace: bool = False) -> dict[str, Any]:
    running = hub.query_one("SELECT id FROM scans WHERE status = 'running'")
    if running is not None:
        raise Conflict("a scan is already running")
    network = _network(cidr or default_cidr())
    if replace:
        _delete_finished_for_cidr(hub, str(network))
    scan_id = hub.write(
        "INSERT INTO scans (cidr, status, progress, total, message, created_at) VALUES (?, 'running', 0, ?, '', ?)",
        (str(network), network.num_addresses, utcnow()),
    )
    worker = discover or discover_subnet
    thread = threading.Thread(target=_run, args=(hub, scan_id, str(network), worker), daemon=True)
    hub.track_background(thread)
    thread.start()
    return get_scan(hub, scan_id)


def _run(hub: Hub, scan_id: int, cidr: str, discover: Discover) -> None:
    def progress(done: int, total: int) -> None:
        if hub.stopping():
            return
        hub.write("UPDATE scans SET progress = ?, total = ? WHERE id = ?", (done, total, scan_id))

    try:
        hosts = discover(cidr, progress)
        if hub.stopping():
            return
        for host in hosts:
            if hub.stopping():
                return
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
        if hub.stopping():
            return
        hub.write(
            "UPDATE scans SET status = 'done', progress = total, finished_at = ?, message = ? WHERE id = ?",
            (utcnow(), f"{len(hosts)} hosts", scan_id),
        )
    except Exception as exc:
        if not hub.stopping():
            hub.write(
                "UPDATE scans SET status = 'error', error = ?, finished_at = ? WHERE id = ?",
                (str(exc), utcnow(), scan_id),
            )
        return
    if not hub.stopping():
        prune_scans(hub)


def delete_scan(hub: Hub, scan_id: int) -> dict[str, Any]:
    row = hub.query_one("SELECT id, status FROM scans WHERE id = ?", (scan_id,))
    if row is None:
        raise NotFound(f"scan {scan_id} was not found")
    if row["status"] == "running":
        raise Conflict("a running scan cannot be deleted")
    # Inventory devices are a different table and are not touched.
    hub.write("DELETE FROM scan_hosts WHERE scan_id = ?", (scan_id,))
    hub.write("DELETE FROM scans WHERE id = ?", (scan_id,))
    return {"removed": scan_id}


def clear_scans(hub: Hub, *, confirm: bool) -> dict[str, Any]:
    if confirm is not True:
        raise ConfirmationRequired("clearing scan history needs confirm set to true")
    rows = hub.query("SELECT id FROM scans WHERE status != 'running'")
    removed = _delete_scan_ids(hub, [row["id"] for row in rows])
    running = hub.query_one("SELECT id FROM scans WHERE status = 'running'")
    return {"removed": removed, "kept_running": running["id"] if running else None}


def rescan(hub: Hub, scan_id: int, *, replace: bool = True, discover: Discover | None = None) -> dict[str, Any]:
    row = hub.query_one("SELECT id, cidr FROM scans WHERE id = ?", (scan_id,))
    if row is None:
        raise NotFound(f"scan {scan_id} was not found")
    return start_scan(hub, row["cidr"], discover, replace=replace)


def prune_scans(hub: Hub) -> int:
    from wakehub.inventory import public_settings

    settings = public_settings(hub)
    keep = int(settings.get("scan_keep") or 0)
    days = int(settings.get("scan_keep_days") or 0)
    if keep <= 0 and days <= 0:
        return 0
    doomed: set[int] = set()
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
        for row in hub.query(
            """
            SELECT id FROM scans
            WHERE status != 'running' AND COALESCE(finished_at, created_at) < ?
            """,
            (cutoff,),
        ):
            doomed.add(row["id"])
    if keep > 0:
        finished = hub.query("SELECT id FROM scans WHERE status != 'running' ORDER BY id DESC")
        for row in finished[keep:]:
            doomed.add(row["id"])
    return _delete_scan_ids(hub, doomed)


def _delete_finished_for_cidr(hub: Hub, cidr: str) -> int:
    rows = hub.query("SELECT id FROM scans WHERE cidr = ? AND status != 'running'", (cidr,))
    return _delete_scan_ids(hub, [row["id"] for row in rows])


def _delete_scan_ids(hub: Hub, scan_ids) -> int:
    ids = [int(item) for item in scan_ids]
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    hub.write(f"DELETE FROM scan_hosts WHERE scan_id IN ({marks})", tuple(ids))
    hub.write(f"DELETE FROM scans WHERE id IN ({marks}) AND status != 'running'", tuple(ids))
    return len(ids)


def list_scans(hub: Hub) -> list[dict[str, Any]]:
    return [_public_scan(row) for row in hub.query("SELECT * FROM scans ORDER BY id DESC LIMIT 20")]


def get_scan(hub: Hub, scan_id: int) -> dict[str, Any]:
    row = hub.query_one("SELECT * FROM scans WHERE id = ?", (scan_id,))
    if row is None:
        raise NotFound(f"scan {scan_id} was not found")
    hosts = hub.query("SELECT * FROM scan_hosts WHERE scan_id = ? ORDER BY ip", (scan_id,))
    result = _public_scan(row)
    from wakehub.identity import host_key as normalize_host
    from wakehub.identity import mac_key as normalize_mac_key

    known = _inventory_index(hub)
    result["hosts"] = []
    for host in hosts:
        detail = json.loads(host["detail"])
        ip = host["ip"]
        mac = host["mac"] or ""
        matches: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        keys = [normalize_host(ip)]
        if mac:
            try:
                keys.append(normalize_mac_key(mac))
            except WakeHubError:
                pass
        for key in keys:
            for item in known.get(key) or []:
                marker = (item["kind"], item["id"])
                if marker not in seen:
                    seen.add(marker)
                    matches.append(item)
        result["hosts"].append(
            {
                "id": host["id"],
                "ip": ip,
                "mac": host["mac"],
                "hostname": host["hostname"],
                "vendor": host["vendor"],
                "kinds": json.loads(host["kinds"]),
                "detail": detail,
                "matches": matches,
                "known": matches[0] if matches else None,
            }
        )
    return result


def add_from_scan(hub: Hub, scan_id: int, host_id: int, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from wakehub.endpoints import add_amt, add_jetkvm, add_pdu, add_plug, add_roku, add_ups

    scan = get_scan(hub, scan_id)
    host = next((item for item in scan["hosts"] if item["id"] == host_id), None)
    if host is None:
        raise NotFound(f"scan host {host_id} was not found")
    extra = dict(payload or {})
    suggestion = (host.get("detail") or {}).get("suggestion") or {}
    prefill = dict(suggestion.get("prefill") or {})
    prefill.update({key: value for key, value in extra.items() if value not in (None, "")})
    extra = prefill
    name = extra.pop("name", None) or host.get("hostname") or host["ip"]
    extra.pop("kind", None)
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
    if kind == "roku":
        return add_roku(hub, {"name": name, "host": host["ip"], "port": int(extra.pop("port", None) or 8060), **extra})
    raise WakeHubError("kind must be device, pdu, amt, jetkvm, plug, ups, or roku")


def discover_subnet(cidr: str, progress: Callable[[int, int], None]) -> list[dict[str, Any]]:
    network = _network(cidr)
    hosts = [str(ip) for ip in network.hosts()] or [str(network.network_address)]
    total = len(hosts)
    found: dict[str, dict[str, Any]] = {}
    done = 0

    def inspect(ip: str, arp: dict[str, str], names: list[str], answered: bool) -> dict[str, Any] | None:
        if not answered and ip not in arp:
            return None
        mac = arp.get(ip, "")
        kinds, detail = _fingerprint(ip, mac, names)
        return {
            "ip": ip,
            "mac": mac or None,
            "hostname": _hostname(ip),
            "vendor": vendor(mac),
            "kinds": kinds,
            "detail": detail,
        }

    with ThreadPoolExecutor(max_workers=32) as pool:
        arp_job = pool.submit(_arp_table)
        mdns_job = pool.submit(_mdns_names)
        ssdp_job = pool.submit(_roku_ssdp)
        pings = {pool.submit(ping, ip, 1): ip for ip in hosts}
        arp = arp_job.result()
        names_by_ip = mdns_job.result()
        roku_ips = ssdp_job.result()
        for job in as_completed(pings):
            ip = pings[job]
            done += 1
            try:
                answered = bool(job.result())
            except Exception:
                answered = False
            if not answered and ip not in arp:
                if done % 16 == 0 or done == total:
                    progress(done, total)
                continue
            described = inspect(ip, arp, names_by_ip.get(ip, []), answered or ip in arp)
            if described:
                found[ip] = described
            if done % 16 == 0 or done == total:
                progress(done, total)
        for ip, mac in arp.items():
            if ip in found or not mac:
                continue
            try:
                if ipaddress.ip_address(ip) not in network:
                    continue
            except ValueError:
                continue
            described = inspect(ip, arp, names_by_ip.get(ip, []), False)
            if described:
                found[ip] = described
        for ip in roku_ips:
            own_names = names_by_ip.get(ip, [])
            if ip in found:
                detail = found[ip].setdefault("detail", {})
                suggestion = dict((detail.get("suggestion") or {}))
                if suggestion.get("type") != "roku":
                    kinds, finger = _fingerprint(ip, found[ip].get("mac") or "", own_names)
                    finger["suggestion"] = suggest(
                        vendor=found[ip].get("vendor") or "",
                        mac=found[ip].get("mac") or "",
                        ports=set(finger.get("ports") or []),
                        http_kinds=kinds,
                        mdns=own_names,
                        ssdp=True,
                    )
                    found[ip]["kinds"] = kinds
                    found[ip]["detail"] = finger
                continue
            try:
                if ipaddress.ip_address(ip) not in network:
                    continue
            except ValueError:
                continue
            described = inspect(ip, arp, own_names, True)
            if described:
                described["detail"]["suggestion"] = suggest(
                    vendor=described.get("vendor") or "",
                    mac=described.get("mac") or "",
                    ports=set((described.get("detail") or {}).get("ports") or []),
                    http_kinds=described.get("kinds") or [],
                    mdns=own_names,
                    ssdp=True,
                )
                found[ip] = described
    return list(found.values())


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


def _fingerprint(ip: str, mac: str, mdns: list[str] | None = None) -> tuple[list[str], dict[str, Any]]:
    kinds: list[str] = []
    ports: set[int] = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        checks = {pool.submit(_port_open, ip, port): port for port in (80, 443, 16992, 16993, 9999, 161, 8060)}
        for job in as_completed(checks):
            if job.result():
                ports.add(checks[job])
    if mac:
        kinds.append("wol")
    if 16992 in ports or 16993 in ports:
        kinds.append("amt")
    if 9999 in ports:
        kinds.append("kasa")
    http = _http_kinds(ip)
    for kind in http:
        if kind not in kinds:
            kinds.append(kind)
    if 161 in ports and _snmp_cyberpower(ip) and "ups" not in kinds:
        kinds.append("ups")
    if 8060 in ports and "roku" not in kinds:
        kinds.append("roku")
    suggestion = suggest(vendor=vendor(mac), mac=mac, ports=ports, http_kinds=http, mdns=mdns or [])
    return kinds, {"ports": sorted(ports), "suggestion": suggestion}


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
            host = host_for_url(ip)
            status = client.get(f"http://{host}/device/status")
            if status.status_code == 200 and "isSetup" in status.text:
                kinds.append("jetkvm")
            shelly = client.get(f"http://{host}/shelly")
            if shelly.status_code == 200 and "gen" in shelly.text:
                kinds.append("shelly")
            pdu = client.get(f"http://{host}/cmd.cgi?$A5")
            if pdu.status_code == 401 and synaccess_realm(pdu.headers.get("www-authenticate", "")):
                kinds.append("synaccess")
            elif pdu.status_code == 200:
                try:
                    parse_status(pdu.text)
                    kinds.append("synaccess")
                except WakeHubError:
                    if "netBooter" in pdu.text or "Synaccess" in pdu.text:
                        kinds.append("synaccess")
            root = client.get(f"http://{host}/")
            if any(token in root.text for token in ("CyberPower", "RCCARD", "RMCARD")):
                kinds.append("ups")
    except httpx.HTTPError:
        pass
    try:
        with httpx.Client(timeout=0.6) as client:
            info = client.get(f"http://{host_for_url(ip)}:8060/query/device-info")
            if info.status_code == 200 and ("power-mode" in info.text or "Roku" in info.text):
                kinds.append("roku")
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


def _inventory_index(hub: Hub) -> dict[str, list[dict[str, Any]]]:
    from wakehub.identity import host_key as normalize_host
    from wakehub.identity import mac_key as normalize_mac_key

    index: dict[str, list[dict[str, Any]]] = {}

    def remember(key: str | None, kind: str, item_id: int, name: str) -> None:
        if not key:
            return
        bucket = index.setdefault(key, [])
        if not any(item["kind"] == kind and item["id"] == item_id for item in bucket):
            bucket.append({"kind": kind, "id": item_id, "name": name})

    for row in hub.query("SELECT id, name, host, mac, host_key, mac_key FROM devices"):
        remember(row["host_key"] or normalize_host(row["host"]), "device", row["id"], row["name"])
        mac = row["mac_key"]
        if not mac and row["mac"]:
            try:
                mac = normalize_mac_key(row["mac"])
            except WakeHubError:
                mac = None
        remember(mac, "device", row["id"], row["name"])
    for table, kind in (
        ("pdus", "pdu"),
        ("amt_endpoints", "amt"),
        ("jetkvm_endpoints", "jetkvm"),
        ("plugs", "plug"),
        ("ups_cards", "ups"),
        ("rokus", "roku"),
    ):
        for row in hub.query(f"SELECT id, name, host, host_key FROM {table}"):
            remember(row["host_key"] or normalize_host(row["host"]), kind, row["id"], row["name"])
    return index


def _roku_ssdp() -> set[str]:
    from wakehub.clients.roku import discover_ecp

    return {str(item["ip"]) for item in discover_ecp()}


def _mdns_names() -> dict[str, list[str]]:
    """Ask the LAN for Shelly and JetKVM names, keyed by the address that sent them."""
    queries = (_dns_query("_shelly._tcp.local"), _dns_query("_jetkvm._tcp.local"))
    by_ip: dict[str, list[str]] = {}
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setblocking(False)
        for query in queries:
            sock.sendto(query, ("224.0.0.251", 5353))
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            try:
                ready, _, _ = select.select([sock], [], [], 0.2)
                if not ready:
                    continue
                packet, addr = sock.recvfrom(2048)
                _remember_mdns(by_ip, packet, addr[0])
            except Exception:
                # One bad reply must not close the listen window.
                continue
    except Exception:
        # A bad packet or a closed multicast socket must not fail the whole scan.
        return by_ip
    finally:
        if sock is not None:
            sock.close()
    return by_ip


def _remember_mdns(by_ip: dict[str, list[str]], packet: bytes, sender: str) -> None:
    names, addresses = _dns_records(packet)
    targets = {sender} if sender else set()
    for ip, owner in addresses:
        targets.add(ip)
        if owner and owner not in names:
            names.append(owner)
    for ip in targets:
        bucket = by_ip.setdefault(ip, [])
        for name in names:
            if name and name not in bucket:
                bucket.append(name)


def _dns_query(name: str) -> bytes:
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.split(".")) + b"\x00"
    return b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00" + labels + b"\x00\x0c\x00\x01"


def _dns_names(packet: bytes) -> list[str]:
    names, _addresses = _dns_records(packet)
    return names


def _dns_records(packet: bytes) -> tuple[list[str], list[tuple[str, str]]]:
    names: list[str] = []
    addresses: list[tuple[str, str]] = []
    if len(packet) < 12:
        return names, addresses
    offset = 12
    try:
        questions = int.from_bytes(packet[4:6], "big")
        answers = int.from_bytes(packet[6:8], "big")
        for _ in range(questions):
            _name, offset = _dns_label(packet, offset)
            offset += 4
        for _ in range(answers):
            name, offset = _dns_label(packet, offset)
            if offset + 10 > len(packet):
                break
            kind, _klass, _ttl, length = struct.unpack("!HHIH", packet[offset:offset + 10])
            offset += 10
            if name:
                names.append(name)
            if kind == 1 and length == 4 and offset + 4 <= len(packet):
                addresses.append((socket.inet_ntoa(packet[offset:offset + 4]), name))
            offset += length
    except (IndexError, struct.error, UnicodeError):
        return names, addresses
    return names, addresses


def _dns_label(packet: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    end = offset
    guard = 0
    while guard < 20:
        guard += 1
        if offset >= len(packet):
            break
        length = packet[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                break
            pointer = ((length & 0x3F) << 8) | packet[offset + 1]
            if not jumped:
                end = offset + 2
            offset = pointer
            jumped = True
            continue
        offset += 1
        labels.append(packet[offset:offset + length].decode("ascii", "replace"))
        offset += length
    return ".".join(labels), (end if jumped else offset)


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
