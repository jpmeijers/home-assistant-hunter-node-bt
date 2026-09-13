"""Diagnostics for Hunter NODE-BT."""

from __future__ import annotations

from dataclasses import asdict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import HunterNodeCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, object]:
    """Return protocol and model data without credentials or identifiers."""
    coordinator: HunterNodeCoordinator = entry.runtime_data
    data = asdict(coordinator.data) if coordinator.data is not None else None
    if data is not None:
        data["serial_number"] = "REDACTED"
        data["name"] = "Hunter NODE-BT"
    return {
        "last_update_success": coordinator.last_update_success,
        "advertisement": (
            {
                **coordinator.advertisements.data,
                "local_name": "REDACTED",
                "source": "REDACTED",
                "raw": "REDACTED",
                "manufacturer_data": "REDACTED",
                "service_data": "REDACTED",
            }
            if coordinator.advertisements.data is not None
            else None
        ),
        "data": data,
    }
