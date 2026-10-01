"""Shared bases: the hub device, and one device per body."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DarbCoordinator

HUB_DEVICE_ID = (DOMAIN, "hub")


def body_device_id(body_id: str) -> tuple[str, str]:
    # Keyed on the body's immutable id, never its display name: renaming a body
    # in DARB renames the HA device instead of orphaning it.
    return (DOMAIN, f"body_{body_id}")


class DarbHubEntity(CoordinatorEntity[DarbCoordinator]):
    """An entity on the DARB hub's own device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DarbCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"hub_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={HUB_DEVICE_ID},
            name="DARB hub",
            manufacturer="DARB",
            model="Hub",
            configuration_url=coordinator.client.url + "/app/",
        )


class DarbBodyEntity(CoordinatorEntity[DarbCoordinator]):
    """An entity attached to one body's HA device.

    A body retired in DARB drops out of /fleet; its entities go unavailable and
    the device can then be deleted from HA (see async_remove_config_entry_device).
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: DarbCoordinator, body_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._body_id = body_id
        self._attr_unique_id = f"body_{body_id}_{key}"
        self._attr_translation_key = key

    @property
    def body(self) -> dict[str, Any] | None:
        for b in (self.coordinator.data or {}).get("bodies", []):
            if b["id"] == self._body_id:
                return b
        return None

    @property
    def available(self) -> bool:
        return super().available and self.body is not None

    @property
    def device_info(self) -> DeviceInfo:
        body = self.body or {}
        return DeviceInfo(
            identifiers={body_device_id(self._body_id)},
            name=body.get("display_name") or self._body_id,
            manufacturer="DARB",
            model=f"Body ({body.get('integration_level', 'unknown')} integration)",
            via_device=HUB_DEVICE_ID,
        )

    def current_task(self) -> dict[str, Any] | None:
        """The task this body is working on, if any. /fleet lists tasks in
        flight, highest priority first, so the first match is the one that
        matters."""
        for t in (self.coordinator.data or {}).get("tasks", []):
            if t.get("assigned_body") == self._body_id and t.get("state") in (
                "assigned",
                "running",
            ):
                return t
        return None
