"""Startup lifecycle regressions without requiring a Bluetooth controller."""

import asyncio
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.hunter_node_bt import async_setup_entry
from custom_components.hunter_node_bt.setup_helpers import async_add_entities_when_ready


class DeferredEntitiesTests(unittest.TestCase):
    def setUp(self):
        self.listeners = []
        self.cleanup = []
        self.coordinator = SimpleNamespace(data=None, last_update_success=False)

        def subscribe(listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)

        self.coordinator.async_add_listener = subscribe
        self.entry = SimpleNamespace(
            runtime_data=self.coordinator, async_on_unload=self.cleanup.append
        )

    def test_failed_reads_do_not_build_entities_and_recovery_adds_only_once(self):
        add = Mock()
        factory = Mock(return_value=["valve", "battery"])
        async_add_entities_when_ready(self.entry, add, factory)
        factory.assert_not_called()
        for listener in self.listeners:
            listener()
        factory.assert_not_called()
        self.coordinator.data = object()
        self.coordinator.last_update_success = True
        for _ in range(3):
            for listener in self.listeners:
                listener()
        factory.assert_called_once_with()
        add.assert_called_once_with(["valve", "battery"])
        for cancel in self.cleanup:
            cancel()
        self.assertEqual(self.listeners, [])

    def test_unload_before_recovery_removes_pending_subscription(self):
        factory = Mock()
        async_add_entities_when_ready(self.entry, Mock(), factory)
        for cancel in self.cleanup:
            cancel()
        self.coordinator.data = object()
        self.coordinator.last_update_success = True
        self.assertEqual(self.listeners, [])
        factory.assert_not_called()


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_finishes_with_first_read_pending_and_after_read_failure(self):
        started = asyncio.Event()
        finish = asyncio.Event()
        tasks = []
        order = []

        async def refresh():
            order.append("read")
            started.set()
            await finish.wait()
            # DataUpdateCoordinator.async_refresh handles a failed read this way.
            coordinator.last_update_success = False

        coordinator = SimpleNamespace(
            data=None, last_update_success=False,
            async_refresh=refresh,
            async_start_advertisements=lambda: order.append("advertisements"),
        )

        async def forward(entry, platforms):
            self.assertIs(entry.runtime_data, coordinator)
            self.assertIn("sensor", platforms)
            self.assertEqual(order, ["advertisements"])
            order.append("platforms")

        def create_task(hass, coroutine, name):
            task = asyncio.create_task(coroutine, name=name)
            tasks.append(task)
            return task

        entry = SimpleNamespace(async_create_background_task=create_task)
        hass = SimpleNamespace(config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(side_effect=forward)
        ))
        module = ModuleType("custom_components.hunter_node_bt.coordinator")
        module.HunterNodeCoordinator = Mock(return_value=coordinator)
        with patch.dict(sys.modules, {module.__name__: module}):
            self.assertTrue(await asyncio.wait_for(async_setup_entry(hass, entry), 1))
        await started.wait()
        self.assertEqual(order, ["advertisements", "platforms", "read"])
        self.assertFalse(tasks[0].done())
        finish.set()
        await tasks[0]
        self.assertIsNone(coordinator.data)
        self.assertFalse(coordinator.last_update_success)
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
