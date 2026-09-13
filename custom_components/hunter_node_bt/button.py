"""Button entities for Hunter NODE-BT."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeEntity
from .setup_helpers import async_add_entities_when_ready


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the stop-all button."""
    coordinator: HunterNodeCoordinator = entry.runtime_data
    async_add_entities_when_ready(
        entry, async_add_entities, lambda: [HunterNodeStopButton(coordinator)]
    )


class HunterNodeStopButton(HunterNodeEntity, ButtonEntity):
    """Stop every active station."""

    _attr_translation_key = "stop_all"

    def __init__(self, coordinator: HunterNodeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.data.serial_number}_stop_all"

    async def async_press(self) -> None:
        """Stop all watering."""
        await self.coordinator.async_stop_all()
