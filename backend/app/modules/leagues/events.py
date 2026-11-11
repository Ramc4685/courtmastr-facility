"""Events the leagues context emits (overview section 2, data model 2.20). Thin payloads: ids and the transition."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class ScheduleGenerated(Event):
    aggregate_type: ClassVar[str] = "schedule_run"
    type: Literal["leagues.schedule.generated"] = "leagues.schedule.generated"
    schedule_run_id: UUID
    location_id: UUID
    scheduled_count: int
    unschedulable_count: int


class _GameEvent(Event):
    aggregate_type: ClassVar[str] = "game"
    game_id: UUID
    competition_id: UUID
    location_id: UUID


class GameRescheduled(_GameEvent):
    type: Literal["leagues.game.rescheduled"] = "leagues.game.rescheduled"
    status: str


class GameCancelled(_GameEvent):
    type: Literal["leagues.game.cancelled"] = "leagues.game.cancelled"


class GameResultRecorded(_GameEvent):
    type: Literal["leagues.game.result_recorded"] = "leagues.game.result_recorded"


class StandingsUpdated(Event):
    aggregate_type: ClassVar[str] = "competition"
    type: Literal["leagues.standings.updated"] = "leagues.standings.updated"
    competition_id: UUID
    location_id: UUID
