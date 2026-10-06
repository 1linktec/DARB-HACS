"""DARB as a Home Assistant conversation agent.

Pick "DARB" as the conversation agent of an Assist pipeline and everything said
to that pipeline -- a Voice PE, a satellite, the HA app -- reaches DARB: one
brain for the robots and the house (Jeff, 6 Oct).

DARB still holds no HA token. Each turn this entity sends the hub HA's chat log,
the tools HA's Assist API offers, and the exposed entities that open the house
(locks, alarm panels, garage doors, gates, doors) among the devices exposed to
DARB. The hub answers with one model
turn. Its own lookups come back already run (`external`, with results, so HA's
chat log and debug trace show them); HA's tool calls come back for Assist to run
here -- so only entities exposed to Assist are reachable, and HA's permissions
apply. Then the log goes back to the hub, until a turn has no tool calls.

The speaker is not identified, so a state change to a guarded entity is refused
-- by the hub, and again here before Assist runs it (guard.py).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import logging
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    intent,
    llm,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

try:  # HA 2026.x converts tool schemas with probatio; earlier with voluptuous_openapi
    from probatio import to_openapi
except ImportError:  # pragma: no cover
    from voluptuous_openapi import convert as to_openapi

from .api import DarbError
from .const import DOMAIN
from .coordinator import DarbConfigEntry
from .entity import HUB_DEVICE_ID
from .guard import guard_refusal
from .home import API_ID, Exposure, describe

_LOGGER = logging.getLogger(__name__)

# Rounds of tool use per thing said (each round is one hub turn).
MAX_ROUNDS = 8

# HA's default prompt opens "You are a voice assistant for Home Assistant";
# DARB has its own. HA's part is only what the home is called -- the Assist
# API adds its own instructions and the exposed entities after it.
HA_PROMPT = "The home is called {{ ha_name }}."


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DarbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([DarbConversationEntity(entry)])


def guarded_entities(hass: HomeAssistant, exp: Exposure) -> list[dict[str, Any]]:
    """Entities exposed to DARB to control that open the house, with every name
    a person might use (guard.py refuses them to an unidentified voice)."""
    out = []
    for eid in sorted(exp.control):
        d = describe(hass, eid, exp)
        if d and d["guarded"]:
            out.append(
                {
                    k: d[k]
                    for k in (
                        "entity_id",
                        "name",
                        "aliases",
                        "domain",
                        "device_class",
                        "area",
                        "floor",
                    )
                }
            )
    return out


def _as_message(c: Any) -> dict[str, Any]:
    if isinstance(c, conversation.SystemContent):
        return {"role": "system", "content": c.content}
    if isinstance(c, conversation.UserContent):
        return {"role": "user", "content": c.content}
    if isinstance(c, conversation.AssistantContent):
        return {
            "role": "assistant",
            "content": c.content or "",
            "tool_calls": [
                {"id": t.id, "name": t.tool_name, "args": t.tool_args}
                for t in c.tool_calls or ()
            ],
        }
    return {"role": "tool", "name": c.tool_name, "result": c.tool_result}


class DarbConversationEntity(conversation.ConversationEntity):
    """The DARB conversation agent, on the DARB hub's device."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, entry: DarbConfigEntry) -> None:
        self.entry = entry
        self._attr_unique_id = "hub_conversation"
        self._attr_device_info = dr.DeviceInfo(identifiers={HUB_DEVICE_ID})

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self.entry, self)

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                API_ID,
                HA_PROMPT,
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        api = chat_log.llm_api
        tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "parameters": to_openapi(
                    t.parameters, custom_serializer=api.custom_serializer
                ),
            }
            for t in (api.tools if api else [])
        ]
        guarded = guarded_entities(self.hass, Exposure.of(dict(self.entry.options)))
        user = None
        if user_input.context.user_id:
            u = await self.hass.auth.async_get_user(user_input.context.user_id)
            user = u.name if u else None
        speaker = {
            "ha_user": user,
            "device_id": user_input.device_id,
            "satellite_id": user_input.satellite_id,
        }
        client = self.entry.runtime_data.client

        for _ in range(MAX_ROUNDS):
            try:
                reply = await client.async_converse(
                    {
                        "messages": [_as_message(c) for c in chat_log.content],
                        "ha_tools": tools,
                        "guarded": guarded,
                        "conversation_id": chat_log.conversation_id,
                        "language": user_input.language,
                        "speaker": speaker,
                    }
                )
            except DarbError as err:
                _LOGGER.warning("DARB hub did not answer: %s", err)
                response = intent.IntentResponse(language=user_input.language)
                response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    "I can't reach the DARB hub right now.",
                )
                return conversation.ConversationResult(
                    response=response, conversation_id=chat_log.conversation_id
                )
            async for _content in chat_log.async_add_delta_content_stream(
                self.entity_id, self._deltas(reply, guarded)
            ):
                pass
            if not chat_log.unresponded_tool_results:
                break

        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _deltas(
        self, reply: dict[str, Any], guarded: list[dict]
    ) -> AsyncGenerator[dict[str, Any]]:
        """One hub turn as chat-log deltas: the assistant message (HA runs the
        calls not marked external), then the results the hub already has."""
        calls, done = [], []
        for c in reply.get("tool_calls") or []:
            name, args = str(c.get("name") or ""), c.get("args") or {}
            external, result = bool(c.get("external")), c.get("result")
            if not external and (why := guard_refusal(name, args, guarded)):
                # The hub let it through; this side does not.
                _LOGGER.warning(
                    "refused %s(%s) from the hub: guarded entity", name, args
                )
                external, result = True, {"error": "refused", "error_text": why}
            calls.append(
                llm.ToolInput(
                    tool_name=name,
                    tool_args=args,
                    id=str(c.get("id")),
                    external=external,
                )
            )
            if external:
                done.append(
                    {
                        "role": "tool_result",
                        "tool_call_id": str(c.get("id")),
                        "tool_name": name,
                        "tool_result": result
                        if isinstance(result, dict)
                        else {"result": result},
                    }
                )
        yield {
            "role": "assistant",
            "content": reply.get("content") or None,
            "tool_calls": calls or None,
        }
        for d in done:
            yield d
