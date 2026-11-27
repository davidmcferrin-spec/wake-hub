from wakehub.capabilities import CAPABILITIES
from wakehub.mcp_server import build_server


def test_every_capability_is_on_the_api_and_in_the_ui(client):
    from wakehub.api import STATIC

    schema = client.get("/openapi.json").json()
    pieces = [client.get("/").text]
    for path in sorted(STATIC.iterdir()):
        if path.suffix in {".js", ".css", ".html"}:
            response = client.get(f"/static/{path.name}")
            assert response.status_code == 200
            pieces.append(response.text)
    ui = "\n".join(pieces)
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
