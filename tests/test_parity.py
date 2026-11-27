import asyncio
import re

from wakehub.api import STATIC
from wakehub.capabilities import CAPABILITIES
from wakehub.mcp_server import build_server


def _resolve(schema: dict, node: dict) -> dict:
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return _resolve(schema, schema["components"]["schemas"][name])
    if "allOf" in node:
        merged: dict = {"properties": {}, "required": []}
        for part in node["allOf"]:
            resolved = _resolve(schema, part)
            merged["properties"].update(resolved.get("properties", {}))
            merged["required"].extend(resolved.get("required", []))
        return merged
    if "anyOf" in node or "oneOf" in node:
        for part in node.get("anyOf", node.get("oneOf", [])):
            resolved = _resolve(schema, part)
            if resolved.get("properties") or resolved.get("type") == "object":
                return resolved
        return {}
    return node


def _operation_fields(schema: dict, operation: dict) -> tuple[set[str], set[str]]:
    path_fields: set[str] = set()
    body_fields: set[str] = set()
    for param in operation.get("parameters", []):
        if param.get("in") == "path":
            path_fields.add(param["name"])
        elif param.get("in") == "query":
            body_fields.add(param["name"])
    body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    if body:
        resolved = _resolve(schema, body)
        body_fields.update(resolved.get("properties", {}))
    return path_fields, body_fields


def _ui_controls(text: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    pattern = re.compile(
        r"data-cap=\"([a-z0-9_]+)\"[^>]*data-fields=\"([^\"]*)\"|data-fields=\"([^\"]*)\"[^>]*data-cap=\"([a-z0-9_]+)\"",
    )
    for match in pattern.finditer(text):
        if match.group(1):
            cap, fields = match.group(1), match.group(2)
        else:
            cap, fields = match.group(4), match.group(3)
        found.setdefault(cap, set()).add(fields)
    return found


def _handlers(text: str) -> set[str]:
    block = re.search(r"(?:const|window\.)CONTROL_HANDLERS = \{([\s\S]*?)\n\};", text)
    if block is None:
        return set()
    return set(re.findall(r"^\s{2}([a-z0-9_]+)\s*(?:\(|:)", block.group(1), re.M))


def test_every_capability_is_on_the_api_mcp_and_ui(client):
    schema = client.get("/openapi.json").json()
    pieces = [client.get("/").text]
    for path in sorted(STATIC.iterdir()):
        if path.suffix in {".js", ".css", ".html"}:
            response = client.get(f"/static/{path.name}")
            assert response.status_code == 200
            pieces.append(response.text)
    ui = "\n".join(pieces)
    controls = _ui_controls(ui)
    handlers = _handlers(ui)
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    missing = []
    for cap in CAPABILITIES:
        operation = schema["paths"].get(cap.path, {}).get(cap.method.lower())
        if operation is None:
            missing.append(f"{cap.id} missing {cap.method} {cap.path}")
            continue
        path_fields, body_fields = _operation_fields(schema, operation)
        tool = tools.get(cap.mcp_tool)
        if tool is None:
            missing.append(f"{cap.id} missing mcp tool")
            continue
        mcp_fields = set((tool.input_schema or {}).get("properties", {}))
        if mcp_fields != path_fields | body_fields:
            missing.append(
                f"{cap.id} fields rest={sorted(path_fields | body_fields)} mcp={sorted(mcp_fields)}"
            )
        expected = ",".join(sorted(body_fields))
        if cap.id not in controls or expected not in controls[cap.id]:
            missing.append(f"{cap.id} ui fields want {expected!r} have {controls.get(cap.id)}")
        if cap.id not in handlers:
            missing.append(f"{cap.id} has no dispatcher")
    assert missing == []


def test_every_ui_button_is_a_capability(client):
    pieces = []
    for path in sorted(STATIC.iterdir()):
        if path.suffix == ".js":
            pieces.append(path.read_text())
    controls = _ui_controls("\n".join(pieces))
    known = {item.id for item in CAPABILITIES}
    extra = sorted(set(controls) - known)
    assert extra == [], extra


def test_poll_dispatch_reaches_scan_and_history():
    source = (STATIC / "app.js").read_text()
    body = source.split("async function pollStatus", 1)[1].split("window.pollStatus = pollStatus", 1)[0]
    for name in ("pollScan", "pollHistory"):
        assert name in body, name
        head = body.split(name, 1)[0]
        for match in re.finditer(r"if\s*\((.*?)\)\s*return\s*;", head, re.S):
            condition = match.group(1)
            if "state.page" not in condition and "page" not in condition:
                continue
            assert '"scan"' in condition and '"history"' in condition, condition


def _api_clicks_missing_a_capability(text: str) -> list[str]:
    # A consuming tail would hide the next class check, so each window stops there.
    marks = list(re.finditer(r'classList\.contains\("([^"]+)"\)', text))
    missing = []
    for index, match in enumerate(marks):
        name = match.group(1)
        end = marks[index + 1].start() if index + 1 < len(marks) else match.end() + 600
        tail = text[match.end():min(end, match.end() + 600)]
        if "api(" not in tail and "/api/v1" not in tail:
            continue
        buttons = re.findall(rf"<button\b[^>]*\b{re.escape(name)}\b[^>]*>", text)
        if not buttons or any("data-cap=" not in tag for tag in buttons):
            missing.append(name)
    return missing


def test_direct_api_clicks_declare_a_capability():
    bare = """
    if (event.target.classList.contains("method-row")) { keep going; }
    if (event.target.classList && event.target.classList.contains("test-method")) {
      api("POST", "/api/v1/test", { kind: "wol" });
    }
    <button type="button" class="ghost test-method">Test</button>
    """
    assert _api_clicks_missing_a_capability(bare) == ["test-method"]
    pieces = []
    for path in sorted(STATIC.iterdir()):
        if path.suffix == ".js":
            pieces.append(path.read_text())
    assert _api_clicks_missing_a_capability("\n".join(pieces)) == []


def test_every_api_operation_is_a_capability(client):
    schema = client.get("/openapi.json").json()
    covered = {(cap.method.lower(), cap.path) for cap in CAPABILITIES}
    extra = []
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in operations:
            if method in {"get", "post", "patch", "delete", "put"} and (method, path) not in covered:
                extra.append(f"{method.upper()} {path}")
    assert extra == []


def test_device_lists_include_power_for_the_api_and_mcp(client, hub):
    import json

    from wakehub.endpoints import add_plug
    from wakehub.hub import set_hub
    from wakehub.metrics import record

    set_hub(hub)
    created = client.post("/api/v1/devices", json={"name": "Metered", "mac": "AA:BB:CC:DD:EE:21", "host": "10.9.0.2"}).json()
    bare = client.post("/api/v1/devices", json={"name": "Plain", "mac": "AA:BB:CC:DD:EE:22", "host": "10.9.0.3"}).json()
    plug = add_plug(hub, {"name": "Desk lamp", "kind": "shelly", "host": "10.9.0.9", "device_id": created["id"]})
    record(hub, "plug", plug["id"], created["id"], [("power_w", 18.5, "W"), ("current_a", 0.16, "A"), ("energy_wh", 42, "Wh")])
    listed = {item["name"]: item for item in client.get("/api/v1/devices").json()}
    fetched = client.get(f"/api/v1/devices/{created['id']}").json()
    assert listed["Plain"]["power"]["metered"] is False
    assert "No metered source" in listed["Plain"]["power"]["message"]
    assert listed["Metered"]["power"]["watts"] == 18.5
    assert listed["Metered"]["power"]["source"]["label"] == "Smart plug Desk lamp"
    assert fetched["power"]["current_a"] == 0.16
    assert fetched["power"]["energy_wh"] == 42
    assert fetched["power"]["history"]
    server = build_server()
    result = asyncio.run(server.call_tool("get_device", {"device_id": created["id"]}))
    body = json.loads(result.content[0].text)
    assert body["power"]["watts"] == fetched["power"]["watts"]
    assert body["power"]["source"]["kind"] == "plug"
    listed_tool = asyncio.run(server.call_tool("list_devices", {}))
    rows = []
    for block in listed_tool.content:
        if not getattr(block, "text", None):
            continue
        parsed = json.loads(block.text)
        rows.extend(parsed if isinstance(parsed, list) else [parsed])
    assert {item["name"] for item in rows} >= {"Metered", "Plain"}
    assert all(item["power"]["metered"] is (item["name"] == "Metered") for item in rows)


def test_mcp_tool_names_match_the_registry():
    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    expected = {cap.mcp_tool for cap in CAPABILITIES}
    assert names == expected
    for tool in tools:
        assert tool.description
