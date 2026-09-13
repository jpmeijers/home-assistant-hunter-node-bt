"""Advertisement observations, independent of controller reads and availability."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)


class HunterNodeAdvertisements:
    """Retain and publish every observation delivered by Home Assistant."""

    def __init__(self) -> None:
        self.data: dict[str, Any] | None = None
        self._last_observed_time: float | None = None
        self._listeners: set[Callable[[], None]] = set()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def async_observe(self, info: Any) -> None:
        # The callback and cache sampler can deliver the same observation.
        if self._last_observed_time is not None and info.time <= self._last_observed_time:
            return
        self._last_observed_time = info.time
        # HA can replay cached observations at registration. Preserve their age.
        observed_at = datetime.now(timezone.utc) - timedelta(
            seconds=max(0, time.monotonic() - info.time)
        )
        raw = getattr(info, "raw", None)
        self.data = {
            "rssi": info.rssi,
            "last_seen": observed_at.isoformat(),
            "local_name": info.name,
            "source": info.source,
            "connectable": info.connectable,
            "tx_power": info.tx_power,
            "service_uuids": list(info.service_uuids),
            "manufacturer_data": {
                str(key): value.hex() for key, value in info.manufacturer_data.items()
            },
            "service_data": {
                key: value.hex() for key, value in info.service_data.items()
            },
            "raw": raw.hex() if raw is not None else None,
        }
        _LOGGER.debug("Advertisement from %s: %s", info.address, self.data)
        for listener in tuple(self._listeners):
            listener()
