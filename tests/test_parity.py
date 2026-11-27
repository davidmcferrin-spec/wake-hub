from wakehub.capabilities import CAPABILITIES
from wakehub.mcp_server import build_server


def test_every_capability_is_on_the_api_and_in_the_ui(client):
    schema = client.get("/openapi.json").json()
    ui = "\n".join(
        [
            client.get("/").text,
            client.get("/static/app.js").text,
            client.get("/static/app.css").text,
        ]
    )
    missing_api = []
    missing_ui = []
    for cap in CAPABILITIES:
        path = schema["paths"].get(cap.path)
        if path is None or cap.method.lower() not in path:
            missing_api.append(cap.id)
        if f'data-cap="{cap.id}"' not in ui:
            missing_ui.append(cap.id)
    assert missing_api == []
    assert missing_ui == []


def test_mcp_tool_names_match_the_registry():
    import asyncio

    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    expected = {cap.mcp_tool for cap in CAPABILITIES}
    assert names == expected
    for tool in tools:
        assert tool.description
