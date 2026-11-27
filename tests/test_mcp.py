import asyncio
import json

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def test_mcp_requires_a_bearer_token(live_server):
    response = httpx2.post(f"{live_server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 401
    response = httpx2.post(
        f"{live_server}/mcp",
        headers={"Authorization": "Bearer not-the-token"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert response.status_code == 401


def test_mcp_lists_tools_and_wakes_a_device(live_server, hub):
    asyncio.run(_exercise(live_server, hub.token))


async def _exercise(base: str, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(f"{base}/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert "wake_device" in names
                assert "list_devices" in names
                assert len(names) >= 16

                created = await session.call_tool(
                    "add_device",
                    {
                        "name": "MCP box",
                        "mac": "10:20:30:40:50:60",
                        "host": "127.0.0.1",
                        "broadcast": "127.0.0.1",
                        "reach_timeout": 2,
                    },
                )
                assert created.is_error is not True
                device = json.loads(created.content[0].text)
                device_id = device["id"]

                woken = await session.call_tool("wake_device", {"device_id": device_id})
                assert woken.is_error is not True
                wake_body = json.loads(woken.content[0].text)
                assert wake_body["sent"] is True
                assert wake_body["reachable"] is True

                calls = [
                    ("list_devices", {}),
                    ("get_device", {"device_id": device_id}),
                    ("update_device", {"device_id": device_id, "notes": "from mcp"}),
                    ("set_device_enabled", {"device_id": device_id, "enabled": True}),
                    ("power_action", {"device_id": device_id, "action": "on", "method": "wol"}),
                    ("device_status", {"device_id": device_id}),
                    ("list_status", {}),
                    ("list_actions", {"limit": 10}),
                    ("get_settings", {}),
                    ("update_settings", {"cors_origins": ["*"]}),
                    ("get_access_token", {}),
                    ("ui_login", {"password": "not-set"}),
                    ("remove_device", {"device_id": device_id}),
                ]
                for name, arguments in calls:
                    result = await session.call_tool(name, arguments)
                    text = " ".join(getattr(block, "text", "") for block in result.content)
                    assert "Unknown tool" not in text, name
                    if name == "ui_login":
                        assert result.is_error is True
                    else:
                        assert result.is_error is not True, f"{name}: {text}"
