"""Shared Hunter NODE-BT entity helpers."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HunterNodeCoordinator


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
