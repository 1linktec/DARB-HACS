"""Which Home Assistant tool calls DARB may run for an unidentified speaker.

A MIRROR of `guard_refusal` in the hub's config/toolserver/converse.py -- keep
the two identical. The hub vets every call before returning it; this copy runs
here, in HA, before Assist executes anything, so a hub that got it wrong (or
was told otherwise) still cannot unlock a door. Hub matching is convenience;
refusing here is the guarantee.
"""

from __future__ import annotations

from typing import Any

APP_SAYS = (
    "I can't do that from a Home Assistant voice request. "
    "Use the Darb app, which can check who you are."
)
READ_PREFIXES = ("Get", "HassGet")
GUARDED_DOMAINS = {"lock", "alarm_control_panel"}
GUARDED_CLASSES = {"garage", "gate", "door"}


def _lower_set(v: Any) -> set[str]:
    if v is None:
        return set()
    items = v if isinstance(v, (list, tuple)) else [v]
    return {s for s in (str(x).strip().lower() for x in items) if s}


def guard_refusal(name: str, args: dict, guarded: list[dict]) -> str | None:
    """Why an HA tool call may not run for an unidentified speaker, or None.

    Reads (GetLiveContext, HassGetState...) always run. A state change is
    refused when it names a guarded entity (by name or alias), targets a
    guarded domain or device class, or sweeps an area holding a guarded entity
    without narrowing to a domain that leaves it out. The same rule runs in the
    integration before HA executes anything."""
    # HA namespaces tools from several APIs: "intent__HassTurnOff".
    if name.rpartition("__")[2].startswith(READ_PREFIXES):
        return None
    args = args or {}
    names = _lower_set(args.get("name"))
    areas = _lower_set(args.get("area")) | _lower_set(args.get("floor"))
    domains = _lower_set(args.get("domain"))
    classes = _lower_set(args.get("device_class"))
    if domains & GUARDED_DOMAINS or classes & GUARDED_CLASSES:
        return APP_SAYS
    for g in guarded or []:
        if names & _lower_set([g.get("name"), *(g.get("aliases") or [])]):
            return APP_SAYS
        in_area = areas & _lower_set([g.get("area"), g.get("floor")])
        if not names and in_area and (not domains or g.get("domain") in domains):
            return APP_SAYS
    return None
