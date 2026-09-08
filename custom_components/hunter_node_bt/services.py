"""Device-targeted program editing actions."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .schedules import PROGRAMS, WEEKDAYS

SET_PROGRAM_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(
            cv.ensure_list, [cv.string], vol.Length(min=1, max=1)
        ),
        vol.Required("program"): vol.In(PROGRAMS),
        vol.Optional("name"): cv.string,
        vol.Optional("station_runtimes"): dict,
        vol.Optional("start_times"): list,
        vol.Optional("start_time_slots"): dict,
        vol.Optional("weekdays"): [vol.In(WEEKDAYS)],
        vol.Optional("require_daily_single_start", default=False): cv.boolean,
    }
)


@callback
def async_register_program_service(hass: HomeAssistant) -> None:
    async def async_set_program(call: ServiceCall) -> None:
        device = dr.async_get(hass).async_get(call.data["device_id"][0])
        if device is None:
            raise ServiceValidationError("Unknown NODE-BT device")
        candidates = []
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.domain == DOMAIN
                and entry.state is ConfigEntryState.LOADED
            ):
                coordinator = entry.runtime_data
                if (DOMAIN, coordinator.data.serial_number) in device.identifiers:
                    candidates.append(coordinator)
        if len(candidates) != 1:
            raise ServiceValidationError(
                "Select exactly one loaded Hunter NODE-BT controller"
            )
        changes = {
            key: value
            for key, value in call.data.items()
            if key not in {"device_id", "program"}
        }
        await candidates[0].async_set_program(call.data["program"], **changes)

    hass.services.async_register(
        DOMAIN, "set_program", async_set_program, schema=SET_PROGRAM_SCHEMA
    )
