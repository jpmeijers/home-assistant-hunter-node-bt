"""Passive observations must publish independently of GATT polling."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from custom_components.hunter_node_bt.advertisement import HunterNodeAdvertisements


def advertisement(**changes):
    values = {
        "address": "60:B6:47:FE:F0:D4",
        "name": "NODE-BT-707796",
        "rssi": -101,
        "source": "84:FC:E6:07:5C:A6",
        "connectable": True,
        "time": 90.0,
        "tx_power": None,
        "service_uuids": [],
        "manufacturer_data": {},
        "service_data": {},
        "raw": bytes.fromhex("0201060f094e4f44452d42542d373037373936"),
    }
    values.update(changes)
    return SimpleNamespace(**values)


class AdvertisementTests(unittest.TestCase):
    def test_captured_frame_and_cached_observation_age(self):
        monitor = HunterNodeAdvertisements()
        now = datetime.now(timezone.utc)
        with patch("custom_components.hunter_node_bt.advertisement.time.monotonic", return_value=100):
            monitor.async_observe(advertisement())
        self.assertEqual(monitor.data["rssi"], -101)
        self.assertEqual(monitor.data["raw"], "0201060f094e4f44452d42542d373037373936")
        self.assertEqual(monitor.data["local_name"], "NODE-BT-707796")
        self.assertEqual(monitor.data["manufacturer_data"], {})
        age = (now - datetime.fromisoformat(monitor.data["last_seen"])).total_seconds()
        self.assertAlmostEqual(age, 10, delta=0.1)

    def test_repeated_rssi_is_published_and_unsubscribe_stops_updates(self):
        monitor = HunterNodeAdvertisements()
        listener = Mock()
        remove = monitor.async_add_listener(listener)
        monitor.async_observe(advertisement())
        monitor.async_observe(advertisement(time=91))
        self.assertEqual(listener.call_count, 2)
        remove()
        monitor.async_observe(advertisement(rssi=-80, time=92))
        self.assertEqual(listener.call_count, 2)
        self.assertEqual(monitor.data["rssi"], -80)

    def test_cache_repeats_and_older_replays_do_not_create_fresh_observations(self):
        monitor = HunterNodeAdvertisements()
        listener = Mock()
        monitor.async_add_listener(listener)
        monitor.async_observe(advertisement(time=90))
        snapshot = monitor.data
        monitor.async_observe(advertisement(time=90))
        monitor.async_observe(advertisement(time=89, rssi=-60))
        self.assertIs(monitor.data, snapshot)
        listener.assert_called_once_with()

    def test_optional_payloads_are_hex_and_copied(self):
        monitor = HunterNodeAdvertisements()
        info = advertisement(
            raw=None, manufacturer_data={123: b"\x00\xff"},
            service_data={"uuid": b"\x01\x80"}, service_uuids=["uuid"],
            tx_power=-4, connectable=False,
        )
        monitor.async_observe(info)
        info.service_uuids.clear()
        self.assertEqual(monitor.data["manufacturer_data"], {"123": "00ff"})
        self.assertEqual(monitor.data["service_data"], {"uuid": "0180"})
        self.assertEqual(monitor.data["service_uuids"], ["uuid"])
        self.assertIsNone(monitor.data["raw"])
        self.assertEqual(monitor.data["tx_power"], -4)
        self.assertFalse(monitor.data["connectable"])
