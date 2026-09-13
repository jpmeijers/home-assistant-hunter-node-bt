"""Weekday selection for controller-resident programs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeProgramEntity
from .schedules import PROGRAMS, WEEKDAYS
from .setup_helpers import async_add_entities_when_ready


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities_when_ready(
        entry, async_add_entities,
        lambda: (HunterNodeWeekday(entry.runtime_data, letter, day)
        for letter in PROGRAMS
        for day in WEEKDAYS),
    )


class HunterNodeWeekday(HunterNodeProgramEntity, SwitchEntity):
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: HunterNodeCoordinator, letter: str, day: str
    ) -> None:
        super().__init__(coordinator, letter, day)
        self.day = day
        self._attr_translation_key = f"program_{day}"
        self._attr_translation_placeholders = {"program": letter}

    @property
    def available(self) -> bool:
        return super().available and self.program.schedule_type == 0

    @property
    def is_on(self) -> bool:
        return bool(self.program.schedule_days & (1 << WEEKDAYS.index(self.day)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_program(
            self.letter, weekday_flags={self.day: True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_program(
            self.letter, weekday_flags={self.day: False}
        )
