"""Polls the hub's /fleet and announces new notifications as HA events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DarbAuthError, DarbClient, DarbError
from .const import (
    EVENT_NOTIFICATION,
    EVENT_TASK_DONE,
    SCAN_SECONDS,
    STORAGE_KEY_NOTIFY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# What reaches the event bus. Everything an automation needs to route or word a
# notification, and nothing more: the hub's internal dedupe key and raw `data`
# blob stay on the hub.
_EVENT_FIELDS = (
    "id",
    "kind",
    "severity",
    "title",
    "detail",
    "body_id",
    "body_name",
    "task_id",
    "auth_request_id",
    "created_at",
)


@dataclass
class DarbData:
    """Everything one configured hub needs at runtime, on `entry.runtime_data`."""

    client: DarbClient
    coordinator: DarbCoordinator


type DarbConfigEntry = ConfigEntry[DarbData]


class DarbCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One poll = the fleet, plus approvals when any are waiting."""

    def __init__(self, hass: HomeAssistant, client: DarbClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="DARB fleet",
            update_interval=timedelta(seconds=SCAN_SECONDS),
        )
        self.client = client
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY_NOTIFY)
        # created_at of the newest notification already announced. None until
        # loaded; "" means "nothing stored yet" (first run).
        self._seen: str | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            fleet = await self.client.async_fleet()
            pending = (fleet.get("notifications") or {}).get("pending_approvals", 0)
            # Only fetched when there is something to show, so the common case
            # stays one request per poll.
            fleet["approvals"] = await self.client.async_approvals() if pending else []
            await self._announce()
        except DarbAuthError as e:
            # Not UpdateFailed: retrying a revoked key forever just leaves every
            # entity unavailable with nothing saying why. This makes HA offer
            # "Reconfigure" — re-pair with a fresh `darb-pair --ha`.
            raise ConfigEntryAuthFailed(str(e)) from e
        except DarbError as e:
            raise UpdateFailed(str(e)) from e
        return fleet

    async def _announce(self) -> None:
        """Fire `darb_notification` once for each notification not yet seen."""
        if self._seen is None:
            stored = await self._store.async_load() or {}
            self._seen = stored.get("newest", "")
        items = await self.client.async_notifications(limit=20)
        if not items:
            return
        newest = max(n["created_at"] for n in items)
        if not self._seen:
            # First run: everything on the hub is history. Announcing twenty old
            # alerts the moment the integration is added would be noise, and an
            # automation that pages someone would page them for last week.
            await self._remember(newest)
            return
        # ISO-8601 timestamps from one source in one zone compare correctly as
        # strings, which avoids parsing them on every poll.
        fresh = sorted(
            (n for n in items if n["created_at"] > self._seen),
            key=lambda n: n["created_at"],
        )
        for n in fresh:
            self.hass.bus.async_fire(
                EVENT_NOTIFICATION, {k: n.get(k) for k in _EVENT_FIELDS}
            )
            if n.get("kind") == "task_done":
                # The way back for a task proposed from HA: the answer itself,
                # keyed by task_id so an automation can wait for its own task.
                self.hass.bus.async_fire(
                    EVENT_TASK_DONE,
                    {
                        "task_id": n.get("task_id"),
                        "title": n.get("title"),
                        "answer": n.get("detail"),
                        "created_at": n.get("created_at"),
                    },
                )
        if fresh:
            await self._remember(newest)

    async def _remember(self, newest: str) -> None:
        self._seen = newest
        await self._store.async_save({"newest": newest})
