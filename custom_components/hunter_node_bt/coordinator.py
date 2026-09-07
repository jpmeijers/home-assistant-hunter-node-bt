"""Data coordinator for Hunter NODE-BT."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import bleak
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS, establish_connection

if TYPE_CHECKING:
    from bleak import BleakClient

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_PIN, UPDATE_INTERVAL
from .models import HunterNodeData
from .protocol import (
    HunterNodeAmbiguousCommandError,
    HunterNodeController,
    HunterNodeError,
)

UPDATE_EXCEPTIONS = (*BLEAK_RETRY_EXCEPTIONS, HunterNodeError)
_LOGGER = logging.getLogger(__name__)


class HunterNodeCoordinator(DataUpdateCoordinator[HunterNodeData]):
    """Coordinate low-frequency reads and serialized controller commands."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=UPDATE_INTERVAL,
        )
        self.address = entry.data[CONF_ADDRESS]
        self.controller = HunterNodeController(
            self._async_connect, int(entry.data[CONF_PIN])
        )

    async def _async_connect(self) -> BleakClient:
        """Connect using Home Assistant's best current local or proxy route."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise UpdateFailed("controller is not currently advertising")
        return await establish_connection(
            bleak.BleakClient,
            device,
            self.config_entry.title,
            max_attempts=3,
        )

    async def _async_update_data(self) -> HunterNodeData:
        """Read the controller and live station state."""
        try:
            return await self.controller.read_data()
        except UPDATE_EXCEPTIONS as err:
            raise UpdateFailed(str(err)) from err

    async def async_start_station(self, station: int, duration: int) -> None:
        """Start a station, then refresh state if the command was acknowledged."""
        try:
            await self.controller.start_station(station, duration)
        except HunterNodeAmbiguousCommandError:
            await self.async_request_refresh()
            raise
        await self.async_request_refresh()

    async def async_stop_all(self) -> None:
        """Stop all stations and refresh live state."""
        await self.controller.stop_all()
        await self.async_request_refresh()
