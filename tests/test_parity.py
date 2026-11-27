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


def test_mcp_tool_names_match_the_registry():
    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    expected = {cap.mcp_tool for cap in CAPABILITIES}
    assert names == expected
    for tool in tools:
        assert tool.description
