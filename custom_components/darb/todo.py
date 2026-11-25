"""DARB's shopping list as a Home Assistant to-do list (hub 25 Nov 2026 or later).

The list is DARB's own (the household's inventory and groceries: the handheld
scanner, the Darb app, voice). Here it is a to-do list: what DARB adds shows up,
what is added or ticked off here goes to DARB. A hub without the inventory
answers 404, and the list then stays empty and unavailable.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DarbClient, DarbError
from .coordinator import DarbConfigEntry
from .entity import HUB_DEVICE_ID

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant, entry: DarbConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [DarbShoppingList(entry.runtime_data.client)], update_before_add=True
    )


def _item(line: dict[str, Any], done: bool) -> TodoItem:
    qty = line.get("quantity") or 1
    unit = line.get("unit")
    extra = []
    if qty != 1 or unit:
        extra.append(f"{qty:g}{' ' + unit if unit else ''}")
    if line.get("added_by"):
        extra.append("added by " + str(line["added_by"]).split(" on ")[0])
    return TodoItem(
        uid=line["id"],
        summary=line["name"],
        status=TodoItemStatus.COMPLETED if done else TodoItemStatus.NEEDS_ACTION,
        description=" · ".join(extra) or None,
    )


class DarbShoppingList(TodoListEntity):
    """The household's shopping list, kept by DARB."""

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, client: DarbClient) -> None:
        self._client = client
        self._attr_unique_id = "hub_shopping_list"
        self._attr_device_info = DeviceInfo(identifiers={HUB_DEVICE_ID})
        self._attr_todo_items = []

    async def async_update(self) -> None:
        try:
            open_ = await self._client.async_shopping(done=False)
            bought = await self._client.async_shopping(done=True)
        except DarbError as e:
            if self._attr_available:
                _LOGGER.info("DARB shopping list unavailable: %s", e)
            self._attr_available = False
            return
        self._attr_available = True
        # the last few ticked off stay visible as completed, as on any list
        self._attr_todo_items = [_item(x, False) for x in open_] + [
            _item(x, True) for x in bought[:15]
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        await self._client.async_shopping_add(item.summary or "")
        await self.async_update_ha_state(force_refresh=True)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        was = next((x for x in self._attr_todo_items or [] if x.uid == item.uid), None)
        if was and item.summary and item.summary != was.summary:
            # a renamed line: DARB keeps the new name as a new line
            await self._client.async_shopping_delete(item.uid)
            await self._client.async_shopping_add(item.summary)
        elif item.status is not None:
            await self._client.async_shopping_done(
                item.uid, item.status == TodoItemStatus.COMPLETED
            )
        await self.async_update_ha_state(force_refresh=True)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            try:
                await self._client.async_shopping_delete(uid)
            except DarbError as e:
                _LOGGER.debug("shopping line %s not deleted: %s", uid, e)
        await self.async_update_ha_state(force_refresh=True)
