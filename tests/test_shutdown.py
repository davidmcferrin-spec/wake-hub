import threading
import time

from fastapi.testclient import TestClient

from wakehub.api import create_app
from wakehub.config import Settings
from wakehub.hub import Hub
from wakehub.scan import start_scan


def _settings(path):
    return Settings(
        config_dir=path / "config",
        data_dir=path / "data",
        host="127.0.0.1",
        port=0,
        secret_key="test-secret",
        cors_origins=(),
    )


def test_metrics_thread_can_be_started_and_stopped_repeatedly(tmp_path):
    for index in range(50):
        hub = Hub.open(_settings(tmp_path / str(index)))
        app = create_app(hub)
        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200
        hub.stop_background()
        hub.join_background(timeout=2)
        hub.close()
        hub.close()
    alive = [thread.name for thread in threading.enumerate() if thread.name == "wakehub-metrics" and thread.is_alive()]
    assert alive == []


def test_a_scan_thread_does_not_touch_the_database_after_close(tmp_path, capsys):
    entered = threading.Event()
    release = threading.Event()

    def discover(_cidr, progress):
        entered.set()
        release.wait(3)
        progress(1, 1)
        return [{"ip": "10.0.0.2", "mac": None, "hostname": "", "vendor": "", "kinds": [], "detail": {}}]

    hub = Hub.open(_settings(tmp_path))
    start_scan(hub, "10.0.0.0/30", discover)
    assert entered.wait(2)
    threading.Thread(target=lambda: (time.sleep(0.15), release.set()), daemon=True).start()
    hub.stop_background()
    hub.join_background(timeout=2)
    hub.close()
    hub.close()
    time.sleep(0.2)
    captured = capsys.readouterr()
    assert "sqlite" not in captured.err.lower()
    assert "Exception ignored" not in captured.err
