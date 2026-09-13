"""Controller-stored program runtimes."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAX_RUN_TIME
from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeProgramEntity
from .schedules import PROGRAMS
from .setup_helpers import async_add_entities_when_ready


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities_when_ready(
        entry, async_add_entities,
        lambda: (HunterNodeRuntime(coordinator, letter, station.number)
        for letter in PROGRAMS
        for station in coordinator.data.stations),
    )


class HunterNodeRuntime(HunterNodeProgramEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_RUN_TIME
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "program_runtime"

    def __init__(
        self, coordinator: HunterNodeCoordinator, letter: str, station: int
    ) -> None:
        super().__init__(coordinator, letter, f"station_{station}_runtime")
        self.station = station
        self._attr_translation_placeholders = {
            "program": letter,
            "station": str(station),
        }

    @property
    def native_value(self) -> int:
        return self.program.runtimes[self.station - 1]

    async def async_set_native_value(self, value: float) -> None:
        if isinstance(value, bool) or not float(value).is_integer():
            raise ValueError("runtime must be a whole number of seconds")
        await self.coordinator.async_set_program(
            self.letter, station_runtimes={self.station: int(value)}
        )
