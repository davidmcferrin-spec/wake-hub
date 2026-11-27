import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from wakehub.config import Settings
from wakehub.errors import Conflict
from wakehub.hub import Hub, set_hub
from wakehub.inventory import add_device, utcnow
from wakehub.mcp_server import build_server
from wakehub.scan import add_from_scan


def test_device_ip_and_mac_must_be_unique(client):
    first = client.post(
        "/api/v1/devices",
        json={"name": "Studio", "mac": "AA:BB:CC:DD:EE:30", "host": "2001:db8::10"},
    )
    assert first.status_code == 201
    mac = client.post(
        "/api/v1/devices",
        json={"name": "Other", "mac": "aa-bb-cc-dd-ee-30", "host": "10.9.9.9"},
    )
    assert mac.status_code == 409
    assert mac.json()["error"]["existing"]["name"] == "Studio"
    assert "Studio" in mac.json()["error"]["message"]
    ipv6 = client.post(
        "/api/v1/devices",
        json={"name": "Alias", "mac": "AA:BB:CC:DD:EE:31", "host": " 2001:0db8:0000::10 "},
    )
    assert ipv6.status_code == 409
    assert ipv6.json()["error"]["existing"]["id"] == first.json()["id"]


def test_each_hardware_kind_has_one_host(client):
    created = client.post("/api/v1/pdus", json={"name": "Rack", "host": "10.4.4.4"})
    assert created.status_code == 201
    again = client.post("/api/v1/pdus", json={"name": "Second", "host": "10.4.4.4"})
    assert again.status_code == 409
    assert "Rack" in again.json()["error"]["message"]
    other_kind = client.post("/api/v1/ups", json={"name": "Card", "host": "10.4.4.4"})
    assert other_kind.status_code == 201


def test_mcp_duplicate_is_a_tool_error(hub):
    set_hub(hub)
    add_device(hub, {"name": "Studio", "mac": "AA:BB:CC:DD:EE:32", "host": "10.8.8.8"})
    server = build_server()
    with pytest.raises(ToolError, match="Studio"):
        import asyncio

        asyncio.run(server.call_tool("add_device", {"name": "Copy", "mac": "aa:bb:cc:dd:ee:32"}))


def test_add_from_scan_flags_an_existing_device(hub):
    set_hub(hub)
    add_device(hub, {"name": "Studio", "mac": "AA:BB:CC:DD:EE:33", "host": "10.7.7.7"})
    now = utcnow()
    scan_id = hub.write(
        "INSERT INTO scans (cidr, status, progress, total, message, created_at) VALUES ('10.7.7.0/30', 'done', 1, 1, '', ?)",
        (now,),
    )
    host_id = hub.write(
        """
        INSERT INTO scan_hosts (scan_id, ip, mac, hostname, vendor, kinds, detail)
        VALUES (?, '10.7.7.7', 'aa:bb:cc:dd:ee:33', '', '', '[]', '{}')
        """,
        (scan_id,),
    )
    with pytest.raises(Conflict, match="Studio"):
        add_from_scan(hub, scan_id, host_id, "device", {})


def test_existing_duplicates_are_reported_and_kept(tmp_path):
    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        host="127.0.0.1",
        port=0,
        secret_key="test-secret",
        cors_origins=(),
    )
    first = Hub.open(settings)
    now = utcnow()
    for name in ("One", "Two"):
        first.write(
            """
            INSERT INTO devices (
                name, host, broadcast, wol_port, notes, tags, enabled, reach_mode,
                reach_timeout, wake_strategy, methods, created_at, updated_at
            ) VALUES (?, '10.1.1.9', '255.255.255.255', 9, '', '[]', 1, 'icmp', 30, 'wol_only', '[]', ?, ?)
            """,
            (name, now, now),
        )
    first.close()
    again = Hub.open(settings)
    names = [row["name"] for row in again.query("SELECT name FROM devices ORDER BY name")]
    assert names == ["One", "Two"]
    report = json.loads(again.setting("duplicate_records") or "[]")
    assert any(item["key"] == "10.1.1.9" and item["kind"] == "device" for item in report)
    again.close()
