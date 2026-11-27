# Wake Hub

Self-hosted power control for a home LAN. One process serves a web UI, a versioned REST API and an MCP server. This revision covers the device inventory and Wake-on-LAN. Synaccess PDUs, Intel AMT, JetKVM, Shelly, Kasa and CyberPower UPS cards are the next change on top of this service.

The web UI can stay open on the LAN. The API and MCP always require a bearer token.

## Run with Docker

Host networking is required. A bridge network does not deliver directed broadcasts to the LAN, and later ARP discovery needs to see the host's subnet.

```bash
mkdir -p /mnt/user/appdata/wake-hub/config /mnt/user/appdata/wake-hub/data
docker compose up -d --build
```

On a machine that is not Unraid, create those directories (or change the bind mounts in `docker-compose.yml`) before starting. The UI is at `http://<host>:8765/`. The first start writes an API token and, if `WAKEHUB_SECRET_KEY` is unset, an encryption key at `/config/secret.key`.

`PUID` and `PGID` own the files on the volumes. Unraid should use `99` and `100`. `NET_RAW` lets the unprivileged process send ICMP probes. If you would rather not grant that capability, set each device's reachability to a TCP port.

Environment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8765` | Web UI, REST and MCP listen on this port |
| `PUID` / `PGID` | `99` / `100` | Volume owner |
| `WAKEHUB_SECRET_KEY` | generated file | Encrypts the API token and SecureOn passwords |
| `WAKEHUB_CORS` | `*` | Browser origins allowed to call the API |

Config lives in `/config`. The SQLite database lives in `/data`.

### Unraid

**Compose Manager.** Copy `docker-compose.yml` into a stack. Keep `network_mode: host`. Appdata paths are `/mnt/user/appdata/wake-hub/config` and `/mnt/user/appdata/wake-hub/data`. Start the stack, then open `http://<tower>:8765/`.

**Community Applications template.** The template is `unraid/wake-hub.xml`. Point the two path mappings at the same appdata folders, leave the network on host, and keep `NET_RAW`. The web UI port variable is `8765`.

**Update.** Pull the image and recreate the container. Compose Manager: update the stack. Template installs: check for updates in Community Applications, or `docker pull ghcr.io/davidmcferrin-spec/wake-hub:latest` and restart. The database and key stay on the appdata share.

Images are published to GHCR for `linux/amd64` and `linux/arm64` by `.github/workflows/image.yml`.

## Web UI

The device list shows reachability, Wake and Power on. Add or edit a device from the same page. History records every wake with its source (`ui`, `api` or `mcp`). Settings shows the bearer token, rotates it, and can require a password before the UI will load. The password does not replace the bearer token.

Only enabled devices can be woken. Off, cycle, reboot and shutdown require `confirm: true` once a method supports them. Wake-on-LAN itself only sends a magic packet (`action: on`). `wake_strategy=power_then_wol` is stored now and turns a linked plug or outlet on before the packet once those methods are configured.

## REST API

OpenAPI is at `/openapi.json`. Interactive docs are at `/docs`.

All `/api/v1` routes except UI login and the UI session require:

```
Authorization: Bearer <token>
```

A missing or wrong token is `401`. Destructive actions without `confirm: true` are `409` with code `confirmation_required`.

## MCP

Streamable HTTP at `/mcp`. Send the same bearer token. Without it the endpoint returns `401`.

Tools in this revision: `list_devices`, `get_device`, `add_device`, `update_device`, `remove_device`, `set_device_enabled`, `wake_device`, `power_action`, `device_status`, `list_status`, `list_actions`, `get_settings`, `update_settings`, `get_access_token`, `rotate_token`, `ui_login`.

`wake_device` sends the magic packet and reports whether the host answered. `power_action` with `off`, `cycle`, `reboot` or `shutdown` requires `confirm=true`.

## Integrating from another service

Life-Dashboard, or any other service, should call the versioned REST API. Paths under `/api/v1` stay stable. A breaking change will move to `/api/v2`.

Base URL: `http://<unraid-host>:8765`

Auth: `Authorization: Bearer <token>`

Copy the token from the Wake Hub settings page. Do not expect the API to hand the token to an anonymous caller. When the UI has no password, a browser on the LAN can read it from `GET /api/v1/ui/session`. Server-side callers should store the token themselves.

List devices:

```bash
curl -s \
  -H "Authorization: Bearer $WAKEHUB_TOKEN" \
  http://192.168.1.10:8765/api/v1/devices
```

Wake one device and wait until it answers, or until the device timeout:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $WAKEHUB_TOKEN" \
  -H "Content-Type: application/json" \
  http://192.168.1.10:8765/api/v1/devices/1/wake
```

The response includes `sent`, `reachable` and `elapsed_s`. `reachable` is `null` when the device has no host to probe.

CORS: set `WAKEHUB_CORS` or the settings page to the origin of a browser app, for example `http://192.168.1.10:8080`. Use `*` to allow any origin. Server-side calls do not use CORS.

The same token works for MCP if Life-Dashboard prefers tools over REST:

```
POST http://192.168.1.10:8765/mcp
Authorization: Bearer $WAKEHUB_TOKEN
```

Tools to call: `list_devices`, then `wake_device` with `device_id`.

Stored secrets (SecureOn, and later PDU, AMT, JetKVM, plug and UPS passwords) are encrypted with `WAKEHUB_SECRET_KEY` or `/config/secret.key` and are never returned by the API or MCP.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q --tb=line
WAKEHUB_CONFIG_DIR=./config WAKEHUB_DATA_DIR=./data .venv/bin/python -m wakehub.main
```

`ping` must be on `PATH` for ICMP probes (`iputils-ping`).

## What this revision does not verify on hardware

Magic packets are checked with a local UDP listener. Reachability is checked against `127.0.0.1`. A physical NIC, a sleeping desktop, and a real SecureOn NIC were not exercised here.
