"""VideoMeeting port (ADR 0012 section 5): `fake_video` (simulated) and `zoom` (a tenant's Server-to-Server
OAuth app). Callers never email or list the join URL: members go through the join route."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Meeting:
    external_meeting_id: str
    join_url: str
    host_start_url: str
    passcode: str | None = None


class VideoMeeting(Protocol):
    name: str
    simulated: bool

    def check_account(self) -> None:
        """Raises unless the credentials really open the account they name."""
        ...

    def create_meeting(self, *, topic: str, starts_at: datetime, minutes: int, host_user_id: str) -> Meeting: ...

    def update_meeting(self, external_meeting_id: str, *, starts_at: datetime, minutes: int) -> None: ...

    def delete_meeting(self, external_meeting_id: str) -> None: ...


_adapter: VideoMeeting | None = None


def configure(adapter: VideoMeeting) -> None:
    global _adapter
    _adapter = adapter


def get() -> VideoMeeting:
    if _adapter is None:
        raise RuntimeError("video meeting adapter not configured; call bootstrap()")
    return _adapter
