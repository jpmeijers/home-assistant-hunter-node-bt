"""Program start slots, expressed in the controller's local clock time."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeProgramEntity
from .schedules import DISABLED_START, PROGRAMS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        HunterNodeStartTime(entry.runtime_data, letter, slot)
        for letter in PROGRAMS
        for slot in range(1, 9)
    )


class HunterNodeStartTime(HunterNodeProgramEntity, TimeEntity):
    _attr_translation_key = "program_start"

    def __init__(
        self, coordinator: HunterNodeCoordinator, letter: str, slot: int
    ) -> None:
        super().__init__(coordinator, letter, f"start_{slot}")
        self.slot = slot
        self._attr_translation_placeholders = {"program": letter, "slot": str(slot)}
        self._attr_entity_registry_enabled_default = slot == 1

    @property
    def native_value(self) -> time | None:
        value = self.program.start_times[self.slot - 1]
        return None if value == DISABLED_START else time(value // 60, value % 60)

    @property
    def extra_state_attributes(self) -> dict[str, str | int | bool]:
        return {
            "enabled": self.program.start_times[self.slot - 1] != DISABLED_START,
            "program": self.letter,
            "slot": self.slot,
        }

    async def async_set_value(self, value: time) -> None:
        if value.second or value.microsecond or value.tzinfo is not None:
            raise ValueError("start time must be a local HH:MM time with zero seconds")
        await self.coordinator.async_set_program(
            self.letter, start_time_slots={self.slot: value.strftime("%H:%M")}
        )

    async def async_clear_start_time(self) -> None:
        await self.coordinator.async_set_program(
            self.letter, start_time_slots={self.slot: None}
        )
