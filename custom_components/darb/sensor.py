"""DARB sensors: per body (battery, task) and on the hub (counts, power)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DarbConfigEntry, DarbCoordinator
from .entity import DarbBodyEntity, DarbHubEntity


@dataclass(frozen=True, kw_only=True)
class HubSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]


HUB_SENSORS: tuple[HubSensorDescription, ...] = (
    HubSensorDescription(
        key="unread_notifications",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: (d.get("notifications") or {}).get("unread"),
    ),
    HubSensorDescription(
        key="tasks_running",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: (d.get("counts") or {}).get("running"),
    ),
    HubSensorDescription(
        key="tasks_queued",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: (d.get("counts") or {}).get("queued"),
    ),
    # Delayed = capable bodies exist but none is free or online. It resolves on
    # its own, but silent waiting looks exactly like silent breakage.
    HubSensorDescription(
        key="tasks_delayed",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: (d.get("counts") or {}).get("delayed"),
    ),
    HubSensorDescription(
        key="tasks_failed_today",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: (d.get("counts") or {}).get("failed_today"),
    ),
    # What the property's power source PERMITS, not just its name: on generator
    # the hub restricts discretionary work, and automations should know that.
    HubSensorDescription(
        key="power_source",
        value=lambda d: (d.get("power") or {}).get("source"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DarbConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [DarbHubSensor(coordinator, d) for d in HUB_SENSORS]
        + [DarbApprovalsSensor(coordinator)]
    )

    # Bodies come and go: a new one plugged in on the property should appear in
    # HA on the next poll, with no reload — the same promise the hub makes.
    known: set[str] = set()

    @callback
    def _add_new_bodies() -> None:
        new = [
            b["id"]
            for b in (coordinator.data or {}).get("bodies", [])
            if b["id"] not in known
        ]
        if not new:
            return
        known.update(new)
        entities: list[SensorEntity] = []
        for body_id in new:
            entities += [
                DarbBatterySensor(coordinator, body_id),
                DarbTaskSensor(coordinator, body_id),
            ]
        async_add_entities(entities)

    _add_new_bodies()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_bodies))


class DarbHubSensor(DarbHubEntity, SensorEntity):
    entity_description: HubSensorDescription

    def __init__(
        self, coordinator: DarbCoordinator, description: HubSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "power_source":
            return {"allow": (self.coordinator.data.get("power") or {}).get("allow")}
        return None


class DarbApprovalsSensor(DarbHubEntity, SensorEntity):
    """How many approvals are waiting, with what each one is asking.

    The attributes carry what an automation or a card needs to put the question
    to a person — and the request id `darb.answer_approval` takes.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DarbCoordinator) -> None:
        super().__init__(coordinator, "pending_approvals")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("approvals") or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"requests": self.coordinator.data.get("approvals") or []}


class DarbBatterySensor(DarbBodyEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DarbCoordinator, body_id: str) -> None:
        super().__init__(coordinator, body_id, "battery")

    @property
    def native_value(self) -> float | None:
        return (self.body or {}).get("battery_pct")


class DarbTaskSensor(DarbBodyEntity, SensorEntity):
    """What the body is doing, in words — the task's goal, or idle."""

    def __init__(self, coordinator: DarbCoordinator, body_id: str) -> None:
        super().__init__(coordinator, body_id, "task")

    @property
    def native_value(self) -> str:
        task = self.current_task()
        # A sensor state is capped at 255 characters; a goal is free text.
        return task["goal"][:255] if task else "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        task = self.current_task() or {}
        return {
            "task_id": task.get("id"),
            "state": task.get("state"),
            "priority": task.get("priority"),
            "capabilities": (self.body or {}).get("capabilities") or [],
        }
