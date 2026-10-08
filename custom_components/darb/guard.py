"""Which Home Assistant tool calls DARB may run for an unidentified speaker.

A MIRROR of `guard_refusal` in the hub's config/toolserver/converse.py -- keep
the two identical. The hub vets every call before returning it; this copy runs
here, in HA, before Assist executes anything, so a hub that got it wrong (or
was told otherwise) still cannot unlock a door. Hub matching is convenience;
refusing here is the guarantee.
"""

from __future__ import annotations

import re
from typing import Any

APP_SAYS = (
    "I can't do that from a Home Assistant voice request. "
    "Use the Darb app, which can check who you are."
)
READ_PREFIXES = ("Get", "HassGet")
GUARDED_DOMAINS = {"lock", "alarm_control_panel"}
GUARDED_CLASSES = {"garage", "gate", "door"}
# A switch or button that opens the house shows up by NAME only ("Garage Door" on a relay):
# HA gives it no device class. These domains are guarded when the name says so.
NAMED_DOMAINS = {"switch", "button", "input_boolean", "script"}
OPENER_NAME = re.compile(
    r"\b(garage|gate|door|doors|lock|unlock|deadbolt|entry|entrance|alarm|disarm|shutter|opener)\b",
    re.I,
)


def _lower_set(v: Any) -> set[str]:
    if v is None:
        return set()
    items = v if isinstance(v, (list, tuple)) else [v]
    return {s for s in (str(x).strip().lower() for x in items) if s}


SECURING_ACTIONS = {"lock", "close", "arm", "arm_away", "arm_home", "arm_night"}
# HA offers each exposed script as its own tool with no arguments, so the checks below
# never see what it touches: a script whose name opens the house is refused.
SCRIPT_OPENS = re.compile(
    r"\b(open\w*|unlock\w*|disarm\w*|garage|gate\w*|door\w*|entry|entrance|shutter\w*|"
    r"alarm off|let in|buzz\w*)\b",
    re.I,
)


def _securing(base: str, domains: set) -> bool:
    """HA's own intents that make a guarded device safer: turning a lock "on"
    locks it; turning a cover (garage door, gate) "off" closes it."""
    domains = {d for d in domains if d}
    if not domains:
        return False
    if base == "HassTurnOn":
        return domains <= {"lock"}
    if base in ("HassTurnOff", "HassCloseCover"):
        return domains <= {"cover"}
    return False


def guard_refusal(name: str, args: dict, guarded: list[dict]) -> str | None:
    """Why an HA tool call may not run for an unidentified speaker, or None.

    Reads (GetLiveContext, HassGetState...) always run. A state change is
    refused when it names a guarded entity (by name or alias), targets a
    guarded domain or device class, or sweeps an area holding a guarded entity
    without narrowing to a domain that leaves it out. The same rule runs in the
    integration before HA executes anything."""
    # HA namespaces tools from several APIs: "intent__HassTurnOff".
    base = name.rpartition("__")[2]
    if base.startswith(READ_PREFIXES):
        return None
    args = args or {}
    # Making the house safer is always allowed (Jeff, 7 Oct): lock, close, arm.
    act = str(args.get("action") or "").strip().lower().replace(" ", "_")
    if base == "HomeAction" and act in SECURING_ACTIONS:
        return None
    if (
        not base.startswith("Hass")
        and base != "HomeAction"
        and SCRIPT_OPENS.search(base.replace("_", " "))
    ):
        return APP_SAYS
    names = _lower_set(args.get("name"))
    areas = _lower_set(args.get("area")) | _lower_set(args.get("floor"))
    domains = _lower_set(args.get("domain"))
    classes = _lower_set(args.get("device_class"))
    if (domains & GUARDED_DOMAINS or classes & GUARDED_CLASSES) and not _securing(
        base, domains
    ):
        return APP_SAYS
    for g in guarded or []:
        if names & _lower_set(
            [g.get("name"), g.get("entity_id"), *(g.get("aliases") or [])]
        ):
            if not _securing(base, {g.get("domain")}):
                return APP_SAYS
            continue
        in_area = areas & _lower_set([g.get("area"), g.get("floor")])
        if (
            not names
            and in_area
            and (not domains or g.get("domain") in domains)
            and not _securing(base, {g.get("domain")})
        ):
            return APP_SAYS
    return None
