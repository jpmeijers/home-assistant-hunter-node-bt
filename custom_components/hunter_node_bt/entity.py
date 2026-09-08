"""Shared Hunter NODE-BT entity helpers."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HunterNodeCoordinator
from .schedules import PROGRAMS, HunterNodeProgram


class HunterNodeEntity(CoordinatorEntity[HunterNodeCoordinator]):
    """Base entity associated with a Hunter NODE-BT controller."""

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, data.serial_number)},
            connections={
                (
                    CONNECTION_BLUETOOTH,
                    self.coordinator.config_entry.data[CONF_ADDRESS],
                )
            },
            manufacturer="Hunter Industries",
            model="NODE-BT",
            name=data.name,
            sw_version=data.firmware_version,
        )


class HunterNodeProgramEntity(HunterNodeEntity):
    """An entity whose values always come from the last controller read."""

    def __init__(
        self, coordinator: HunterNodeCoordinator, letter: str, key: str
    ) -> None:
        super().__init__(coordinator)
        self.letter = letter
        self._attr_unique_id = (
            f"{coordinator.data.serial_number}_program_{letter.lower()}_{key}"
        )

    @property
    def program(self) -> HunterNodeProgram:
        return self.coordinator.data.programs[PROGRAMS.index(self.letter)]
