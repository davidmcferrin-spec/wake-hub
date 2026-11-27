import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from wakehub.clients.amt import AmtClient
from wakehub.hub import set_hub
from wakehub.mcp_server import build_server


class _Reply(BaseHTTPRequestHandler):
    status_code = 401

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(self.status_code)
        if self.status_code == 401:
            self.send_header("WWW-Authenticate", 'Digest realm="AMT", qop="auth", nonce="nonce", opaque="opaque"')
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"no")

    def log_message(self, _format, *_args):
        return


def _serve(status_code):
    _Reply.status_code = status_code
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Reply)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _device(client, host, port):
    device = client.post(
        "/api/v1/devices",
        json={"name": "UNRAID", "mac": "02:00:00:00:00:91", "host": "10.9.1.1", "broadcast": "10.9.1.255"},
    ).json()
    client.post(
        "/api/v1/amt",
        json={"name": "UNRAID vPRO", "host": host, "port": port, "password": "wrong-secret", "device_id": device["id"]},
    )
    return device


def _no_packets(monkeypatch):
    sent = []
    monkeypatch.setattr("wakehub.inventory.send_magic_packet", lambda *_args, **_kwargs: sent.append(True))
    monkeypatch.setattr("wakehub.inventory.wait_until_reachable", lambda *_args, **_kwargs: (False, 0))
    return sent


def _mcp_wake(device_id):
    server = build_server()

    async def run():
        return await server.call_tool("wake_device", {"device_id": device_id, "method": "auto"})

    import asyncio

    return asyncio.run(run())


@pytest.mark.parametrize("status_code,message", [(401, "digest credentials"), (500, "AMT HTTP 500")])
def test_amt_http_errors_do_not_send_wol(client, hub, monkeypatch, status_code, message):
    set_hub(hub)
    server = _serve(status_code)
    sent = _no_packets(monkeypatch)
    try:
        device = _device(client, "127.0.0.1", server.server_address[1])
        wake = client.post(f"/api/v1/devices/{device['id']}/wake", json={"method": "auto"})
        power = client.post(f"/api/v1/devices/{device['id']}/power", json={"action": "on", "method": "auto"})
        assert wake.status_code == 502, wake.text
        assert power.status_code == 502, power.text
        assert message in wake.json()["error"]["message"]
        assert message in power.json()["error"]["message"]
        with pytest.raises(ToolError, match=message):
            _mcp_wake(device["id"])
        assert sent == []
    finally:
        server.shutdown()


def test_connection_refused_still_falls_back_to_wol(client, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    sent = _no_packets(monkeypatch)
    device = _device(client, "127.0.0.1", port)
    woken = client.post(f"/api/v1/devices/{device['id']}/wake", json={"method": "auto"})
    assert woken.status_code == 200, woken.text
    assert woken.json()["reason"] == "AMT unreachable, sent WOL"
    assert woken.json()["name"] == "UNRAID"
    assert sent == [True]


def test_timeout_still_falls_back_to_wol(client, monkeypatch):
    class Quick(AmtClient):
        def __init__(self, *args, **kwargs):
            kwargs["timeout"] = 0.3
            super().__init__(*args, **kwargs)

    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]

    def hold():
        try:
            conn, _addr = held.accept()
            time.sleep(1)
            conn.close()
        except OSError:
            return

    threading.Thread(target=hold, daemon=True).start()
    monkeypatch.setattr("wakehub.endpoints.AmtClient", Quick)
    sent = _no_packets(monkeypatch)
    try:
        device = _device(client, "127.0.0.1", port)
        woken = client.post(f"/api/v1/devices/{device['id']}/wake", json={"method": "auto"})
        assert woken.status_code == 200, woken.text
        assert woken.json()["reason"] == "AMT unreachable, sent WOL"
        assert sent == [True]
    finally:
        held.close()
