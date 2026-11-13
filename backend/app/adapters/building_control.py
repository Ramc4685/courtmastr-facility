"""Building control adapters (app.ports.building_control). Only the simulated one until a vendor is chosen."""

import time
from dataclasses import dataclass, field

from app.ports.building_control import BuildingControlError, TimedCode


@dataclass
class SimulatedBuildingControl:
    """Records every call and keeps zone state in memory. Tests and demos script failures with `fail(...)`:
    the next `times` calls of `operation` (or of any operation, `"*"`) raise an error, time out, or hang (block for
    `hang_seconds`, then succeed: a stuck controller the caller must bound). Never records
    a code: `calls` holds the operation, the address and the code id only."""

    name: str = "simulated"
    simulated: bool = True
    supports_code_push: bool = True
    calls: list[tuple] = field(default_factory=list)
    zones: dict[str, bool] = field(default_factory=dict)
    pushed: set[str] = field(default_factory=set)
    hang_seconds: float = 1.0
    _failures: list[list] = field(default_factory=list)  # [operation, remaining, kind]

    def fail(self, operation: str = "*", *, times: int = 1, kind: str = "error") -> None:
        self._failures.append([operation, times, kind])

    def reset(self) -> None:
        self.calls.clear()
        self.zones.clear()
        self.pushed.clear()
        self._failures.clear()

    def _call(self, operation: str, *args) -> None:
        self.calls.append((operation, *args))
        for failure in self._failures:
            if failure[1] > 0 and failure[0] in (operation, "*"):
                failure[1] -= 1
                if failure[2] == "hang":
                    time.sleep(self.hang_seconds)
                    return
                if failure[2] == "timeout":
                    raise BuildingControlError(f"{operation} timed out")
                raise BuildingControlError(f"{operation} was refused by the controller")

    def unlock(self, device_ref: str, *, seconds: int) -> None:
        self._call("unlock", device_ref, seconds)

    def push_code(self, device_ref: str, code: TimedCode) -> None:
        self._call("push_code", device_ref, code.code_id)
        self.pushed.add(code.code_id)

    def revoke_code(self, device_ref: str, code_id: str) -> None:
        self._call("revoke_code", device_ref, code_id)
        self.pushed.discard(code_id)

    def set_zone(self, zone_ref: str, *, is_on: bool) -> None:
        self._call("set_zone", zone_ref, is_on)
        self.zones[zone_ref] = is_on

    def read_zone(self, zone_ref: str) -> bool | None:
        self._call("read_zone", zone_ref)
        return self.zones.get(zone_ref)
