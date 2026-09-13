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

    async def test_signal_strength_sensor_is_disabled_by_default(self):
        from homeassistant.helpers.entity import EntityCategory

        from custom_components.hunter_node_bt.advertisement import (
            HunterNodeAdvertisements,
        )
        from custom_components.hunter_node_bt.sensor import (
            SENSORS,
            HunterNodeSignalSensor,
        )

        from .test_advertisement import advertisement

        self.coordinator.data = replace(self.coordinator.data, rssi=-71)
        self.coordinator.advertisements = HunterNodeAdvertisements()
        sensor = HunterNodeSignalSensor(
            self.coordinator, next(description for description in SENSORS if description.key == "rssi")
        )
        self.assertFalse(sensor.available)
        self.assertIsNone(sensor.native_value)
        self.coordinator.last_update_success = False
        self.coordinator.advertisements.async_observe(advertisement(rssi=-101))
        self.assertTrue(sensor.available)
        self.assertEqual(sensor.native_value, -101)
        self.assertEqual(sensor.extra_state_attributes["source"], "84:FC:E6:07:5C:A6")
        self.assertTrue(sensor.force_update)
        self.assertEqual(sensor.entity_category, EntityCategory.DIAGNOSTIC)
        self.assertFalse(sensor.entity_registry_enabled_default)

    async def test_advertisement_does_not_refresh_or_recover_poll_coordinator(self):
        from custom_components.hunter_node_bt.advertisement import (
            HunterNodeAdvertisements,
        )
        from custom_components.hunter_node_bt.coordinator import HunterNodeCoordinator

        from .test_advertisement import advertisement

        self.coordinator.advertisements = HunterNodeAdvertisements()
        self.coordinator.last_update_success = False
        snapshot = self.coordinator.data
        HunterNodeCoordinator._async_advertisement(self.coordinator, advertisement(), None)
        self.assertFalse(self.coordinator.last_update_success)
        self.assertIs(self.coordinator.data, snapshot)
        self.coordinator.async_set_updated_data.assert_not_called()
        self.coordinator.async_request_refresh.assert_not_called()
        self.coordinator.controller.read_data.assert_not_called()

    async def test_advertisement_subscription_is_passive_and_unloaded(self):
        from unittest.mock import patch

        from homeassistant.components import bluetooth

        from custom_components.hunter_node_bt.coordinator import HunterNodeCoordinator

        with (
            patch("custom_components.hunter_node_bt.coordinator.bluetooth.async_register_callback") as register,
            patch("custom_components.hunter_node_bt.coordinator.async_track_time_interval") as timer,
        ):
            HunterNodeCoordinator.async_start_advertisements(self.coordinator)
        register.assert_called_once_with(
            self.coordinator.hass, self.coordinator._async_advertisement,
            {"address": self.coordinator.address, "connectable": False},
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
        self.coordinator.config_entry.async_on_unload.assert_any_call(register.return_value)
        self.coordinator.config_entry.async_on_unload.assert_any_call(timer.return_value)
        self.assertEqual(timer.call_args.args[2].total_seconds(), 1)

    async def test_signal_cache_sampling_does_not_connect(self):
        from unittest.mock import patch

        from custom_components.hunter_node_bt.advertisement import (
            HunterNodeAdvertisements,
        )
        from custom_components.hunter_node_bt.coordinator import HunterNodeCoordinator

        from .test_advertisement import advertisement

        self.coordinator.advertisements = HunterNodeAdvertisements()
        self.coordinator.last_update_success = False
        with patch("custom_components.hunter_node_bt.coordinator.bluetooth.async_last_service_info") as cached:
            cached.return_value = advertisement(rssi=-85)
            HunterNodeCoordinator._async_sample_advertisement(self.coordinator)
        self.assertEqual(self.coordinator.advertisements.data["rssi"], -85)
        self.assertFalse(self.coordinator.last_update_success)
        self.coordinator.async_request_refresh.assert_not_called()
        self.coordinator.controller.read_data.assert_not_called()

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
        call.context.user_id = None
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

    async def test_service_checks_target_program_permissions_before_writing(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from homeassistant.auth.permissions.const import POLICY_CONTROL
        from homeassistant.config_entries import ConfigEntryState
        from homeassistant.exceptions import Unauthorized, UnknownUser

        from custom_components.hunter_node_bt.services import (
            async_register_program_service,
        )

        hass = MagicMock()
        user = MagicMock()
        hass.auth.async_get_user = AsyncMock(return_value=user)
        hass.config_entries.async_get_entry.return_value = SimpleNamespace(
            domain="hunter_node_bt", state=ConfigEntryState.LOADED,
            runtime_data=self.coordinator,
        )
        device = SimpleNamespace(
            id="device", config_entries={"entry"},
            identifiers={("hunter_node_bt", "16707796")},
        )
        call = SimpleNamespace(
            context=MagicMock(user_id="restricted"),
            data={"device_id": ["device"], "program": "A", "start_times": []},
        )
        def entity(domain, suffix, letter="a"):
            return SimpleNamespace(
                platform="hunter_node_bt", domain=domain,
                unique_id=f"16707796_program_{letter}_{suffix}",
                entity_id=f"{domain}.{letter}_{suffix}",
            )

        entities = [entity("time", "start_1"), entity("switch", "mon")]
        with (
            patch("custom_components.hunter_node_bt.services.dr.async_get") as devices,
            patch("custom_components.hunter_node_bt.services.er.async_get"),
            patch("custom_components.hunter_node_bt.services.er.async_entries_for_device") as entries,
        ):
            devices.return_value.async_get.return_value = device
            entries.return_value = entities + [
                entity("sensor", "schedule"), entity("time", "start_1", "b")
            ]
            async_register_program_service(hass)
            handler = hass.services.async_register.call_args.args[2]

            # Read-only users and users denied just one editing entity cannot write.
            for allowed in (set(), {"time.a_start_1"}):
                user.permissions.check_entity.side_effect = (
                    lambda eid, policy, allowed=allowed: eid in allowed
                )
                with self.assertRaises(Unauthorized):
                    await handler(call)
                self.coordinator.async_set_program.assert_not_awaited()

            # Unknown users cannot inherit internal-automation privileges.
            hass.auth.async_get_user.return_value = None
            with self.assertRaises(UnknownUser):
                await handler(call)
            self.coordinator.async_set_program.assert_not_awaited()
            hass.auth.async_get_user.return_value = user

            # A missing registry target must fail closed, even for a permissive user.
            entries.return_value = []
            with self.assertRaises(Unauthorized):
                await handler(call)
            self.coordinator.async_set_program.assert_not_awaited()

            # Permissions on B or telemetry aren't needed to edit A.
            entries.return_value = entities + [entity("time", "start_1", "b")]
            user.permissions.check_entity.side_effect = (
                lambda eid, policy: eid in {"time.a_start_1", "switch.a_mon"}
                and policy == POLICY_CONTROL
            )
            await handler(call)
            self.coordinator.async_set_program.assert_awaited_once_with("A", start_times=[])
            self.assertEqual(entries.call_args.args[1], "device")

            self.coordinator.async_set_program.reset_mock()
            hass.auth.async_get_user.reset_mock()
            call.context.user_id = None
            await handler(call)
            hass.auth.async_get_user.assert_not_awaited()
            self.coordinator.async_set_program.assert_awaited_once()
