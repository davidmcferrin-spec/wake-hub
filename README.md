# Wake Hub

Self-hosted power control for a home LAN. One process serves a web UI, a versioned REST API and an MCP server, all on the same port. It can wake a machine, switch a Synaccess outlet or a smart plug, drive Intel AMT and JetKVM power buttons, and read or command a CyberPower UPS card.

The web UI requires a password. The API and MCP always require a bearer token. Stored passwords are encrypted and are never returned.

## Run with Docker

Host networking is required. A bridge network does not deliver directed broadcasts, and ARP discovery cannot see the LAN from a bridge.

```bash
mkdir -p /mnt/user/appdata/wake-hub/config /mnt/user/appdata/wake-hub/data
docker compose up -d --build
```

On a machine that is not Unraid, create those directories or change the bind mounts. The UI is at `http://<host>:8765/`. The first start writes an API token and, if `WAKEHUB_SECRET_KEY` is unset, an encryption key at `/config/secret.key`.

`PUID` and `PGID` own the volume files. Unraid should use `99` and `100`. `NET_RAW` lets the unprivileged process send ICMP probes. A device can instead be probed on a TCP port, which does not need that capability.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8765` | Web UI, REST and MCP |
| `PUID` / `PGID` | `99` / `100` | Volume owner |
| `WAKEHUB_SECRET_KEY` | generated file | Encrypts the API token and device passwords |
| `WAKEHUB_CORS` | empty | Browser origins allowed to call the API. Empty blocks cross-origin calls |

Config lives in `/config`. SQLite lives in `/data`.

### Unraid

**Compose Manager.** Use `docker-compose.yml` as a stack. Keep `network_mode: host`. Appdata is `/mnt/user/appdata/wake-hub/config` and `/mnt/user/appdata/wake-hub/data`.

**Community Applications.** The template is `unraid/wake-hub.xml`. Use the same appdata paths, host networking, and `NET_RAW`. The port variable is `8765`.

**Update.** Pull `ghcr.io/davidmcferrin-spec/wake-hub:latest` and recreate the container. The database and key stay on the appdata share. Images are built for `linux/amd64` and `linux/arm64` by `.github/workflows/image.yml`. GitHub Container Registry packages are private by default. Either make the package public or run `docker login ghcr.io` on the Unraid host before the pull.

## What you can control

- **Inventory.** Name, MAC, host, broadcast, WOL port, optional SecureOn password, notes, tags, enabled flag, and one or more power methods. Disabled devices are listed but cannot be acted on.
- **Wake-on-LAN.** Magic packet to a directed broadcast on port 9 or 7, then ICMP or a TCP port until the host answers or the timeout ends. `wake_strategy=power_then_wol` turns a linked plug or PDU outlet on before the packet.
- **Synaccess netBooter.** Add by IP and credentials. List outlets, switch one on, off or reboot. The NP-1601DU reports inlet bank current, not per-outlet current.
- **Intel AMT / vPro.** Digest auth on port 16992 or 16993. TLS can allow that device's self-signed certificate. Read power state and request on, off, power cycle, reset, or graceful shutdown through WS-Management.
- **JetKVM.** Local password or no password. Reachability, ATX short press, long press, reset, DC on/off when that extension is present, and a console URL that opens in a new tab.
- **Shelly Plug US Gen4.** Gen2 RPC (`Switch.GetStatus`, `Switch.Set`, `Switch.Toggle`) with optional digest auth, plus power, voltage and energy when the plug reports them.
- **Kasa (EP10, EP25, KP125M and the same family).** Legacy XOR on port 9999, and KLAP on current firmware using the TP-Link account email and password. Energy is read on models that report it.
- **CyberPower RCCARD100.** SNMP v1, v2c or v3. Status, on line or on battery, capacity, runtime, input and output voltage, load, current and watts. Shutdown, reboot, turn off (immediate or delayed), battery test, and outlet-bank control. The UI warns before those commands.
- **Discovery.** Ping and ARP sweep of a CIDR (the host subnet by default), plus reverse DNS, MAC vendor from the bundled IEEE OUI list, and probes for AMT, Synaccess, JetKVM, Shelly, Kasa and CyberPower. Scans run in the background. Every type can also be added by hand with an IP.
- **Telemetry.** Bank current, plug power and energy, and UPS load and voltages are polled into SQLite. JetKVM DC voltage, current and watts are polled only when that endpoint is set to the DC extension and its metrics toggle is on, because a poll opens a WebRTC session and can take over an open console. The UI shows the latest values and a small chart. Retention and the poll interval are settings.

## REST API

OpenAPI: `/openapi.json`. Docs: `/docs`.

```
Authorization: Bearer <token>
```

A missing or wrong token is `401`. `off`, `cycle`, `reboot`, `shutdown`, outlet off, JetKVM force-off and reset, and the destructive UPS commands are `409` with code `confirmation_required` until the body sets `confirm` to true.

## MCP

Streamable HTTP at `/mcp`, same bearer token. Without the token the endpoint is `401`.

Tools: `list_devices`, `get_device`, `add_device`, `update_device`, `remove_device`, `set_device_enabled`, `wake_device`, `power_action`, `device_status`, `list_status`, `list_actions`, `get_settings`, `update_settings`, `get_access_token`, `rotate_token`, `ui_login`, `ui_setup`, `get_ui_session`, `list_pdus`, `add_pdu`, `update_pdu`, `remove_pdu`, `list_pdu_outlets`, `set_pdu_outlet`, `list_amt`, `add_amt`, `update_amt`, `remove_amt`, `amt_power_state`, `list_jetkvm`, `add_jetkvm`, `update_jetkvm`, `remove_jetkvm`, `jetkvm_status`, `jetkvm_power`, `jetkvm_console`, `list_plugs`, `add_plug`, `update_plug`, `remove_plug`, `plug_status`, `plug_power`, `list_ups`, `add_ups`, `update_ups`, `remove_ups`, `ups_status`, `ups_action`, `scan_subnet`, `list_scans`, `scan_results`, `add_from_scan`, `device_metrics`, `list_metrics`.

`tests/test_parity.py` fails if any of these is missing from the OpenAPI document, the MCP tool list, or a `data-cap` control in the UI.

## Integrating from another service

Life-Dashboard, or any other LAN service, should call the versioned REST API. Paths under `/api/v1` stay stable. A breaking change will move to `/api/v2`.

Base URL: `http://<unraid-host>:8765`

Auth: `Authorization: Bearer <token>`

The API token is printed in the container log and written to `/config/token` on startup. The web UI requires a password. On first run, enter that token plus a new password of at least 8 characters. After you sign in, Settings can show the token. `GET /api/v1/ui/session` does not return the token unless the browser already has a valid session cookie. Server-side callers should store the token themselves. Do not send PDU, AMT, JetKVM, plug or UPS passwords back out of Wake Hub; those endpoints never return them.

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

CORS defaults to empty, so a web page on another origin cannot call the API. Set `WAKEHUB_CORS`, or the settings page, to the origin of a browser app such as `http://192.168.1.10:8080`. Use `*` only when you intend to allow any origin. Server-side calls do not use CORS.

The same token works for MCP:

```
POST http://192.168.1.10:8765/mcp
Authorization: Bearer $WAKEHUB_TOKEN
```

Call `list_devices`, then `wake_device` with the `device_id`.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q --tb=line
WAKEHUB_CONFIG_DIR=./config WAKEHUB_DATA_DIR=./data .venv/bin/python -m wakehub.main
```

`ping` (`iputils-ping`) is required for ICMP probes and for the discovery sweep.

## Not verified on hardware

CI and the local tests build magic packets and catch them with a UDP listener, parse recorded Synaccess, AMT, JetKVM, Shelly, Kasa and CyberPower fixtures, and scan `127.0.0.1/32`. They do not talk to a sleeping PC, an NP-1601DU, an AMT firmware, a JetKVM, a Shelly or Kasa plug, or an RCCARD100.

In particular, without those devices it is not confirmed that:

- a directed broadcast crosses the Unraid host's switch and that a NIC with SecureOn accepts the password bytes
- an NP-1601DU's live `$A5` string matches the bank-current layout used here (the parser follows Synaccess's published format)
- an AMT stack accepts the WS-Management body and digest challenge this client sends
- a JetKVM completes the WebRTC offer and answers `getATXState` / `setATXPowerAction` / `setDCPowerState` (the JSON-RPC and signaling bytes are covered by fixtures; the live data channel is not). DC volts, amps and watts are collected only after the endpoint is set to the DC extension and metrics polling is turned on for that device. A poll opens a WebRTC session, which can take the console away from someone who already has it open. That takeover was not checked on hardware
- a current Kasa firmware accepts this KLAP handshake (the hash and AES framing are covered by test vectors; no plug was attached)
- an RCCARD100 reports runtime as TimeTicks and accepts the graceful-delay SET (the client follows the CPS-MIB; the card was not queried)
- SNMP v3 auth and privacy on that card match the protocols selected in the form
