"""Data coordinator for Hunter NODE-BT."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import bleak
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS, establish_connection

if TYPE_CHECKING:
    from bleak import BleakClient

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .advertisement import HunterNodeAdvertisements
from .const import CONF_PIN, DOMAIN, UPDATE_INTERVAL
from .models import HunterNodeData
from .protocol import (
    HunterNodeAmbiguousCommandError,
    HunterNodeController,
    HunterNodeError,
    HunterNodeScheduleUnverifiedError,
)

UPDATE_EXCEPTIONS = (*BLEAK_RETRY_EXCEPTIONS, HunterNodeError, ValueError)
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
        self.advertisements = HunterNodeAdvertisements()
        self._operation_lock = asyncio.Lock()
        self.schedule_write_status = "not_requested"
        self.schedule_write_verified_at: datetime | None = None
        self._backup_store = Store(
            hass, 1, f"hunter_node_bt.{entry.entry_id}.program_backup"
        )
        self.controller = HunterNodeController(
            self._async_connect,
            int(entry.data[CONF_PIN]),
            # An old service call can still be finishing when an entry reloads.
            session_lock=hass.data.setdefault(DOMAIN, {}).setdefault(
                self.address, asyncio.Lock()
            ),
        )

    @callback
    def async_start_advertisements(self) -> None:
        """Listen without connecting or changing the controller polling timer."""
        self.config_entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._async_advertisement,
                {"address": self.address, "connectable": False},
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        )
        # HA suppresses discovery callbacks for RSSI-only changes, but still
        # updates its advertisement cache. Reading that cache uses no radio I/O.
        self.config_entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._async_sample_advertisement, timedelta(seconds=1)
            )
        )
        self._async_sample_advertisement()

    @callback
    def _async_sample_advertisement(self, now: datetime | None = None) -> None:
        service_info = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=False
        )
        if service_info is not None:
            self.advertisements.async_observe(service_info)

    @callback
    def _async_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        self.advertisements.async_observe(service_info)

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
        async with self._operation_lock:
            try:
                data = await self.controller.read_data()
            except UPDATE_EXCEPTIONS as err:
                raise UpdateFailed(str(err)) from err
        service_info = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        )
        return replace(data, rssi=service_info.rssi if service_info else None)

    async def _async_save_program_backup(
        self, letter: str, raw: dict[str, Any]
    ) -> None:
        backups = await self._backup_store.async_load() or {}
        backups[letter] = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "program": raw,
        }
        await self._backup_store.async_save(backups)

    async def async_set_program(self, letter: str, **changes: Any) -> None:
        """Publish only verified data; retain ambiguous-write status across refreshes."""
        async with self._operation_lock:
            self.schedule_write_status = "writing"
            self.async_update_listeners()
            try:
                data = await self.controller.set_program(
                    letter, changes, self._async_save_program_backup
                )
            except HunterNodeScheduleUnverifiedError as err:
                self.schedule_write_status = "unverified"
                self.async_set_update_error(UpdateFailed(str(err)))
                raise HomeAssistantError(str(err)) from err
            except asyncio.CancelledError:
                self.schedule_write_status = "unverified"
                self.async_set_update_error(
                    UpdateFailed("Program update cancelled; refresh before retrying")
                )
                raise
            except ValueError as err:
                self.schedule_write_status = "failed"
                self.async_update_listeners()
                raise ServiceValidationError(str(err)) from err
            except Exception as err:
                self.schedule_write_status = "failed"
                self.async_set_update_error(UpdateFailed(str(err)))
                raise HomeAssistantError(str(err)) from err
            self.schedule_write_status = "verified"
            self.schedule_write_verified_at = data.configuration_read_at
            self.async_set_updated_data(data)

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
