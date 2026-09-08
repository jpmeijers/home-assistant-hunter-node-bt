"""Sensor entities for Hunter NODE-BT."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from .entity import HunterNodeEntity
from .models import HunterNodeData


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
