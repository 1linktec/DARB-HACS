"""Expose to DARB: the Home Assistant devices DARB may see, or see and control.

Jeff's decisions (6 Oct 2026): DARB has its OWN exposure list -- separate from
what HA's Assist agents see -- set in this integration's options, each entity
"see" or "see and control". This module:

- gives DARB's voice agent tools over exactly those entities (an LLM API of
  its own, `darb_home`), instead of HA's Assist exposure;
- sends the hub those entities and every change to them (planning context:
  who is home, doors, temperatures);
- collects the `ha_action` tasks the Bot Herder queues for Home Assistant,
  runs them and reports back.

Devices that open the house -- locks, alarm panels, garage doors, gates and
doors -- stay refused to an unidentified voice (guard.py), and the hub only
hands one over as a task inside a plan a person approved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import json
import logging
from typing import Any

from homeassistant.core import Context, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    floor_registry as fr,
)
from homeassistant.helpers import (
    llm,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.json import JSONEncoder
from homeassistant.util.json import JsonObjectType
import voluptuous as vol

from .api import DarbClient, DarbError
from .guard import GUARDED_CLASSES, GUARDED_DOMAINS

_LOGGER = logging.getLogger(__name__)

API_ID = "darb_home"
OPT_SEE = "see"
OPT_CONTROL = "control"
ACTION_POLL = timedelta(seconds=5)
FULL_PUSH = timedelta(minutes=10)
DROP_ATTRS = {
    "entity_picture",
    "icon",
    "supported_features",
    "friendly_name",
    "attribution",
}

# What DARB may ask for, per domain: action -> (service domain, service, value field).
ACTIONS: dict[str, dict[str, tuple[str, str, str | None]]] = {
    "light": {
        "on": ("light", "turn_on", None),
        "off": ("light", "turn_off", None),
        "toggle": ("light", "toggle", None),
        "set": ("light", "turn_on", "brightness_pct"),
    },
    "switch": {
        "on": ("switch", "turn_on", None),
        "off": ("switch", "turn_off", None),
        "toggle": ("switch", "toggle", None),
    },
    "input_boolean": {
        "on": ("input_boolean", "turn_on", None),
        "off": ("input_boolean", "turn_off", None),
        "toggle": ("input_boolean", "toggle", None),
    },
    "fan": {
        "on": ("fan", "turn_on", None),
        "off": ("fan", "turn_off", None),
        "toggle": ("fan", "toggle", None),
        "set": ("fan", "set_percentage", "percentage"),
    },
    "cover": {
        "open": ("cover", "open_cover", None),
        "close": ("cover", "close_cover", None),
        "stop": ("cover", "stop_cover", None),
        "set": ("cover", "set_cover_position", "position"),
    },
    "valve": {
        "open": ("valve", "open_valve", None),
        "close": ("valve", "close_valve", None),
    },
    "lock": {"lock": ("lock", "lock", None), "unlock": ("lock", "unlock", None)},
    "climate": {
        "on": ("climate", "turn_on", None),
        "off": ("climate", "turn_off", None),
        "set": ("climate", "set_temperature", "temperature"),
    },
    "media_player": {
        "on": ("media_player", "turn_on", None),
        "off": ("media_player", "turn_off", None),
        "play": ("media_player", "media_play", None),
        "pause": ("media_player", "media_pause", None),
        "stop": ("media_player", "media_stop", None),
        "set": ("media_player", "volume_set", "volume_level"),
    },
    "scene": {"on": ("scene", "turn_on", None)},
    "script": {"on": ("script", "turn_on", None)},
    "button": {"on": ("button", "press", None)},
    "alarm_control_panel": {
        "arm": ("alarm_control_panel", "alarm_arm_away", None),
        "on": ("alarm_control_panel", "alarm_arm_away", None),
        "off": ("alarm_control_panel", "alarm_disarm", None),
    },
}


# What models actually send for an action (found 6 Oct: the hub model asked for
# "turn_off", HA's own service name, and the tool refused it).
SYNONYMS = {
    "turn_on": "on",
    "turn on": "on",
    "switch_on": "on",
    "switch on": "on",
    "enable": "on",
    "activate": "on",
    "start": "on",
    "power_on": "on",
    "turn_off": "off",
    "turn off": "off",
    "switch_off": "off",
    "switch off": "off",
    "disable": "off",
    "deactivate": "off",
    "power_off": "off",
    "open_cover": "open",
    "raise": "open",
    "close_cover": "close",
    "lower": "close",
    "shut": "close",
    "stop_cover": "stop",
    "media_play": "play",
    "media_pause": "pause",
    "press": "on",
    "dim": "set",
    "brighten": "set",
    "set_brightness": "set",
    "brightness": "set",
    "set_level": "set",
    "set_temperature": "set",
    "set_position": "set",
    "set_percentage": "set",
    "volume": "set",
    "arm_away": "arm",
    "arm_home": "arm",
    "disarm": "off",
}


def normalise_action(action: str) -> str:
    a = (action or "").strip().lower()
    return SYNONYMS.get(a, SYNONYMS.get(a.replace(" ", "_"), a))


@dataclass
class Exposure:
    see: set[str]
    control: set[str]

    @classmethod
    def of(cls, options: dict) -> Exposure:
        control = set(options.get(OPT_CONTROL) or [])
        return cls(see=set(options.get(OPT_SEE) or []) | control, control=control)


def guarded(state: State | None, entity_id: str) -> bool:
    domain = entity_id.split(".", 1)[0]
    dclass = state.attributes.get("device_class") if state else None
    return domain in GUARDED_DOMAINS or (
        domain == "cover" and dclass in GUARDED_CLASSES
    )


def describe(
    hass: HomeAssistant, entity_id: str, exp: Exposure
) -> dict[str, Any] | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    ents, devs = er.async_get(hass), dr.async_get(hass)
    entry = ents.async_get(entity_id)
    area_id = entry.area_id if entry else None
    if (
        entry
        and not area_id
        and entry.device_id
        and (dev := devs.async_get(entry.device_id))
    ):
        area_id = dev.area_id
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    floor = (
        fr.async_get(hass).async_get_floor(area.floor_id)
        if area and area.floor_id
        else None
    )
    attrs = {k: v for k, v in state.attributes.items() if k not in DROP_ATTRS}
    attrs = json.loads(json.dumps(attrs, cls=JSONEncoder))
    return {
        "entity_id": entity_id,
        "name": state.name,
        "aliases": [a for a in (entry.aliases if entry else []) if isinstance(a, str)],
        "domain": state.domain,
        "device_class": state.attributes.get("device_class"),
        "area": area.name if area else None,
        "floor": floor.name if floor else None,
        "state": state.state,
        "attributes": attrs,
        "control": entity_id in exp.control,
        "guarded": guarded(state, entity_id),
        "last_changed": state.last_changed.isoformat(),
    }


def find(hass: HomeAssistant, exp: Exposure, name: str) -> str | None:
    """An exposed entity by id, name or alias (exact, then a unique partial name)."""
    q = (name or "").strip().lower()
    for lead in ("the ", "my ", "our "):
        if q.startswith(lead):
            q = q[len(lead) :]
    if not q:
        return None
    if q in exp.see:
        return q
    exact, partial = [], []
    ents = er.async_get(hass)
    for eid in exp.see:
        st = hass.states.get(eid)
        entry = ents.async_get(eid)
        names = {(st.name if st else "").lower()} | {
            a.lower() for a in (entry.aliases if entry else []) if isinstance(a, str)
        }
        if q in names:
            exact.append(eid)
        elif st and q in st.name.lower():
            partial.append(eid)
    if len(exact) == 1:
        return exact[0]
    if not exact and len(partial) == 1:
        return partial[0]
    return None


async def execute(
    hass: HomeAssistant,
    exp: Exposure,
    entity_id: str,
    action: str,
    value: Any,
    context: Context | None = None,
) -> tuple[bool, str, str | None]:
    """(ok, what happened, state afterwards). Only entities marked 'see and control'."""
    if entity_id not in exp.control:
        return False, f"{entity_id} is not exposed to DARB to control.", None
    domain = entity_id.split(".", 1)[0]
    act = normalise_action(action)
    spec = ACTIONS.get(domain, {}).get(act)
    if spec is None:
        allowed = ", ".join(ACTIONS.get(domain, {})) or "nothing"
        return False, f"A {domain} cannot '{act}'. It can: {allowed}.", None
    svc_domain, service, field = spec
    data: dict[str, Any] = {"entity_id": entity_id}
    if field:
        if value is None:
            return False, f"'{act}' needs a value ({field}).", None
        data[field] = value
    try:
        await hass.services.async_call(
            svc_domain, service, data, blocking=True, context=context
        )
    except (HomeAssistantError, vol.Invalid, ValueError) as e:
        return False, f"Home Assistant refused: {e}", None
    st = hass.states.get(entity_id)
    return True, f"{st.name if st else entity_id}: {act} done", st.state if st else None


# ------------------------------------------------------------------ LLM API --


class GetHomeState(llm.Tool):
    name = "GetHomeState"
    description = (
        "The state of Home Assistant devices exposed to DARB. "
        "Filter by device name, area or kind "
        "(light, cover, lock, sensor, person...); leave all empty for everything."
    )
    parameters = vol.Schema(
        {
            vol.Optional("name"): str,
            vol.Optional("area"): str,
            vol.Optional("kind"): str,
        }
    )

    def __init__(self, exp: Exposure) -> None:
        self.exp = exp

    async def async_call(
        self, hass, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        a = tool_input.tool_args
        out = []
        for eid in sorted(self.exp.see):
            d = describe(hass, eid, self.exp)
            if d is None:
                continue
            if a.get("kind") and d["domain"] != a["kind"]:
                continue
            if a.get("area") and (d["area"] or "").lower() != str(a["area"]).lower():
                continue
            if (
                a.get("name")
                and str(a["name"]).lower() not in (d["name"] or "").lower()
                and a["name"] != eid
            ):
                continue
            out.append(
                {
                    k: d[k]
                    for k in (
                        "name",
                        "entity_id",
                        "area",
                        "state",
                        "attributes",
                        "control",
                    )
                }
            )
        return {"devices": out[:60]}


class HomeAction(llm.Tool):
    name = "HomeAction"
    description = (
        "Change a Home Assistant device exposed to DARB to control. "
        "action: on, off, toggle, open, close, "
        "stop, lock, unlock, set, play, pause; "
        "value: a number for set (brightness %, position, "
        "temperature, volume 0-1)."
    )
    parameters = vol.Schema(
        {
            vol.Required("name"): str,
            vol.Required("action"): str,
            vol.Optional("value"): vol.Any(int, float),
        }
    )

    def __init__(self, exp: Exposure) -> None:
        self.exp = exp

    async def async_call(
        self, hass, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        a = tool_input.tool_args
        eid = find(hass, self.exp, str(a.get("name") or ""))
        if eid is None:
            return {
                "error": "unknown device",
                "error_text": f"No single exposed device is called {a.get('name')!r}.",
            }
        ok, said, state = await execute(
            hass,
            self.exp,
            eid,
            str(a.get("action") or ""),
            a.get("value"),
            llm_context.context,
        )
        return {"ok": ok, "result": said, "state": state}


@dataclass(slots=True, kw_only=True)
class DarbHomeApi(llm.API):
    """The devices exposed to DARB, as tools. Registered while the entry is loaded."""

    exposure: Callable[[], Exposure]

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        exp = self.exposure()
        lines = []
        for eid in sorted(exp.see):
            d = describe(self.hass, eid, exp)
            if d:
                lines.append(
                    f"- {d['name']} ({eid}, {d['area'] or 'no area'}): {d['state']}"
                    + (" [can change]" if d["control"] else "")
                )
        prompt = (
            "Home Assistant devices exposed to DARB "
            "(use GetHomeState for details, HomeAction to change "
            "the ones marked [can change]):\n"
            + ("\n".join(lines[:80]) or "(none exposed yet)")
        )
        return llm.APIInstance(
            api=self,
            api_prompt=prompt,
            llm_context=llm_context,
            tools=[GetHomeState(exp), HomeAction(exp)],
        )


# ---------------------------------------------------------------- the sync --


class HomeSync:
    """Pushes the exposed entities to the hub and runs the HA actions it queues."""

    def __init__(
        self, hass: HomeAssistant, client: DarbClient, exposure: Callable[[], Exposure]
    ) -> None:
        self.hass, self.client, self.exposure = hass, client, exposure
        self._unsubs: list[Callable[[], None]] = []
        self._dirty: set[str] = set()
        self._flush: asyncio.TimerHandle | None = None
        self._busy = False

    async def async_start(self) -> None:
        await self.push_all()
        self.track()
        self._unsubs.append(async_track_time_interval(self.hass, self._full, FULL_PUSH))
        self._unsubs.append(
            async_track_time_interval(self.hass, self._poll, ACTION_POLL)
        )

    def track(self) -> None:
        exp = self.exposure()
        if exp.see:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, sorted(exp.see), self._changed
                )
            )

    async def async_stop(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        if self._flush:
            self._flush.cancel()

    async def push_all(self) -> None:
        exp = self.exposure()
        ents = [d for eid in sorted(exp.see) if (d := describe(self.hass, eid, exp))]
        try:
            await self.client.async_push_entities(True, ents)
        except DarbError as e:
            _LOGGER.warning(
                "DARB: could not send the exposed devices to the hub: %s", e
            )

    @callback
    def _changed(self, event: Event) -> None:
        self._dirty.add(event.data["entity_id"])
        if self._flush is None:
            # A burst of changes (a scene) goes as one push, two seconds later.
            self._flush = self.hass.loop.call_later(
                2, lambda: self.hass.async_create_task(self._push_dirty())
            )

    async def _push_dirty(self) -> None:
        self._flush = None
        ids, self._dirty = self._dirty, set()
        exp = self.exposure()
        ents = [d for eid in sorted(ids) if (d := describe(self.hass, eid, exp))]
        if ents:
            try:
                await self.client.async_push_entities(False, ents)
            except DarbError as e:
                _LOGGER.debug("DARB: state push failed: %s", e)

    async def _full(self, _now=None) -> None:
        await self.push_all()

    async def _poll(self, _now=None) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            actions = await self.client.async_claim_actions()
            for a in actions:
                ok, said, state = await execute(
                    self.hass,
                    self.exposure(),
                    str(a.get("entity_id") or ""),
                    str(a.get("action") or ""),
                    a.get("value"),
                    Context(),
                )
                _LOGGER.info("DARB task %s: %s", a.get("id"), said)
                await self.client.async_action_result(str(a["id"]), ok, said, state)
        except DarbError as e:
            _LOGGER.debug("DARB: action poll failed: %s", e)
        finally:
            self._busy = False
