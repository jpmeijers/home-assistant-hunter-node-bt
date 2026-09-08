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
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import CONTROLLER_STATE_NAMES
from .coordinator import HunterNodeCoordinator
from .entity import HunterNodeEntity, HunterNodeProgramEntity
from .models import HunterNodeData
from .schedules import DISABLED_START, PROGRAMS


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
    async_add_entities(
        HunterNodeSensor(coordinator, description) for description in SENSORS
    )
    async_add_entities(
        HunterNodeProgramSensor(coordinator, letter) for letter in PROGRAMS
    )
    async_add_entities(
        HunterNodeScheduleStatus(coordinator, key)
        for key in (
            "schedule_write_status",
            "configuration_read_at",
            "schedule_write_verified_at",
        )
    )


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
