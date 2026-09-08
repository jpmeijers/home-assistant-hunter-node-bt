"""HA entity/action smoke tests, runnable when Home Assistant is installed."""

from __future__ import annotations

import importlib.util
import unittest
from dataclasses import replace
from datetime import time
from unittest.mock import AsyncMock, MagicMock

from custom_components.hunter_node_bt.models import HunterNodeData

from .test_schedules import configuration, state

HAS_HA = importlib.util.find_spec("homeassistant") is not None


@unittest.skipUnless(HAS_HA, "Home Assistant is not installed")
class ScheduleEntityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = MagicMock()
        self.coordinator.data = HunterNodeData.from_responses(configuration(), state())
        self.coordinator.last_update_success = True
        self.coordinator.async_set_program = AsyncMock()

    async def test_runtime_and_time_controls_patch_only_the_selected_field(self):
        from custom_components.hunter_node_bt.number import HunterNodeRuntime
        from custom_components.hunter_node_bt.time import HunterNodeStartTime

        runtime = HunterNodeRuntime(self.coordinator, "A", 2)
        self.assertEqual(runtime.native_value, 60)
        await runtime.async_set_native_value(90.0)
        self.coordinator.async_set_program.assert_awaited_with(
            "A", station_runtimes={2: 90}
        )
        # A successful call alone does not set an optimistic entity value.
        self.assertEqual(runtime.native_value, 60)
        start = HunterNodeStartTime(self.coordinator, "A", 2)
        self.assertIsNone(start.native_value)
        await start.async_set_value(time(6, 30))
        self.coordinator.async_set_program.assert_awaited_with(
            "A", start_time_slots={2: "06:30"}
        )
        await start.async_clear_start_time()
        self.coordinator.async_set_program.assert_awaited_with(
            "A", start_time_slots={2: None}
        )
        with self.assertRaises(ValueError):
            await start.async_set_value(time(6, 30, 15))

    async def test_weekday_switch_does_not_edit_interval_mode(self):
        from custom_components.hunter_node_bt.switch import HunterNodeWeekday

        day = HunterNodeWeekday(self.coordinator, "A", "mon")
        self.assertTrue(day.available)
        self.assertTrue(day.is_on)
        await day.async_turn_off()
        self.coordinator.async_set_program.assert_awaited_with(
            "A", weekday_flags={"mon": False}
        )
        programs = list(self.coordinator.data.programs)
        programs[0] = replace(programs[0], schedule_type=2)
        self.coordinator.data = replace(self.coordinator.data, programs=tuple(programs))
        self.assertFalse(day.available)

    async def test_service_resolves_only_loaded_controller(self):
        from unittest.mock import patch

        from homeassistant.config_entries import ConfigEntryState
        from homeassistant.exceptions import ServiceValidationError

        from custom_components.hunter_node_bt.services import (
            SET_PROGRAM_SCHEMA,
            async_register_program_service,
        )

        hass = MagicMock()
        entry = MagicMock(
            domain="hunter_node_bt",
            state=ConfigEntryState.LOADED,
            runtime_data=self.coordinator,
        )
        hass.config_entries.async_get_entry.return_value = entry
        device = MagicMock(
            config_entries={"entry"}, identifiers={("hunter_node_bt", "16707796")}
        )
        call = MagicMock(
            data=SET_PROGRAM_SCHEMA(
                {"device_id": "device", "program": "A", "station_runtimes": {"1": 120}}
            )
        )
        with patch(
            "custom_components.hunter_node_bt.services.dr.async_get"
        ) as registry:
            registry.return_value.async_get.return_value = device
            async_register_program_service(hass)
            handler = hass.services.async_register.call_args.args[2]
            await handler(call)
            self.coordinator.async_set_program.assert_awaited_with(
                "A", station_runtimes={"1": 120}, require_daily_single_start=False
            )
            entry.state = ConfigEntryState.NOT_LOADED
            with self.assertRaises(ServiceValidationError):
                await handler(call)
