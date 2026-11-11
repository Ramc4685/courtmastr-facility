"""VideoMeeting port (ADR 0012 section 5). v1 ships the simulated adapter only; `zoom` replaces it behind this
interface once a Zoom app is approved. Callers never email the join URL (members go through our redirect)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Meeting:
    external_meeting_id: str
    join_url: str
    host_start_url: str


class VideoMeeting(Protocol):
    name: str
    simulated: bool

    def create_meeting(self, *, topic: str, starts_at: datetime, minutes: int, host_user_id: str) -> Meeting: ...

    def update_meeting(self, external_meeting_id: str, *, starts_at: datetime, minutes: int) -> None: ...

    def delete_meeting(self, external_meeting_id: str) -> None: ...
