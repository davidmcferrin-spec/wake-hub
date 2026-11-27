import socket

from wakehub.wol import build_magic_packet, parse_secureon, send_magic_packet


def test_magic_packet_repeats_the_mac_sixteen_times():
    mac = "01:23:45:67:89:AB"
    packet = build_magic_packet(mac)
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("0123456789AB") * 16
    assert len(packet) == 6 + 16 * 6


def test_secureon_password_is_appended():
    packet = build_magic_packet("01:23:45:67:89:AB", parse_secureon("secret"))
    assert packet.endswith(b"secret")
    assert build_magic_packet("01:23:45:67:89:AB", parse_secureon("736563726574")).endswith(b"secret")


def test_udp_listener_receives_the_magic_packet():
    packet = build_magic_packet("AA:BB:CC:DD:EE:FF")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        send_magic_packet(packet, "127.0.0.1", port)
        sock.settimeout(2)
        data, _addr = sock.recvfrom(256)
    finally:
        sock.close()
    assert data == packet
