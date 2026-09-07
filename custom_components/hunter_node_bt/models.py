"""Data models for Hunter NODE-BT controllers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HunterNodeStation:
    """A physical irrigation station."""

    number: int
    name: str
    state: int = 0
    remaining: int = 0


@dataclass(frozen=True, slots=True)
class HunterNodeData:
    """A complete controller snapshot."""

    name: str
    serial_number: str
    station_count: int
    firmware_version: str | None
    bluetooth_firmware_version: str | None
    battery: int | None
    moisture: int | None
    controller_state: int | None
    next_water_time: int | None
    daily_run_time: int | None
    stations: tuple[HunterNodeStation, ...]

    @classmethod
    def from_responses(
        cls, read_all: dict[str, Any], read_state: dict[str, Any]
    ) -> HunterNodeData:
        """Build a snapshot from the controller's two read responses."""
        controller = _mapping(read_all, "Controller")
        sensor = _mapping(read_all, "Sensor")
        state = _mapping(read_state, "State")

        station_count = _required_int(controller, "StationCount")
        if station_count not in range(1, 5):
            raise ValueError(f"unsupported station count: {station_count}")

        stations: list[HunterNodeStation] = []
        for number in range(1, station_count + 1):
            station_key = f"Station_{number}"
            station_config = _mapping(read_all, station_key)
            station_state = _mapping(state, station_key)
            stations.append(
                HunterNodeStation(
                    number=number,
                    name=str(station_config.get("Name") or f"Station {number}"),
                    state=_optional_int(station_state.get("State")) or 0,
                    remaining=_optional_int(station_state.get("Remaining")) or 0,
                )
            )

        version = controller.get("Version")
        version_letter = controller.get("VersionLetter")
        firmware = None
        if version is not None:
            firmware = f"{version}{version_letter or ''}"

        return cls(
            name=str(controller.get("Name") or "Hunter NODE-BT"),
            serial_number=str(controller.get("SerialNumber") or "unknown"),
            station_count=station_count,
            firmware_version=firmware,
            bluetooth_firmware_version=_optional_str(controller.get("BTVersion")),
            battery=_optional_int(sensor.get("Battery")),
            moisture=_optional_int(sensor.get("MoistureSensor")),
            controller_state=_optional_int(state.get("ControllerState")),
            next_water_time=_optional_int(state.get("NextWaterTime")),
            daily_run_time=_optional_int(state.get("DailyRunTime")),
            stations=tuple(stations),
        )


def _mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} is not an object")
    return value


def _required_int(container: dict[str, Any], key: str) -> int:
    value = _optional_int(container.get(key))
    if value is None:
        raise ValueError(f"missing integer field: {key}")
    return value


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
