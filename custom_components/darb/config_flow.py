"""Config flow for DARB: discover the hub, pair with a code from the Darb app.

An admin taps Settings > Phones > Connect Home Assistant in the Darb app and
gets a one-time code (XXXXX-XXXXX, 15 minutes). Entered here, it is traded with
the hub for a key issued to Home Assistant alone -- no key is ever shown on a
phone. The older routes still work: the line `sudo darb-pair --ha` prints, or a
bare key. When the hub is found by zeroconf the address is already known, so
only the code is asked for.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .api import (
    DarbAuthError,
    DarbClient,
    DarbCodeError,
    DarbError,
    async_redeem_code,
    parse_code,
    parse_pairing,
)
from .const import CONF_KEY, CONF_PAIRING, CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Plain text: the usual entry is a one-time code, and a typo is easier to
# spot when it can be seen. (A pasted darb-pair line or key works here too.)
PAIRING_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
)


async def _check(hass, url: str, key: str) -> tuple[str | None, str]:
    """Try the key against the hub. (error_key, detail), or (None, "")."""
    try:
        await DarbClient(hass, url, key).async_fleet()
    except DarbAuthError as e:
        return "invalid_auth", str(e)
    except DarbError as e:
        _LOGGER.warning("DARB hub at %s unreachable: %s", url, e)
        return "cannot_connect", str(e)
    return None, ""


async def _key_from(
    hass, url: str | None, text: str
) -> tuple[str | None, str | None, str]:
    """(key, error_key, detail) from whatever was entered: an app code (traded
    for a key now), a darb-pair line, or a bare key."""
    _, key = parse_pairing(text)
    if key:
        return key, None, ""
    code = parse_code(text)
    if not code:
        return None, "no_key", ""
    if not url:
        return None, "no_url", ""
    try:
        return await async_redeem_code(hass, url, code), None, ""
    except DarbCodeError:
        return None, "code_used", ""
    except DarbError as e:
        _LOGGER.warning("DARB hub at %s unreachable: %s", url, e)
        return None, "cannot_connect", str(e)


class DarbConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._url: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup: the app's code plus the hub address (or a darb-pair line)."""
        errors: dict[str, str] = {}
        detail = ""
        data = user_input or {}
        if user_input is not None:
            url, _ = parse_pairing(user_input[CONF_PAIRING])
            url = (user_input.get(CONF_URL) or "").strip().rstrip("/") or url
            key, err, detail = await _key_from(self.hass, url, user_input[CONF_PAIRING])
            if err in ("no_key", "code_used"):
                errors[CONF_PAIRING] = err
            elif err == "no_url":
                errors[CONF_URL] = err
            elif err:
                errors["base"] = err
            else:
                err, detail = await _check(self.hass, url, key)
                if err:
                    errors["base"] = err
                else:
                    return self.async_create_entry(
                        title="DARB", data={CONF_URL: url, CONF_KEY: key}
                    )
        schema = vol.Schema(
            {
                vol.Required(CONF_PAIRING): PAIRING_SELECTOR,
                vol.Optional(CONF_URL, default=data.get(CONF_URL, "")): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"detail": detail},
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """The hub announced itself as _darb._tcp."""
        url = f"http://{discovery_info.host}:{discovery_info.port}"
        # Already set up: if the hub's address changed, follow it rather than
        # leaving the entry pointed at the old one. That is the point of
        # discovery — nobody should have to retype an address (architecture §6).
        for entry in self._async_current_entries():
            if entry.data.get(CONF_URL) != url:
                _LOGGER.info("DARB hub moved to %s; updating", url)
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_URL: url}
                )
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_abort(reason="already_configured")
        self._url = url
        self.context["title_placeholders"] = {"host": discovery_info.host}
        return await self.async_step_pair()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Hub found by discovery: only the code is needed."""
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            key, err, detail = await _key_from(
                self.hass, self._url, user_input[CONF_PAIRING]
            )
            if err in ("no_key", "code_used"):
                errors[CONF_PAIRING] = err
            elif err:
                errors["base"] = err
            else:
                err, detail = await _check(self.hass, self._url, key)
                if err:
                    errors["base"] = err
                else:
                    return self.async_create_entry(
                        title="DARB", data={CONF_URL: self._url, CONF_KEY: key}
                    )
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required(CONF_PAIRING): PAIRING_SELECTOR}),
            errors=errors,
            description_placeholders={"url": self._url, "detail": detail},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The stored key stopped being accepted — revoked, or the hub reset."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh code, keeping the address that works."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            key, err, detail = await _key_from(
                self.hass, entry.data[CONF_URL], user_input[CONF_PAIRING]
            )
            if err in ("no_key", "code_used"):
                errors[CONF_PAIRING] = err
            elif err:
                errors["base"] = err
            else:
                err, detail = await _check(self.hass, entry.data[CONF_URL], key)
                if err:
                    errors["base"] = err
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_KEY: key}
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PAIRING): PAIRING_SELECTOR}),
            errors=errors,
            description_placeholders={"url": entry.data[CONF_URL], "detail": detail},
        )
