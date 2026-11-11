"""Scanner adapters: a no-op for development and tests, and ClamAV's clamd over TCP (the INSTREAM command)."""

import socket
import struct

_CHUNK = 64 * 1024


class NoopScanner:
    def scan(self, data: bytes) -> None:
        return None


class ClamdScanner:
    def __init__(self, host: str, port: int, timeout: float = 30.0) -> None:
        self.address, self.timeout = (host, port), timeout

    def scan(self, data: bytes) -> str | None:
        with socket.create_connection(self.address, timeout=self.timeout) as conn:
            conn.sendall(b"zINSTREAM\0")
            for start in range(0, len(data), _CHUNK):
                chunk = data[start : start + _CHUNK]
                conn.sendall(struct.pack("!L", len(chunk)) + chunk)
            conn.sendall(struct.pack("!L", 0))
            reply = b""
            while not reply.endswith(b"\0") and (part := conn.recv(4096)):
                reply += part
        answer = reply.rstrip(b"\0").decode(errors="replace").strip()  # "stream: OK" | "stream: <name> FOUND"
        if answer.endswith(" FOUND"):
            return answer.removeprefix("stream:").removesuffix(" FOUND").strip()
        if answer != "stream: OK":
            raise RuntimeError(f"clamd scan failed: {answer}")  # size limit, engine error: fail closed
        return None
