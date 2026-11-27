"""Process state: database, cipher and the bearer token."""

from __future__ import annotations

import logging
import secrets
import threading
from typing import Any

from wakehub.config import Settings
from wakehub.crypto import decrypt, encrypt, load_cipher
from wakehub.db import connect
from wakehub.errors import WakeHubError

log = logging.getLogger("wakehub")

_hub: Hub | None = None


class Hub:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.Lock()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        self.db = connect(settings.data_dir / "wakehub.sqlite3")
        self.cipher = load_cipher(settings.config_dir, settings.secret_key)
        self.token = self._load_or_create_token()
        self._ensure_cors_default()

    @classmethod
    def open(cls, settings: Settings) -> Hub:
        return cls(settings)

    def close(self) -> None:
        self.db.close()

    def _load_or_create_token(self) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key = 'api_token'").fetchone()
        if row is not None:
            try:
                return decrypt(self.cipher, row["value"])
            except WakeHubError:
                # The key file was replaced. A token we cannot read is useless, so mint a new one.
                log.warning("stored API token could not be decrypted; generating a new token")
        token = secrets.token_urlsafe(32)
        self._write_setting("api_token", encrypt(self.cipher, token))
        return token

    def _ensure_cors_default(self) -> None:
        row = self.db.execute("SELECT value FROM settings WHERE key = 'cors_origins'").fetchone()
        if row is None:
            self._write_setting("cors_origins", ",".join(self.settings.cors_origins))

    def _write_setting(self, key: str, value: str) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.db.commit()

    def setting(self, key: str, default: str | None = None) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return row["value"]

    def cors_origins(self) -> list[str]:
        raw = self.setting("cors_origins", "*") or "*"
        return [part.strip() for part in raw.split(",") if part.strip()]

    def rotate_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._write_setting("api_token", encrypt(self.cipher, token))
        self.token = token
        return token

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        with self.lock:
            return list(self.db.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        with self.lock:
            return self.db.execute(sql, params).fetchone()

    def write(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.lock:
            cursor = self.db.execute(sql, params)
            self.db.commit()
            return int(cursor.lastrowid or 0)

    def write_many(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        with self.lock:
            for sql, params in statements:
                self.db.execute(sql, params)
            self.db.commit()


def set_hub(hub: Hub) -> None:
    global _hub
    _hub = hub


def get_hub() -> Hub:
    if _hub is None:
        raise RuntimeError("Wake Hub is not initialized")
    return _hub
