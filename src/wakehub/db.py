"""SQLite schema. Later tables are created the same way, if they are missing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    mac TEXT,
    host TEXT,
    broadcast TEXT NOT NULL DEFAULT '255.255.255.255',
    wol_port INTEGER NOT NULL DEFAULT 9,
    secureon_enc TEXT,
    notes TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    reach_mode TEXT NOT NULL DEFAULT 'icmp',
    reach_port INTEGER,
    reach_timeout REAL NOT NULL DEFAULT 30,
    wake_strategy TEXT NOT NULL DEFAULT 'wol_only',
    methods TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    device_id INTEGER,
    target_kind TEXT NOT NULL,
    target_id INTEGER,
    target_name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS actions_created ON actions (id DESC);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pdus (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 80,
    use_tls INTEGER NOT NULL DEFAULT 0,
    insecure_tls INTEGER NOT NULL DEFAULT 0,
    username TEXT NOT NULL DEFAULT '',
    password_enc TEXT,
    outlet_names TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS amt_endpoints (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 16992,
    use_tls INTEGER NOT NULL DEFAULT 0,
    insecure_tls INTEGER NOT NULL DEFAULT 0,
    username TEXT NOT NULL DEFAULT 'admin',
    password_enc TEXT NOT NULL,
    device_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jetkvm_endpoints (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 80,
    use_tls INTEGER NOT NULL DEFAULT 0,
    insecure_tls INTEGER NOT NULL DEFAULT 0,
    password_enc TEXT,
    extension TEXT NOT NULL DEFAULT '',
    poll_metrics INTEGER NOT NULL DEFAULT 0,
    device_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plugs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 80,
    username TEXT NOT NULL DEFAULT '',
    password_enc TEXT,
    insecure_tls INTEGER NOT NULL DEFAULT 0,
    protocol TEXT NOT NULL DEFAULT 'auto',
    switch_id INTEGER NOT NULL DEFAULT 0,
    device_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ups_cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 161,
    snmp_version TEXT NOT NULL DEFAULT '2c',
    community_enc TEXT,
    v3_user TEXT NOT NULL DEFAULT '',
    v3_auth_proto TEXT NOT NULL DEFAULT 'sha',
    v3_auth_enc TEXT,
    v3_priv_proto TEXT NOT NULL DEFAULT 'aes',
    v3_priv_enc TEXT,
    device_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    cidr TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS scan_hosts (
    id INTEGER PRIMARY KEY,
    scan_id INTEGER NOT NULL,
    ip TEXT NOT NULL,
    mac TEXT,
    hostname TEXT,
    vendor TEXT,
    kinds TEXT NOT NULL DEFAULT '[]',
    detail TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metric_samples (
    id INTEGER PRIMARY KEY,
    recorded_at TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    device_id INTEGER,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS metric_lookup ON metric_samples (source_kind, source_id, recorded_at);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
    have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in have:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _ensure_column(conn, "pdus", "insecure_tls", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "plugs", "insecure_tls", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "jetkvm_endpoints", "extension", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "jetkvm_endpoints", "poll_metrics", "INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn
