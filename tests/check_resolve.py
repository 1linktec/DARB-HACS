"""Checks the area-aware name resolution against a real Home Assistant core
(no running HA needed). Run inside the HA image with the integration mounted:

    docker run --rm -v $PWD:/w -w /w ghcr.io/home-assistant/home-assistant:2026.9.4 \
        python tests/check_resolve.py
"""

import asyncio
import sys
import tempfile

from homeassistant.core import HomeAssistant, ServiceCall
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
    label_registry as lr,
)

sys.path.insert(0, "custom_components")
from darb.home import Exposure, act, resolve

FAILS = []


def check(what, got, want):
    ok = got == want
    print(("ok  " if ok else "FAIL"), what, "->", got, "" if ok else f"(wanted {want})")
    if not ok:
        FAILS.append(what)


async def main():
    hass = HomeAssistant(tempfile.mkdtemp())
    from homeassistant import loader
    from homeassistant.helpers import category_registry as cr
    from homeassistant.helpers import entity, frame, translation

    loader.async_setup(hass)
    entity.async_setup(hass)
    frame.async_setup(hass)
    translation.async_setup(hass)
    dr.async_setup(hass)
    for reg in (lr, fr, cr, ar, dr, er):
        await reg.async_load(hass)
    areas = ar.async_get(hass)
    living = areas.async_create("Living Room", aliases={"lounge"})
    kitchen = areas.async_create("Gail's Kitchen")
    ents = er.async_get(hass)

    def add(eid, name, area=None, state="on"):
        domain, oid = eid.split(".")
        e = ents.async_get_or_create(domain, "test", oid, suggested_object_id=oid)
        if area:
            ents.async_update_entity(e.entity_id, area_id=area.id)
        hass.states.async_set(eid, state, {"friendly_name": name})

    add("light.livingroom_lights", "Livingroom Lights", living)
    add("light.overhead_living_room_light", "Overhead living room light", living)
    add("light.gails_living_room_lamp", "Gails living room lamp", living)
    add("switch.recroom_switch_1", "Recroom switch 1", living, "off")
    add("light.gails_kitchen_wall_left", "Gails kitchen wall left", kitchen)
    add("light.gails_kitchen_wall_right", "Gails kitchen wall right", kitchen)
    add("light.back_yard", "Back yard")
    add("sensor.greenhouse_current_temperature", "Greenhouse temperature", None, "21")
    see = {s.entity_id for s in hass.states.async_all()}
    exp = Exposure(see=see, control={e for e in see if not e.startswith("sensor.")})

    lr_lights = [
        "light.gails_living_room_lamp",
        "light.livingroom_lights",
        "light.overhead_living_room_light",
    ]
    check("exact name", resolve(hass, exp, "Back yard"), ["light.back_yard"])
    check(
        "area wins over a spaceless name",
        resolve(hass, exp, "living room lights"),
        lr_lights,
    )
    check(
        "name, spaces differ",
        resolve(hass, exp, "livingroom lights"),
        ["light.livingroom_lights"],
    )
    check("area + kind", resolve(hass, exp, "the living room lamps"), lr_lights)
    check("area alias + kind", resolve(hass, exp, "lounge lights"), lr_lights)
    check(
        "area only",
        resolve(hass, exp, "living room"),
        [*lr_lights, "switch.recroom_switch_1"],
    )
    check(
        "area with apostrophe",
        resolve(hass, exp, "gails kitchen lights"),
        ["light.gails_kitchen_wall_left", "light.gails_kitchen_wall_right"],
    )
    check("all the lights", len(resolve(hass, exp, "all the lights")), 6)
    check("bare 'lights' is ambiguous", resolve(hass, exp, "lights"), [])
    check("entity id", resolve(hass, exp, "light.back_yard"), ["light.back_yard"])
    check(
        "unique partial",
        resolve(hass, exp, "overhead"),
        ["light.overhead_living_room_light"],
    )
    check("nothing", resolve(hass, exp, "garage"), [])
    add("sensor.living_room_temperature", "Living room temperature", living, "20")
    exp.see.add("sensor.living_room_temperature")
    check(
        "an area never includes sensors",
        "sensor.living_room_temperature" in resolve(hass, exp, "living room"),
        False,
    )

    calls = []

    async def svc(call: ServiceCall):
        calls.extend(
            call.data["entity_id"]
            if isinstance(call.data["entity_id"], list)
            else [call.data["entity_id"]]
        )

    hass.services.async_register("light", "turn_off", svc)
    hass.services.async_register("homeassistant", "turn_off", svc)
    hass.services.async_register("switch", "turn_off", svc)
    ok, _said, _state, say = await act(hass, exp, "the lounge lights", "off", None)
    check(
        "act on an area",
        (ok, sorted(calls), say),
        (True, lr_lights, "Lounge lights off"),
    )
    ok, _said, _state, say = await act(hass, exp, "garage", "off", None)
    check("act on nothing", (ok, say), (False, None))
    await hass.async_stop()
    print("FAILED:", FAILS if FAILS else "none")
    return 1 if FAILS else 0


sys.exit(asyncio.run(main()))
