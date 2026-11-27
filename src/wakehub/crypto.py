"""Encrypt credentials at rest. The key never leaves /config or the env var."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from wakehub.errors import WakeHubError


def _fernet_from_secret(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def load_cipher(config_dir: Path, secret: str | None) -> Fernet:
    config_dir.mkdir(parents=True, exist_ok=True)
    if secret:
        return _fernet_from_secret(secret)
    key_path = config_dir / "secret.key"
    if key_path.exists():
        raw = key_path.read_text(encoding="utf-8").strip()
        if not raw:
            raise WakeHubError("encryption key file is empty", code="key_unreadable")
        try:
            return Fernet(raw.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise WakeHubError("encryption key file is not a Fernet key", code="key_unreadable") from exc
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    os.chmod(key_path, 0o600)
    return Fernet(key)


def encrypt(cipher: Fernet, value: str) -> str:
    return cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(cipher: Fernet, token: str) -> str:
    try:
        return cipher.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise WakeHubError("stored secret could not be decrypted", code="decrypt_failed") from exc
