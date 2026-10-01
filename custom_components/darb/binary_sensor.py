"""Whether each body is connected to the hub."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DarbConfigEntry, DarbCoordinator
from .entity import DarbBodyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DarbConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def _add_new_bodies() -> None:
        new = [
            b["id"]
            for b in (coordinator.data or {}).get("bodies", [])
            if b["id"] not in known
        ]
        if new:
            known.update(new)
            async_add_entities(DarbOnlineSensor(coordinator, b) for b in new)

    _add_new_bodies()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_bodies))


class DarbOnlineSensor(DarbBodyEntity, BinarySensorEntity):
    """The hub's view, driven by the body's MQTT last-will: a body that loses
    power or Wi-Fi reads off here within the broker's keepalive."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: DarbCoordinator, body_id: str) -> None:
        super().__init__(coordinator, body_id, "online")

    @property
    def is_on(self) -> bool | None:
        return (self.body or {}).get("online")
