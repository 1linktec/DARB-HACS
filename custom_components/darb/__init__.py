"""
DARB — Home Assistant integration.

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

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

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
            task = await entry.runtime_data.client.async_create_task(dict(call.data))
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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DarbConfigEntry) -> bool:
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
