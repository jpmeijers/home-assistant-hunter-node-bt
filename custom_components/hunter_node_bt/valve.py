"""Water valve entities for Hunter NODE-BT stations."""

from __future__ import annotations

from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_RUN_TIME,
    DEFAULT_RUN_TIME,
    MAX_RUN_TIME,
    MIN_RUN_TIME,
    STATION_ACTIVE_STATES,
)
from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeEntity
from .models import HunterNodeStation
from .setup_helpers import async_add_entities_when_ready


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one valve per physical station."""
    coordinator: HunterNodeCoordinator = entry.runtime_data
    async_add_entities_when_ready(
        entry, async_add_entities,
        lambda: (HunterNodeValve(coordinator, station.number) for station in coordinator.data.stations),
    )


class HunterNodeValve(HunterNodeEntity, ValveEntity):
    """A timed irrigation station."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE

    def __init__(self, coordinator: HunterNodeCoordinator, station_number: int) -> None:
        super().__init__(coordinator)
        self.station_number = station_number
        self._attr_unique_id = (
            f"{coordinator.data.serial_number}_station_{station_number}"
        )

    @property
    def name(self) -> str:
        return self._station.name

    @property
    def is_closed(self) -> bool:
        return self._station.state not in STATION_ACTIVE_STATES

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"remaining_seconds": self._station.remaining}

    async def async_open_valve(self, **kwargs: Any) -> None:
        """Run the station for the configured bounded duration."""
        await self.async_start_watering(
            self.coordinator.config_entry.options.get(
                CONF_RUN_TIME,
                self.coordinator.config_entry.data.get(
                    CONF_RUN_TIME, DEFAULT_RUN_TIME
                ),
            )
        )

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Stop all watering because the protocol has no per-station stop."""
        await self.coordinator.async_stop_all()

    async def async_start_watering(self, duration: int) -> None:
        """Run the station for an explicit number of seconds."""
        duration = int(duration)
        if duration not in range(MIN_RUN_TIME, MAX_RUN_TIME + 1):
            raise ValueError(
                f"duration must be between {MIN_RUN_TIME} and {MAX_RUN_TIME} seconds"
            )
        await self.coordinator.async_start_station(self.station_number, duration)

    @property
    def _station(self) -> HunterNodeStation:
        return self.coordinator.data.stations[self.station_number - 1]
