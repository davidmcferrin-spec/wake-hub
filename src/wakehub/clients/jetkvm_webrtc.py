"""Open a JetKVM JSON-RPC data channel.

The device expects a WebRTC offer with a data channel named rpc. The answer
comes back on the signaling socket as base64 JSON. This was not exercised
against a physical JetKVM in CI.
"""

from __future__ import annotations

import asyncio
import json

from wakehub.clients.jetkvm import parse_rpc, rpc_request, signaling_offer
from wakehub.errors import UpstreamError


def rpc_call(base: str, cookie: str, method: str, params: dict | None, timeout: float = 12):
    try:
        return asyncio.run(_rpc_call(base, cookie, method, params, timeout))
    except UpstreamError:
        raise
    except (OSError, TimeoutError) as exc:
        raise UpstreamError(f"JetKVM WebRTC failed: {exc}") from exc


async def _rpc_call(base: str, cookie: str, method: str, params: dict | None, timeout: float):
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription
        import websockets
    except ImportError as exc:
        raise UpstreamError("JetKVM power control needs aiortc and websockets installed") from exc

    scheme = "wss" if base.startswith("https://") else "ws"
    host = base.split("://", 1)[1]
    url = f"{scheme}://{host}/webrtc/signaling/client"
    headers = {"Cookie": f"authToken={cookie}"} if cookie else None
    connection = RTCPeerConnection()
    channel = connection.createDataChannel("rpc")
    connection.addTransceiver("video", direction="recvonly")
    opened = asyncio.Event()
    result: asyncio.Future = asyncio.get_running_loop().create_future()

    @channel.on("open")
    def on_open() -> None:
        opened.set()

    @channel.on("message")
    def on_message(message) -> None:
        if result.done():
            return
        try:
            payload = parse_rpc(message if isinstance(message, str) else message.decode("utf-8"))
        except UpstreamError as exc:
            result.set_exception(exc)
            return
        if payload.get("id") == 1 and "result" in payload:
            result.set_result(payload.get("result"))

    try:
        async with websockets.connect(url, additional_headers=headers, open_timeout=timeout) as socket:
            await asyncio.wait_for(socket.recv(), timeout)
            offer = await connection.createOffer()
            await connection.setLocalDescription(offer)
            description = {"type": connection.localDescription.type, "sdp": connection.localDescription.sdp}
            await socket.send(json.dumps(signaling_offer(description)))

            async def read_signaling() -> None:
                from wakehub.clients.jetkvm import parse_signaling_answer

                while not result.done():
                    raw = await asyncio.wait_for(socket.recv(), timeout)
                    if raw in ("ping", "pong"):
                        continue
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "answer":
                        answer = parse_signaling_answer(message)
                        await connection.setRemoteDescription(
                            RTCSessionDescription(sdp=answer["sdp"], type=answer.get("type") or "answer")
                        )
                    elif kind == "new-ice-candidate" and message.get("data"):
                        from aiortc.sdp import candidate_from_sdp

                        data = message["data"]
                        if data.get("candidate"):
                            await connection.addIceCandidate(candidate_from_sdp(data["candidate"]))

            reader = asyncio.create_task(read_signaling())
            try:
                await asyncio.wait_for(opened.wait(), timeout)
                channel.send(rpc_request(method, params, 1))
                return await asyncio.wait_for(result, timeout)
            finally:
                reader.cancel()
    finally:
        await connection.close()
