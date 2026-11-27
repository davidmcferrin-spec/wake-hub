"""One host, and one MAC, per kind of record. Existing duplicates are reported, not deleted."""

from __future__ import annotations

import ipaddress
import json
import logging
import sqlite3

from wakehub.errors import Conflict, WakeHubError
from wakehub.wol import normalize_mac

log = logging.getLogger("wakehub.identity")

TABLES = {
    "device": ("devices", True),
    "pdu": ("pdus", False),
    "amt": ("amt_endpoints", False),
    "jetkvm": ("jetkvm_endpoints", False),
    "plug": ("plugs", False),
    "ups": ("ups_cards", False),
    "roku": ("rokus", False),
}

LABELS = {
    "device": "device",
    "pdu": "PDU",
    "amt": "AMT endpoint",
    "jetkvm": "JetKVM",
    "plug": "plug",
    "ups": "UPS",
    "roku": "Roku",
}


def host_key(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().rstrip(".")
    if not text:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return text.lower()


def mac_key(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return normalize_mac(str(value))


def migrate_identity(conn: sqlite3.Connection) -> list[dict]:
    """Fill comparison keys and add unique indexes when the table has no duplicates."""
    duplicates = _backfill(conn)
    for kind, (table, has_mac) in TABLES.items():
        duplicates.extend(_index_or_report(conn, kind, table, "host_key"))
        if has_mac:
            duplicates.extend(_index_or_report(conn, kind, table, "mac_key"))
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('duplicate_records', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(duplicates),),
    )
    return duplicates


def _backfill(conn: sqlite3.Connection) -> list[dict]:
    """Assign keys. A repeated key is left unset and reported so the row is not deleted."""
    duplicates: list[dict] = []
    for kind, (table, has_mac) in TABLES.items():
        columns = "id, name, host, mac" if has_mac else "id, name, host"
        seen_host: dict[str, tuple[int, str]] = {}
        seen_mac: dict[str, tuple[int, str]] = {}
        for row in conn.execute(f"SELECT {columns} FROM {table} ORDER BY id"):
            key = host_key(row["host"])
            if key and key in seen_host:
                first_id, first_name = seen_host[key]
                duplicates.append(
                    {
                        "kind": kind,
                        "field": "host_key",
                        "key": key,
                        "ids": f"{first_id},{row['id']}",
                        "names": f"{first_name}, {row['name']}",
                    }
                )
                log.warning("left duplicate %s host %s in place: %s and %s", kind, key, first_name, row["name"])
                key = None
            elif key:
                seen_host[key] = (row["id"], row["name"])
            mac = None
            if has_mac and row["mac"]:
                try:
                    mac = mac_key(row["mac"])
                except WakeHubError:
                    mac = None
                if mac and mac in seen_mac:
                    first_id, first_name = seen_mac[mac]
                    duplicates.append(
                        {
                            "kind": kind,
                            "field": "mac_key",
                            "key": mac,
                            "ids": f"{first_id},{row['id']}",
                            "names": f"{first_name}, {row['name']}",
                        }
                    )
                    log.warning("left duplicate %s MAC %s in place: %s and %s", kind, mac, first_name, row["name"])
                    mac = None
                elif mac:
                    seen_mac[mac] = (row["id"], row["name"])
            if has_mac:
                conn.execute("UPDATE devices SET host_key = ?, mac_key = ? WHERE id = ?", (key, mac, row["id"]))
            else:
                conn.execute(f"UPDATE {table} SET host_key = ? WHERE id = ?", (key, row["id"]))
    return duplicates


def _index_or_report(conn: sqlite3.Connection, kind: str, table: str, column: str) -> list[dict]:
    grouped = conn.execute(
        f"""
        SELECT {column} AS key, GROUP_CONCAT(id) AS ids, GROUP_CONCAT(name) AS names, COUNT(*) AS n
        FROM {table}
        WHERE {column} IS NOT NULL AND {column} != ''
        GROUP BY {column}
        HAVING n > 1
        """
    ).fetchall()
    if grouped:
        found = []
        for row in grouped:
            found.append({"kind": kind, "field": column, "key": row["key"], "ids": row["ids"], "names": row["names"]})
            log.warning("left duplicate %s %s %s in place: %s", kind, column, row["key"], row["names"])
        return found
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {table}_{column} ON {table}({column}) "
        f"WHERE {column} IS NOT NULL AND {column} != ''"
    )
    return []


def assert_available(hub, kind: str, host: str | None, mac: str | None = None, *, exclude_id: int | None = None) -> None:
    table, has_mac = TABLES[kind]
    key = host_key(host)
    if key:
        row = _find(hub, table, "host_key", key, exclude_id)
        if row is not None:
            _raise(kind, "host", key, row)
    if has_mac and mac:
        try:
            normalized = mac_key(mac)
        except WakeHubError:
            raise
        if normalized:
            row = _find(hub, table, "mac_key", normalized, exclude_id)
            if row is not None:
                _raise(kind, "MAC", normalized, row)


def bind_identity(hub, kind: str, item_id: int, host: str | None, mac: str | None = None) -> None:
    table, has_mac = TABLES[kind]
    key = host_key(host)
    try:
        if has_mac:
            normalized = mac_key(mac) if mac else None
            hub.write("UPDATE devices SET host_key = ?, mac_key = ? WHERE id = ?", (key, normalized, item_id))
        else:
            hub.write(f"UPDATE {table} SET host_key = ? WHERE id = ?", (key, item_id))
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"that {LABELS[kind]} conflicts with an existing record") from exc


def _find(hub, table: str, column: str, key: str, exclude_id: int | None):
    if exclude_id is None:
        return hub.query_one(f"SELECT id, name FROM {table} WHERE {column} = ?", (key,))
    return hub.query_one(
        f"SELECT id, name FROM {table} WHERE {column} = ? AND id != ?",
        (key, exclude_id),
    )


def _raise(kind: str, field: str, key: str, row) -> None:
    label = LABELS[kind]
    raise Conflict(
        f"{field} {key} is already {label} {row['name']} (id {row['id']})",
        existing={"kind": kind, "id": row["id"], "name": row["name"]},
    )
