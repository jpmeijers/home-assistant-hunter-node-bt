"""Sensor entities for Hunter NODE-BT."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import CONTROLLER_STATE_NAMES, DOMAIN
from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeEntity, HunterNodeProgramEntity
from .models import HunterNodeData
from .schedules import DISABLED_START, PROGRAMS
from .setup_helpers import async_add_entities_when_ready


@dataclass(frozen=True, kw_only=True)
class HunterNodeSensorDescription(SensorEntityDescription):
    value_fn: Callable[[HunterNodeData], object | None]


SENSORS = (
    HunterNodeSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.battery,
    ),
    HunterNodeSensorDescription(
        key="rssi",
        translation_key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.rssi,
    ),
    HunterNodeSensorDescription(
        key="moisture",
        translation_key="moisture",
        device_class=SensorDeviceClass.MOISTURE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.moisture,
    ),
    HunterNodeSensorDescription(
        key="controller_state",
        translation_key="controller_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(CONTROLLER_STATE_NAMES.values()),
        value_fn=lambda data: CONTROLLER_STATE_NAMES.get(data.controller_state),
    ),
    HunterNodeSensorDescription(
        key="daily_run_time",
        translation_key="daily_run_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: data.daily_run_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up controller sensors."""
    coordinator: HunterNodeCoordinator = entry.runtime_data
    # Preserve existing serial-based IDs; new entries use the known BLE address.
    unique_id = next(
        (
            entity.unique_id
            for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
            if entity.domain == "sensor"
            and entity.platform == DOMAIN
            and entity.unique_id.endswith("_rssi")
        ),
        f"{coordinator.address}_rssi",
    )
    async_add_entities([
        HunterNodeSignalSensor(
            coordinator, next(item for item in SENSORS if item.key == "rssi"), unique_id
        )
    ])

    def controller_sensors():
        yield from (
            HunterNodeSensor(coordinator, description)
            for description in SENSORS if description.key != "rssi"
        )
        yield from (HunterNodeProgramSensor(coordinator, letter) for letter in PROGRAMS)
        yield from (
            HunterNodeScheduleStatus(coordinator, key)
            for key in (
                "schedule_write_status", "configuration_read_at",
                "schedule_write_verified_at",
            )
        )

    async_add_entities_when_ready(entry, async_add_entities, controller_sensors)


class HunterNodeSensor(HunterNodeEntity, SensorEntity):
    entity_description: HunterNodeSensorDescription

    def __init__(
        self,
        coordinator: HunterNodeCoordinator,
        description: HunterNodeSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.data.serial_number}_{description.key}"

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)


class HunterNodeSignalSensor(SensorEntity):
    """Last received signal and payload, even when a GATT read fails."""

    _attr_force_update = True
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HunterNodeCoordinator,
        description: HunterNodeSensorDescription,
        unique_id: str,
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = unique_id
        # A Bluetooth connection identifies the existing device without a read.
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="Hunter Industries",
            model="NODE-BT",
        )

    async def async_update(self) -> None:
        """An explicit signal refresh also reads only the advertisement cache."""
        self.coordinator._async_sample_advertisement()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.advertisements.async_add_listener(
                self.async_write_ha_state
            )
        )

    @property
    def available(self) -> bool:
        # This is a last-observation diagnostic, not proof of GATT connectivity.
        return self.coordinator.advertisements.data is not None

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.advertisements.data
        return data["rssi"] if data is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.advertisements.data
        if data is None:
            return None
        return {key: value for key, value in data.items() if key != "rssi"}


class HunterNodeProgramSensor(HunterNodeProgramEntity, SensorEntity):
    _attr_translation_key = "program_schedule"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["configured", "inactive"]

    def __init__(self, coordinator: HunterNodeCoordinator, letter: str) -> None:
        super().__init__(coordinator, letter, "schedule")
        self._attr_translation_placeholders = {"program": letter}

    @property
    def native_value(self) -> str:
        runnable = any(value != DISABLED_START for value in self.program.start_times)
        runnable = runnable and any(
            self.program.runtimes[: self.coordinator.data.station_count]
        )
        if self.program.schedule_type == 0 and not self.program.schedule_days & 127:
            runnable = False
        return "configured" if runnable else "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.program.as_attributes(self.coordinator.data.station_count)


class HunterNodeScheduleStatus(HunterNodeEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HunterNodeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"{coordinator.data.serial_number}_{key}"
        self._attr_translation_key = key
        if key == "schedule_write_status":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = [
                "not_requested",
                "writing",
                "verified",
                "unverified",
                "failed",
            ]
        else:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def available(self) -> bool:
        # Diagnostics must remain visible when BLE/readback fails.
        return True

    @property
    def native_value(self) -> str | datetime | None:
        if self.key == "configuration_read_at":
            return self.coordinator.data.configuration_read_at
        return getattr(self.coordinator, self.key)
