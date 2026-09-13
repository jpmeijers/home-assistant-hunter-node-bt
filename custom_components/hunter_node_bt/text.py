"""Names stored in the controller's programs."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeProgramEntity
from .schedules import MAX_PROGRAM_NAME_BYTES, PROGRAMS
from .setup_helpers import async_add_entities_when_ready


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities_when_ready(
        entry, async_add_entities,
        lambda: (HunterNodeProgramName(entry.runtime_data, letter) for letter in PROGRAMS),
    )


class HunterNodeProgramName(HunterNodeProgramEntity, TextEntity):
    _attr_native_min = 1
    _attr_native_max = MAX_PROGRAM_NAME_BYTES
    _attr_translation_key = "program_name"

    def __init__(self, coordinator: HunterNodeCoordinator, letter: str) -> None:
        super().__init__(coordinator, letter, "name")
        self._attr_translation_placeholders = {"program": letter}

    @property
    def native_value(self) -> str:
        return self.program.name

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_set_program(self.letter, name=value)
