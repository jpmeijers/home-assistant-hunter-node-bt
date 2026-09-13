"""Create controller entities only once their identity and stations are known."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity import Entity
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


def async_add_entities_when_ready(
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[], Iterable[Entity]],
) -> None:
    """Keep polling while offline and instantiate entities on the first read."""
    coordinator = entry.runtime_data
    added = False

    def add_when_ready() -> None:
        nonlocal added
        if added or coordinator.data is None or not coordinator.last_update_success:
            return
        entities = list(factory())
        async_add_entities(entities)
        added = True

    # Retain until entry unload, so polling survives the handover to entities
    # (including configurations where all polled entities are disabled).
    entry.async_on_unload(coordinator.async_add_listener(add_when_ready))
    add_when_ready()
