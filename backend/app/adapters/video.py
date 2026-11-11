"""VideoMeeting adapters (app.ports.video_meeting). Only the simulated one in v1 (ADR 0012 section 5)."""

from datetime import datetime
from uuid import uuid4

from app.ports.video_meeting import Meeting


class FakeVideo:
    """Simulated Zoom: returns well-formed meeting ids and URLs; integrations logs every call."""

    name, simulated = "fake_video", True

    def create_meeting(self, *, topic: str, starts_at: datetime, minutes: int, host_user_id: str) -> Meeting:
        meeting_id = uuid4().hex[:11]
        return Meeting(meeting_id, f"https://video.invalid/j/{meeting_id}", f"https://video.invalid/s/{meeting_id}")

    def update_meeting(self, external_meeting_id: str, *, starts_at: datetime, minutes: int) -> None:
        return None

    def delete_meeting(self, external_meeting_id: str) -> None:
        return None
