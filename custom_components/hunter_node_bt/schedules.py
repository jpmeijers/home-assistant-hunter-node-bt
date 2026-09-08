"""Controller program models and conservative, HA-independent patch validation."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .const import MAX_RUN_TIME

PROGRAMS = ("A", "B", "C")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DISABLED_START = 65535
MAX_PROGRAM_NAME_BYTES = 14


def integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def slot_index(value: Any, maximum: int, label: str) -> int:
    if isinstance(value, str) and re.fullmatch(r"[1-8]", value):
        value = int(value)
    return integer(value, 1, maximum, label) - 1


def start_minutes(value: Any) -> int:
    if value is None:
        return DISABLED_START
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", value
    ):
        raise ValueError("start times must be HH:MM or null (disabled)")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


@dataclass(frozen=True, slots=True)
class HunterNodeProgram:
    letter: str
    name: str
    schedule_type: int
    schedule_days: int
    interval_day_count: int
    interval_day_next: int
    start_times: tuple[int, ...]
    runtimes: tuple[int, ...]

    @classmethod
    def from_raw(cls, letter: str, raw: Any, station_count: int) -> HunterNodeProgram:
        if not isinstance(raw, dict):
            raise ValueError(f"Program {letter} is missing or invalid")
        starts, runtimes = raw.get("StartTimes"), raw.get("RunTime")
        if not isinstance(starts, list) or len(starts) != 8:
            raise ValueError("program must have eight start slots")
        if not isinstance(runtimes, list) or not station_count <= len(runtimes) <= 4:
            raise ValueError("program runtime array does not match station count")
        for value in starts:
            integer(value, 0, DISABLED_START, "start time")
            if value > 1439 and value != DISABLED_START:
                raise ValueError("invalid start time")
        for value in runtimes:
            integer(value, 0, 2**31 - 1, "stored runtime")
        return cls(
            letter,
            str(raw.get("Name", f"Program {letter}")),
            integer(raw.get("ScheduleType"), 0, 255, "schedule type"),
            integer(raw.get("ScheduleDays"), 0, 65535, "schedule days"),
            integer(raw.get("IntervalDayCount"), 0, 65535, "interval days"),
            integer(raw.get("IntervalDayNext"), 0, 2**63 - 1, "interval next"),
            tuple(starts),
            tuple(runtimes),
        )

    @property
    def schedule_mode(self) -> str:
        if self.schedule_type == 0:
            return "weekdays"
        if self.schedule_type == 1:
            return "even" if self.schedule_days >= 256 else "odd"
        return "interval" if self.schedule_type == 2 else "unknown"

    def as_attributes(self, station_count: int) -> dict[str, Any]:
        return {
            "program": self.letter,
            "program_name": self.name,
            "schedule_mode": self.schedule_mode,
            "weekdays": [
                day
                for index, day in enumerate(WEEKDAYS)
                if self.schedule_days & (1 << index)
            ]
            if self.schedule_type == 0
            else [],
            "interval_days": self.interval_day_count,
            "interval_next_timestamp": self.interval_day_next,
            "start_times": [
                None if value == DISABLED_START else f"{value // 60:02}:{value % 60:02}"
                for value in self.start_times
            ],
            "station_runtimes": {
                str(i + 1): value
                for i, value in enumerate(self.runtimes[:station_count])
            },
        }


def build_program_patch(
    raw: dict[str, Any], station_count: int, changes: dict[str, Any]
) -> dict[str, Any]:
    """Merge indexed changes from a fresh read, preserving hidden array entries."""
    allowed = {
        "name",
        "station_runtimes",
        "start_times",
        "start_time_slots",
        "weekdays",
        "weekday_flags",
    }
    if not changes or changes.keys() - allowed:
        raise ValueError("provide supported program fields")
    patch: dict[str, Any] = {}
    if "name" in changes:
        name = changes["name"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name.encode("utf-8")) > MAX_PROGRAM_NAME_BYTES
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError(
                "name must contain 1–14 UTF-8 bytes without control characters"
            )
        patch["Name"] = name
    if "station_runtimes" in changes:
        values = changes["station_runtimes"]
        if not isinstance(values, dict) or not values:
            raise ValueError("station_runtimes must be a nonempty mapping")
        runtimes = list(raw["RunTime"])
        seen = set()
        for station, duration in values.items():
            index = slot_index(station, station_count, "station")
            if index in seen:
                raise ValueError("duplicate station")
            seen.add(index)
            runtimes[index] = integer(duration, 0, MAX_RUN_TIME, "runtime seconds")
        patch["RunTime"] = runtimes
    if "start_times" in changes and "start_time_slots" in changes:
        raise ValueError("use either start_times or start_time_slots")
    if "start_times" in changes:
        values = changes["start_times"]
        if not isinstance(values, list) or len(values) > 8:
            raise ValueError("start_times must be a list of at most eight times")
        patch["StartTimes"] = [start_minutes(v) for v in values] + [DISABLED_START] * (
            8 - len(values)
        )
    if "start_time_slots" in changes:
        values = changes["start_time_slots"]
        if not isinstance(values, dict) or not values:
            raise ValueError("start_time_slots must be a nonempty mapping")
        starts = list(raw["StartTimes"])
        seen = set()
        for slot, value in values.items():
            index = slot_index(slot, 8, "start slot")
            if index in seen:
                raise ValueError("duplicate start slot")
            seen.add(index)
            starts[index] = start_minutes(value)
        patch["StartTimes"] = starts
    if "weekdays" in changes and "weekday_flags" in changes:
        raise ValueError("use either weekdays or weekday_flags")
    if "weekdays" in changes:
        days = changes["weekdays"]
        if not isinstance(days, list) or any(day not in WEEKDAYS for day in days):
            raise ValueError("weekdays must be a list of mon through sun")
        patch.update(
            ScheduleType=0,
            ScheduleDays=sum(1 << WEEKDAYS.index(day) for day in set(days)),
            IntervalDayCount=0,
            IntervalDayNext=0,
        )
    if "weekday_flags" in changes:
        if raw["ScheduleType"] != 0:
            raise ValueError(
                "weekday switches require weekday mode; use set_program weekdays to change mode"
            )
        flags = changes["weekday_flags"]
        if not isinstance(flags, dict) or not flags:
            raise ValueError("weekday_flags must be a nonempty mapping")
        days = raw["ScheduleDays"]
        for day, enabled in flags.items():
            if day not in WEEKDAYS or type(enabled) is not bool:
                raise ValueError(
                    "weekday_flags requires mon through sun mapped to booleans"
                )
            bit = 1 << WEEKDAYS.index(day)
            days = days | bit if enabled else days & ~bit
        patch["ScheduleDays"] = days
    if "StartTimes" in patch:
        enabled = [value for value in patch["StartTimes"] if value != DISABLED_START]
        if len(enabled) != len(set(enabled)):
            raise ValueError("duplicate program start times are not supported")
        # Firmware sorts and compacts the list; positions are not persistent slot IDs.
        patch["StartTimes"] = sorted(enabled) + [DISABLED_START] * (8 - len(enabled))
    if "StartTimes" in patch and "RunTime" in patch:
        raise ValueError(
            "edit start times and runtimes in separate actions; firmware can corrupt "
            "start times when both arrays are written together"
        )
    # Avoid needless writes, including unchanged fields in a larger edit.
    return {
        key: deepcopy(value) for key, value in patch.items() if raw.get(key) != value
    }


def validate_daily_runtime_sync(
    read_all: dict[str, Any], letter: str, changes: dict[str, Any]
) -> None:
    """Limit a daily duration sensor to one daily occurrence and no scaling."""
    if set(changes) != {"station_runtimes"}:
        raise ValueError("daily runtime synchronization only accepts station_runtimes")
    controller = read_all["Controller"]
    if (
        controller.get("SeasonAdjust") != 100
        or controller.get("SeasonAdjustByMonthEnable") is not False
    ):
        raise ValueError(
            "daily runtime synchronization requires seasonal adjustment 100% and monthly adjustment off"
        )
    count = integer(controller.get("StationCount"), 1, 4, "station count")
    programs = {
        p: HunterNodeProgram.from_raw(p, read_all.get(f"Program_{p}"), count)
        for p in PROGRAMS
    }
    program = programs[letter]
    if program.schedule_type != 0 or program.schedule_days != 127:
        raise ValueError(
            "daily runtime synchronization requires watering every weekday"
        )
    if sum(value != DISABLED_START for value in program.start_times) != 1:
        raise ValueError(
            "daily runtime synchronization requires exactly one start time"
        )
    for other_letter, other in programs.items():
        if other_letter == letter or all(
            value == DISABLED_START for value in other.start_times
        ):
            continue
        if other.schedule_type == 0 and not other.schedule_days & 127:
            continue
        if any(
            other.runtimes[slot_index(station, count, "station")]
            for station in changes["station_runtimes"]
        ):
            raise ValueError(
                "a synchronized station also has an active runtime in another program"
            )
