"""TP-Link Kasa local control.

Speaks the legacy XOR protocol on TCP/UDP 9999 and the newer KLAP HTTP
handshake. Credentials are the TP-Link account email and password.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from wakehub.errors import UpstreamError, WakeHubError

XOR_KEY = 171
XOR_PORT = 9999


def xor_encrypt(payload: bytes) -> bytes:
    key = XOR_KEY
    out = bytearray()
    for byte in payload:
        key = key ^ byte
        out.append(key)
    return bytes(out)


def xor_decrypt(payload: bytes) -> bytes:
    key = XOR_KEY
    out = bytearray()
    for byte in payload:
        out.append(key ^ byte)
        key = byte
    return bytes(out)


def xor_tcp_frame(payload: bytes) -> bytes:
    encrypted = xor_encrypt(payload)
    return struct.pack(">I", len(encrypted)) + encrypted


def xor_tcp_unframe(buffer: bytes) -> bytes:
    if len(buffer) < 4:
        raise UpstreamError("Kasa TCP response was too short")
    length = struct.unpack(">I", buffer[:4])[0]
    encrypted = buffer[4 : 4 + length]
    if len(encrypted) != length:
        raise UpstreamError("Kasa TCP response was truncated")
    return xor_decrypt(encrypted)


def auth_hash_v1(username: str, password: str) -> bytes:
    user = hashlib.md5(username.encode("utf-8")).digest()
    secret = hashlib.md5(password.encode("utf-8")).digest()
    return hashlib.md5(user + secret).digest()


def auth_hash_v2(username: str, password: str) -> bytes:
    user = hashlib.sha1(username.encode("utf-8")).digest()
    secret = hashlib.sha1(password.encode("utf-8")).digest()
    return hashlib.sha256(user + secret).digest()


def handshake1_hash_v1(local_seed: bytes, remote_seed: bytes, auth_hash: bytes) -> bytes:
    # Older KLAP proves the login with the local seed and the auth hash.
    return hashlib.sha256(local_seed + auth_hash).digest()


def handshake2_hash_v1(local_seed: bytes, remote_seed: bytes, auth_hash: bytes) -> bytes:
    return hashlib.sha256(remote_seed + auth_hash).digest()


def handshake1_hash_v2(local_seed: bytes, remote_seed: bytes, auth_hash: bytes) -> bytes:
    return hashlib.sha256(local_seed + remote_seed + auth_hash).digest()


def handshake2_hash_v2(local_seed: bytes, remote_seed: bytes, auth_hash: bytes) -> bytes:
    return hashlib.sha256(remote_seed + local_seed + auth_hash).digest()


def handshake1_hash(local_seed: bytes, remote_seed: bytes, auth_hash: bytes) -> bytes:
    return handshake1_hash_v2(local_seed, remote_seed, auth_hash)


def handshake2_hash(local_seed: bytes, remote_seed: bytes, auth_hash: bytes) -> bytes:
    return handshake2_hash_v2(local_seed, remote_seed, auth_hash)


@dataclass
class KlapSession:
    key: bytes
    signature_key: bytes
    iv_prefix: bytes
    sequence: int

    @classmethod
    def derive(cls, local_seed: bytes, remote_seed: bytes, auth_hash: bytes) -> KlapSession:
        def digest(prefix: bytes) -> bytes:
            return hashlib.sha256(prefix + local_seed + remote_seed + auth_hash).digest()

        full_iv = digest(b"iv")
        sequence = int.from_bytes(full_iv[-4:], "big", signed=True)
        return cls(digest(b"lsk")[:16], digest(b"ldk")[:28], full_iv[:12], sequence)

    def encrypt(self, plaintext: bytes) -> tuple[int, bytes]:
        sequence = self.sequence
        iv = self.iv_prefix + sequence.to_bytes(4, "big", signed=True)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(iv)).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        signature = hashlib.sha256(self.signature_key + iv[12:] + ciphertext).digest()
        # The device decrypts with the seq in the URL, so advance only after the frame exists.
        self.sequence = _next_seq(sequence)
        return sequence, signature + ciphertext

    def decrypt(self, sequence: int, payload: bytes) -> bytes:
        if len(payload) < 32:
            raise UpstreamError("KLAP response was too short")
        signature, ciphertext = payload[:32], payload[32:]
        iv_tail = sequence.to_bytes(4, "big", signed=True)
        expected = hashlib.sha256(self.signature_key + iv_tail + ciphertext).digest()
        if not secrets.compare_digest(signature, expected):
            raise UpstreamError("KLAP response signature did not match")
        iv = self.iv_prefix + iv_tail
        decryptor = Cipher(algorithms.AES(self.key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        try:
            return unpadder.update(padded) + unpadder.finalize()
        except ValueError as exc:
            raise UpstreamError("KLAP response padding was invalid") from exc


def _next_seq(sequence: int) -> int:
    wrapped = (sequence + 1) & 0xFFFFFFFF
    if wrapped >= 0x80000000:
        wrapped -= 0x100000000
    return wrapped


def relay_command(on: bool) -> dict:
    return {"system": {"set_relay_state": {"state": 1 if on else 0}}}


def sysinfo_command() -> dict:
    return {"system": {"get_sysinfo": {}}}


def energy_command() -> dict:
    return {"emeter": {"get_realtime": {}}}


def parse_sysinfo(payload: dict) -> dict:
    info = ((payload.get("system") or {}).get("get_sysinfo")) or payload
    if not isinstance(info, dict):
        raise UpstreamError("Kasa sysinfo was not an object")
    error = info.get("err_code", payload.get("err_code", 0))
    if error not in (0, None):
        raise UpstreamError(f"Kasa returned error {error}")
    relay = info.get("relay_state")
    return {
        "on": None if relay is None else bool(relay),
        "model": info.get("model") or info.get("mic_type") or "",
        "alias": info.get("alias") or "",
        "mac": info.get("mac") or "",
        "device_id": info.get("deviceId") or info.get("device_id") or "",
        "raw": info,
    }


def parse_energy(payload: dict) -> dict:
    block = ((payload.get("emeter") or {}).get("get_realtime")) or {}
    if not isinstance(block, dict):
        return {}
    if block.get("err_code") not in (0, None):
        return {}
    # Legacy plugs report milliwatts, millivolts and milliamps.
    power = block.get("power_mw", block.get("power"))
    voltage = block.get("voltage_mv", block.get("voltage"))
    current = block.get("current_ma", block.get("current"))
    total = block.get("total_wh", block.get("total"))
    return {
        "power_w": None if power is None else (power / 1000 if "power_mw" in block else power),
        "voltage_v": None if voltage is None else (voltage / 1000 if "voltage_mv" in block else voltage),
        "current_a": None if current is None else (current / 1000 if "current_ma" in block else current),
        "energy_kwh": None if total is None else (total / 1000 if "total_wh" in block else total),
    }


class KasaClient:
    def __init__(self, host: str, email: str = "", password: str = "", *, protocol: str = "auto", port: int = 80, timeout: float = 5, http=None):
        if protocol not in {"auto", "xor", "klap"}:
            raise WakeHubError("Kasa protocol must be auto, xor, or klap")
        self.host = host
        self.email = email
        self.password = password
        self.protocol = protocol
        self.port = port
        self.timeout = timeout
        self._http = http
        self._session: KlapSession | None = None
        self._cookie = ""

    def status(self) -> dict:
        info = parse_sysinfo(self._call(sysinfo_command()))
        try:
            info.update({key: value for key, value in parse_energy(self._call(energy_command())).items() if value is not None})
        except UpstreamError:
            pass
        return info

    def set_on(self, on: bool) -> dict:
        self._call(relay_command(on))
        return {"on": on}

    def _call(self, command: dict) -> dict:
        if self.protocol == "xor":
            return self._xor(command)
        if self.protocol == "klap":
            return self._klap(command)
        try:
            return self._xor(command)
        except UpstreamError:
            return self._klap(command)

    def _xor(self, command: dict) -> dict:
        payload = json.dumps(command, separators=(",", ":")).encode("utf-8")
        frame = xor_tcp_frame(payload)
        try:
            with socket.create_connection((self.host, XOR_PORT), self.timeout) as sock:
                sock.sendall(frame)
                sock.settimeout(self.timeout)
                chunks = bytearray()
                while True:
                    piece = sock.recv(4096)
                    if not piece:
                        break
                    chunks.extend(piece)
                    if len(chunks) >= 4 and len(chunks) >= 4 + struct.unpack(">I", chunks[:4])[0]:
                        break
        except OSError as exc:
            raise UpstreamError(f"Kasa XOR connection failed: {exc}") from exc
        try:
            decoded = xor_tcp_unframe(bytes(chunks))
            return json.loads(decoded.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise UpstreamError("Kasa XOR response was not JSON") from exc

    def _klap(self, command: dict) -> dict:
        if self._session is None:
            self._handshake()
        assert self._session is not None
        sequence, body = self._session.encrypt(json.dumps(command, separators=(",", ":")).encode("utf-8"))
        status, payload, _cookie = self._post(f"/app/request?seq={sequence}", body)
        if status != 200:
            raise UpstreamError(f"KLAP request HTTP {status}")
        plain = self._session.decrypt(sequence, payload)
        try:
            return json.loads(plain.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise UpstreamError("KLAP response was not JSON") from exc

    def _handshake(self) -> None:
        local = secrets.token_bytes(16)
        status, data, cookie = self._post("/app/handshake1", local)
        if status != 200 or len(data) < 48:
            raise UpstreamError(f"KLAP handshake1 failed with HTTP {status}")
        remote, server_hash = data[:16], data[16:48]
        hashes = [auth_hash_v2(self.email, self.password), auth_hash_v1(self.email, self.password)]
        if self.email or self.password:
            hashes.extend([auth_hash_v2("", ""), auth_hash_v1("", "")])
        chosen = None
        confirm_hash = None
        for candidate in hashes:
            if secrets.compare_digest(handshake1_hash_v2(local, remote, candidate), server_hash):
                chosen = candidate
                confirm_hash = handshake2_hash_v2(local, remote, candidate)
                break
            if secrets.compare_digest(handshake1_hash_v1(local, remote, candidate), server_hash):
                chosen = candidate
                confirm_hash = handshake2_hash_v1(local, remote, candidate)
                break
        if chosen is None or confirm_hash is None:
            raise UpstreamError("KLAP credentials were rejected")
        confirm = confirm_hash
        self._cookie = cookie
        status, _body, cookie = self._post("/app/handshake2", confirm)
        if cookie:
            self._cookie = cookie
        if status != 200:
            raise UpstreamError(f"KLAP handshake2 failed with HTTP {status}")
        self._session = KlapSession.derive(local, remote, chosen)

    def _post(self, path: str, body: bytes) -> tuple[int, bytes, str]:
        if self._http is not None:
            return self._http(path, body, self._cookie)
        import httpx

        headers = {"Content-Type": "application/octet-stream"}
        if self._cookie:
            headers["Cookie"] = self._cookie
        url = f"http://{self.host}:{self.port}{path}"
        try:
            response = httpx.post(url, content=body, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"KLAP request failed: {exc}") from exc
        cookie = response.cookies.get("TP_SESSIONID", "")
        header = response.headers.get("set-cookie", "")
        if not cookie and "TP_SESSIONID=" in header:
            cookie = header.split("TP_SESSIONID=", 1)[1].split(";", 1)[0]
        return response.status_code, response.content, cookie
