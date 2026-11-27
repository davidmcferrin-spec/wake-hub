"""Start the web UI, REST API and MCP server on one port."""

import logging

import uvicorn

from wakehub.api import create_app
from wakehub.config import Settings
from wakehub.hub import Hub


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    hub = Hub.open(settings)
    app = create_app(hub)
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    finally:
        hub.stop_background()
        hub.join_background(timeout=5)
        hub.close()


if __name__ == "__main__":
    main()
