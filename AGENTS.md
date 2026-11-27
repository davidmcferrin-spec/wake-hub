# Wake Hub

One process serves the web UI, the REST API (`/api/v1`) and MCP (`/mcp`).

- `src/wakehub/main.py` starts uvicorn.
- `src/wakehub/hub.py` owns SQLite, the encryption key and the bearer token.
- `src/wakehub/inventory.py` is the device, wake, action-log and settings service.
- `src/wakehub/wol.py` builds magic packets and probes ICMP or TCP.
- `src/wakehub/api.py` is the REST API and mounts MCP.
- `src/wakehub/mcp_server.py` registers MCP tools that call the same service.
- `src/wakehub/capabilities.py` is the parity list. Tests fail if a row is missing from the API, the MCP tool list, or the UI.
- `src/wakehub/web/static` is the browser UI.
- `/config` holds `secret.key`. `/data/wakehub.sqlite3` is the database.

Run tests with `pytest -q`. Install with `pip install -e ".[dev]"`.
