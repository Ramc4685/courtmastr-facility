"""UUIDv7 (overview 3.5): time-ordered ids, so `id` doubles as the default sort and pagination tiebreaker."""

import os
import time
from uuid import UUID


def new_id() -> UUID:
    raw = bytearray((time.time_ns() // 1_000_000).to_bytes(6, "big") + os.urandom(10))
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # RFC 4122 variant
    return UUID(bytes=bytes(raw))
