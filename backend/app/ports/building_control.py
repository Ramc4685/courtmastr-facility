"""Building control port (CHK-15, CHK-16): door locks and court lights, vendor-neutral.

`device_ref` and `zone_ref` are the addresses the installer gives the controller (a door id, a relay channel);
we never interpret them. Calls are synchronous and must time out quickly (seconds): the remote unlock runs in a
request someone is standing at the door for, and the lights tick runs inside a job transaction.

Only the simulated adapter exists until a vendor is chosen (app.bootstrap wires it; settings refuse it outside
dev and test). A real adapter raises `BuildingControlError` (or a subclass) on any failure, `TimeoutError`
included, so callers record the failure and retry on the next tick instead of crashing the job.

What the hardware must guarantee (access README): free egress at all times; doors released by the fire alarm and on
power loss; emergency and exit lighting never on a circuit this port switches; a manual light switch on site for
every zone. This port never locks a door: `unlock` releases one for a few seconds and the hardware relocks it.
`read_zone` lets the tick notice a controller that rebooted dark; return None when the device cannot tell."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class BuildingControlError(Exception):
    """The controller refused, was unreachable or timed out. The message never carries a code."""


@dataclass(frozen=True)
class TimedCode:
    """A code the door controller should accept on its own between two instants (offline-capable keypads)."""

    code_id: str  # our entry_code id: the handle a later revoke names
    code: str
    valid_from: datetime
    valid_until: datetime


class BuildingController(Protocol):
    name: str
    simulated: bool
    supports_code_push: bool  # False: the keypad asks us (POST /door/verify) for every code

    def unlock(self, device_ref: str, *, seconds: int) -> None:
        """Release the door now for `seconds`, then relock."""
        ...

    def push_code(self, device_ref: str, code: TimedCode) -> None: ...

    def revoke_code(self, device_ref: str, code_id: str) -> None: ...

    def set_zone(self, zone_ref: str, *, is_on: bool) -> None: ...

    def read_zone(self, zone_ref: str) -> bool | None:
        """What the controller reports now; None when it cannot tell."""
        ...


_controller: BuildingController | None = None


def configure(controller: BuildingController | None) -> None:
    global _controller
    _controller = controller


def current() -> BuildingController | None:
    return _controller


def get() -> BuildingController:
    """The controller, or BuildingControlError when none is configured (callers record it like any failure)."""
    if _controller is None:
        raise BuildingControlError("no building control adapter is configured")
    return _controller
