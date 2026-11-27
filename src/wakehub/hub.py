"""Process state: database, cipher and the bearer token."""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
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
        self.lock = threading.RLock()
        self._in_transaction = 0
        self._after_commit: list = []
        self._background_stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._closed = False
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        self.db = connect(settings.data_dir / "wakehub.sqlite3")
        self.cipher = load_cipher(settings.config_dir, settings.secret_key)
        self.token = self._load_or_create_token()
        self._ensure_cors_default()
        self._abandon_running_scans()
        from wakehub.controls import fold_linked_controls

        fold_linked_controls(self)
        self._attempts: dict[str, list[float]] = {}
        self._attempt_lock = threading.Lock()

    @classmethod
    def open(cls, settings: Settings) -> Hub:
        return cls(settings)

    def track_background(self, thread: threading.Thread) -> None:
        self._workers.append(thread)

    def stopping(self) -> bool:
        return self._background_stop.is_set() or self._closed

    def stop_background(self) -> None:
        self._background_stop.set()

    def join_background(self, timeout: float = 5.0) -> None:
        self.stop_background()
        for thread in list(self._workers):
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout)

    def close(self) -> None:
        # Wait out workers before closing. sqlite can segfault if another thread is mid-query.
        self.join_background()
        with self.lock:
            if self._closed:
                return
            self._closed = True
            self.db.close()

    def _skip_locked(self) -> bool:
        if self._closed:
            return True
        # A worker that has been told to stop must not start another statement.
        return self._background_stop.is_set() and threading.current_thread() in self._workers

    def _load_or_create_token(self) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key = 'api_token'").fetchone()
        if row is not None:
            try:
                token = decrypt(self.cipher, row["value"])
                self._publish_token(token)
                return token
            except WakeHubError:
                # The key file was replaced. A token we cannot read is useless, so mint a new one.
                log.warning("stored API token could not be decrypted; generating a new token")
        token = secrets.token_urlsafe(32)
        self._write_setting("api_token", encrypt(self.cipher, token))
        self._publish_token(token)
        return token

    def _abandon_running_scans(self) -> None:
        # The scan thread dies with the process. A leftover running row would block every later scan.
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.write(
            "UPDATE scans SET status = 'error', message = ?, finished_at = ? WHERE status = 'running'",
            ("interrupted by restart", now),
        )

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
            if self._skip_locked():
                return default
            row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return row["value"]

    def cors_origins(self) -> list[str]:
        raw = self.setting("cors_origins")
        if raw is None:
            raw = ",".join(self.settings.cors_origins)
        return [part.strip() for part in raw.split(",") if part.strip()]

    def _publish_token(self, token: str) -> None:
        # The file is how an operator completes first-run setup. The log line is the same secret.
        path = self.settings.config_dir / "token"
        path.write_text(token + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        log.info("API token written to %s", path)
        log.info("Wake Hub API token: %s", token)

    def rotate_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._write_setting("api_token", encrypt(self.cipher, token))
        self.token = token
        self._publish_token(token)
        self.write("DELETE FROM ui_sessions")
        return token

    def note_attempt(self, key: str, *, ok: bool) -> None:
        now = time.monotonic()
        with self._attempt_lock:
            recent = [stamp for stamp in self._attempts.get(key, []) if now - stamp < 900]
            if not ok:
                recent.append(now)
            self._attempts[key] = [] if ok else recent

    def attempts_blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._attempt_lock:
            recent = [stamp for stamp in self._attempts.get(key, []) if now - stamp < 900]
            self._attempts[key] = recent
            return len(recent) >= 5

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        with self.lock:
            if self._skip_locked():
                return []
            return list(self.db.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        with self.lock:
            if self._skip_locked():
                return None
            return self.db.execute(sql, params).fetchone()

    def write(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.lock:
            if self._skip_locked():
                return 0
            cursor = self.db.execute(sql, params)
            if self._in_transaction == 0:
                self.db.commit()
            return int(cursor.lastrowid or 0)

    def write_many(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        with self.lock:
            if self._skip_locked():
                return
            for sql, params in statements:
                self.db.execute(sql, params)
            if self._in_transaction == 0:
                self.db.commit()

    def after_commit(self, callback) -> None:
        """Run callback after the open transaction commits. It must not assume hub.lock is held."""
        if self._in_transaction:
            self._after_commit.append(callback)
        else:
            callback()

    @contextmanager
    def transaction(self):
        """Hold every write until the block finishes, and undo them all if it raises.

        The lock covers the database work only. Callbacks registered with after_commit
        run after it is released, so a network read cannot stall other requests.
        """
        callbacks: list = []
        with self.lock:
            self._in_transaction += 1
            try:
                yield
                if self._in_transaction == 1:
                    self.db.commit()
                    callbacks = self._after_commit
                    self._after_commit = []
            except Exception:
                if self._in_transaction == 1:
                    self.db.rollback()
                    self._after_commit = []
                raise
            finally:
                self._in_transaction -= 1
        for callback in callbacks:
            callback()


def set_hub(hub: Hub) -> None:
    global _hub
    _hub = hub


def get_hub() -> Hub:
    if _hub is None:
        raise RuntimeError("Wake Hub is not initialized")
    return _hub
