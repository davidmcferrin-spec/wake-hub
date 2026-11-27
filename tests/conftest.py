import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from wakehub.api import create_app
from wakehub.clients.synaccess import SynaccessClient
from wakehub.config import Settings
from wakehub.hub import Hub


@pytest.fixture
def hub(tmp_path):
    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        host="127.0.0.1",
        port=0,
        secret_key="test-secret",
        cors_origins=(),
    )
    opened = Hub.open(settings)
    yield opened
    opened.stop_background()
    opened.join_background(timeout=5)
    opened.close()


@pytest.fixture(autouse=True)
def pdu_names_offline(monkeypatch):
    def offline(self, *_args, **_kwargs):
        from wakehub.errors import UpstreamError

        raise UpstreamError("the PDU did not return outlet names")

    original_status = SynaccessClient.status

    def status(self, names=None):
        from wakehub.errors import UpstreamError

        # Unit tests pass their own HTTP client. Live adds must not wait on the LAN.
        if not getattr(self, "_owns", True):
            return original_status(self, names)
        raise UpstreamError("the PDU did not return outlet names")

    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.read_outlet_names", offline)
    monkeypatch.setattr("wakehub.clients.synaccess.SynaccessClient.status", status)


@pytest.fixture
def client(hub):
    app = create_app(hub)
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {hub.token}"
        yield test_client


@pytest.fixture
def live_server(hub):
    app = create_app(hub)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    def runner():
        server.run()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError("server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
