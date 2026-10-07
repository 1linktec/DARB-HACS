"""
DARB (Distributed Autonomous Robotics Backbone) — Home Assistant integration.

Home Assistant owns the property; DARB owns the bodies (architecture §12). This
integration is how the two meet: each body becomes an HA device, DARB's
notifications become HA events, and HA can propose tasks and answer approvals.

The integration talks to DARB; DARB never talks to HA and holds no HA token. Every
request goes through the hub's tool server, which cannot actuate a body directly:
a task proposed here is validated against the body's safety envelope before the
hub dispatches it. One gate on actuation, not two.
"""

from __future__ import annotations

import logging

from homeassistant.components.homeassistant.exposed_entities import (
    async_listen_entity_updates,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .api import DarbClient, DarbError
from .const import (
    CONF_KEY,
    CONF_URL,
    DOMAIN,
    SERVICE_ANSWER_APPROVAL,
    SERVICE_CREATE_TASK,
)
from .coordinator import DarbConfigEntry, DarbCoordinator, DarbData
from .home import API_ID, DarbHomeApi, Exposure, HomeSync

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CONVERSATION,
    Platform.SENSOR,
]

# Configured through the UI only; this is what hassfest expects when an
# integration also defines async_setup (for its services).
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CREATE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("goal"): cv.string,
        vol.Required("kind"): vol.In(["fetch", "observe", "say", "show", "plan"]),
        vol.Optional("required_capabilities", default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional("priority", default=100): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1000)
        ),
    }
)

ANSWER_APPROVAL_SCHEMA = vol.Schema(
    {
        vol.Required("request_id"): cv.string,
        vol.Required("decision"): vol.In(["approved", "denied"]),
    }
)


def _entry(hass: HomeAssistant) -> DarbConfigEntry:
    """The one loaded hub (single_config_entry)."""
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError("DARB is not set up, or its hub is unreachable")
    return entries[0]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services once, not per entry — HA's current guidance, so they
    exist (and validate) even while the hub is unreachable."""

    async def create_task(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass)
        try:
            # Marked as asked from HA, so DARB delivers the result back here
            # (a darb_task_done event) rather than to a body or only the app.
            task = await entry.runtime_data.client.async_create_task(
                {**call.data, "requested_via": "ha"}
            )
        except DarbError as e:
            raise HomeAssistantError(f"DARB refused the task: {e}") from e
        await entry.runtime_data.coordinator.async_request_refresh()
        return {"task_id": task.get("id"), "state": task.get("state")}

    async def answer_approval(call: ServiceCall) -> None:
        entry = _entry(hass)
        try:
            await entry.runtime_data.client.async_answer_approval(
                call.data["request_id"], call.data["decision"]
            )
        except DarbError as e:
            # 409 "already approved" from a second phone lands here, worded by
            # the hub — exactly what the person tapping should be told.
            raise HomeAssistantError(f"DARB: {e}") from e
        await entry.runtime_data.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_TASK,
        create_task,
        schema=CREATE_TASK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ANSWER_APPROVAL,
        answer_approval,
        schema=ANSWER_APPROVAL_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DarbConfigEntry) -> bool:
    client = DarbClient(hass, entry.data[CONF_URL], entry.data[CONF_KEY])
    coordinator = DarbCoordinator(hass, client)
    # Raises ConfigEntryNotReady / ConfigEntryAuthFailed itself, so a hub that is
    # down at HA start is retried, and a revoked key asks to re-pair.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = DarbData(client=client, coordinator=coordinator)

    # DARB sees what HA exposes to Assist (Jeff, 7 Oct) -- its voice tools, the
    # hub's planning context, and HA actions all follow that one list.
    def exposure() -> Exposure:
        return Exposure.from_ha(hass)

    entry.runtime_data.unregister_api = llm.async_register_api(
        hass,
        DarbHomeApi(
            hass=hass,
            id=API_ID,
            name="DARB (devices exposed to Assist)",
            exposure=exposure,
        ),
    )
    entry.runtime_data.home = HomeSync(hass, client, exposure)
    await entry.runtime_data.home.async_start()
    home = entry.runtime_data.home

    # At HA's start, devices from slower integrations are not there yet: send
    # the full list again once HA has finished starting (measured 7 Oct: 9 of
    # 21 exposed devices reached the hub without this).
    async def _started(_hass: HomeAssistant) -> None:
        await home.async_exposure_changed()

    entry.async_on_unload(async_at_started(hass, _started))
    entry.async_on_unload(
        async_listen_entity_updates(
            hass,
            "conversation",
            lambda: hass.async_create_task(home.async_exposure_changed()),
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DarbConfigEntry) -> bool:
    data = entry.runtime_data
    if data.home:
        await data.home.async_stop()
    if data.unregister_api:
        data.unregister_api()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DarbConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Let a person delete a body's device once DARB has retired the body.

    Not while it is still in the fleet: it would come straight back on the next
    poll, which looks like the delete button is broken.
    """
    live = {
        f"body_{b['id']}"
        for b in (entry.runtime_data.coordinator.data or {}).get("bodies", [])
    }
    return not any(
        domain == DOMAIN and (ident == "hub" or ident in live)
        for domain, ident in device.identifiers
    )
