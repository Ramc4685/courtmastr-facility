"""VideoMeeting adapters (app.ports.video_meeting): the simulated one, and Zoom through a tenant's own
Server-to-Server OAuth app (ADR 0012 section 5). Zoom has never been called live in this build: no Zoom app
exists, so tests drive `ZoomVideo` through httpx.MockTransport only (docs/status/phase15-api.md)."""

import base64
import time
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.ports.video_meeting import Meeting


class FakeVideo:
    """Simulated Zoom: returns well-formed meeting ids and URLs; integrations logs every call."""

    name, simulated = "fake_video", True

    def check_account(self) -> None:
        return None

    def create_meeting(self, *, topic: str, starts_at: datetime, minutes: int, host_user_id: str) -> Meeting:
        meeting_id = uuid4().hex[:11]
        return Meeting(meeting_id, f"https://video.invalid/j/{meeting_id}", f"https://video.invalid/s/{meeting_id}")

    def update_meeting(self, external_meeting_id: str, *, starts_at: datetime, minutes: int) -> None:
        return None

    def delete_meeting(self, external_meeting_id: str) -> None:
        return None


class ZoomVideo:
    """Zoom REST v2 with a Server-to-Server OAuth token (`account_credentials` grant). The token request names the
    account, so a token is proof the credentials belong to it. Meetings get the waiting room (ADR 0012 section 5:
    the host has the last word) and are scheduled meetings (type 2) in UTC."""

    name, simulated = "zoom", False
    TOKEN_URL = "https://zoom.us/oauth/token"
    API = "https://api.zoom.us/v2"

    def __init__(self, *, account_id: str, client_id: str, client_secret: str, client: httpx.Client | None = None):
        self.account_id = account_id
        self.client = client or httpx.Client(timeout=30)
        self.basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._token: tuple[str, float] | None = None

    def _bearer(self) -> dict:
        if self._token is None or self._token[1] - time.time() < 60:
            response = self.client.post(
                self.TOKEN_URL,
                params={"grant_type": "account_credentials", "account_id": self.account_id},
                headers={"Authorization": f"Basic {self.basic}"},
            )
            response.raise_for_status()
            body = response.json()
            self._token = (body["access_token"], time.time() + int(body["expires_in"]))
        return {"Authorization": f"Bearer {self._token[0]}"}

    def check_account(self) -> None:
        """Raises unless the credentials obtain a token for `account_id`."""
        self._bearer()

    @staticmethod
    def _when(starts_at: datetime) -> str:
        return starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def create_meeting(self, *, topic: str, starts_at: datetime, minutes: int, host_user_id: str) -> Meeting:
        body = {"topic": topic[:200], "type": 2, "start_time": self._when(starts_at), "timezone": "UTC",
                "duration": minutes, "settings": {"waiting_room": True, "join_before_host": False}}  # fmt: skip
        response = self.client.post(f"{self.API}/users/{host_user_id}/meetings", json=body, headers=self._bearer())
        response.raise_for_status()
        made = response.json()
        return Meeting(str(made["id"]), made["join_url"], made["start_url"], made.get("password") or None)

    def update_meeting(self, external_meeting_id: str, *, starts_at: datetime, minutes: int) -> None:
        body = {"start_time": self._when(starts_at), "timezone": "UTC", "duration": minutes}
        self.client.patch(
            f"{self.API}/meetings/{external_meeting_id}", json=body, headers=self._bearer()
        ).raise_for_status()

    def delete_meeting(self, external_meeting_id: str) -> None:
        response = self.client.delete(f"{self.API}/meetings/{external_meeting_id}", headers=self._bearer())
        if response.status_code != 404:  # already gone at Zoom is the outcome we wanted
            response.raise_for_status()
