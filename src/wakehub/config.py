"""Process configuration. Paths default to the Docker volume mounts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    data_dir: Path
    host: str
    port: int
    secret_key: str | None
    cors_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> Settings:
        # Inside the image these are the volumes. Outside Docker, keep state in the work tree.
        in_docker = Path("/config").is_dir() and os.environ.get("WAKEHUB_CONFIG_DIR") is None and Path("/.dockerenv").exists()
        config_default = "/config" if in_docker else "config"
        data_default = "/data" if in_docker else "data"
        raw_cors = os.environ.get("WAKEHUB_CORS", "*")
        origins = tuple(part.strip() for part in raw_cors.split(",") if part.strip()) or ("*",)
        secret = os.environ.get("WAKEHUB_SECRET_KEY") or None
        return cls(
            config_dir=_path("WAKEHUB_CONFIG_DIR", config_default),
            data_dir=_path("WAKEHUB_DATA_DIR", data_default),
            host=os.environ.get("WAKEHUB_HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", os.environ.get("WAKEHUB_PORT", "8765"))),
            secret_key=secret,
            cors_origins=origins,
        )
