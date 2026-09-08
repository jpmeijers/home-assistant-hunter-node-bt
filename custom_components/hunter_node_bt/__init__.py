"""The Hunter NODE-BT integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register Hunter NODE-BT actions."""
    import voluptuous as vol

    from homeassistant.components.valve import DOMAIN as VALVE_DOMAIN
    from homeassistant.helpers import config_validation as cv, service

    from .const import ATTR_DURATION, DOMAIN, MAX_RUN_TIME

    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "start_watering",
        entity_domain=VALVE_DOMAIN,
        schema={
            vol.Required(ATTR_DURATION): vol.All(
                cv.positive_int, vol.Range(max=MAX_RUN_TIME)
            )
        },
        func="async_start_watering",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hunter NODE-BT from a config entry."""
    from .coordinator import HunterNodeCoordinator

    coordinator = HunterNodeCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, ("valve", "sensor", "button")
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Hunter NODE-BT config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, ("valve", "sensor", "button")
    )
