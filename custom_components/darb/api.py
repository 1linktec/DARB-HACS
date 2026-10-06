"""Async client for the DARB hub's tool server (X-API-Key auth)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_APPROVALS,
    API_CONVERSE,
    API_FLEET,
    API_NOTIFICATIONS,
    API_TASKS,
    KEY_PATTERN,
)

_LOGGER = logging.getLogger(__name__)


class DarbError(Exception):
    """Any DARB API failure."""


class DarbAuthError(DarbError):
    """The key was rejected.

    Separate from the general error because the two need opposite handling: a
    network blip should be retried, a rejected key never will be. This one is
    what turns a revoked key into a "re-pair" prompt instead of entities that are
    unavailable forever.
    """


def parse_pairing(text: str) -> tuple[str | None, str | None]:
    """Pull (hub_url, key) out of whatever was pasted.

    Accepts the whole line `sudo darb-pair --ha` prints
    (`http://<hub>:8080/app/#k=<key>`), the phone's older `#h=<host>&k=<key>`
    form, or a bare key. Either part is None if it is not there. The same
    tolerance as the Darb app's key field: people paste what they were given,
    and editing a URL down to 64 characters is how a typo gets in.
    """
    text = (text or "").strip()
    url = None
    if "://" in text:
        parts = urlsplit(text)
        if parts.scheme in ("http", "https") and parts.netloc:
            url = f"{parts.scheme}://{parts.netloc}"
    key = None
    m = re.search(rf"(?:^|[#&?]k=)({KEY_PATTERN})(?:$|[&\s])", text)
    if m:
        key = m.group(1).lower()
    elif re.fullmatch(KEY_PATTERN, text):
        key = text.lower()
    return url, key


class DarbClient:
    def __init__(self, hass: HomeAssistant, url: str, key: str) -> None:
        self._session = async_get_clientsession(hass)
        self._url = url.rstrip("/")
        self._headers = {"X-API-Key": key}

    @property
    def url(self) -> str:
        return self._url

    async def _request(
        self, method: str, path: str, timeout: float = 10, **kw: Any
    ) -> Any:
        try:
            async with self._session.request(
                method,
                self._url + path,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                **kw,
            ) as r:
                if r.status == 401:
                    raise DarbAuthError("the hub rejected this key")
                if r.status >= 400:
                    # The hub explains refusals (409 "already approved", 422 a bad
                    # task) in `detail`; pass that on rather than a bare status.
                    try:
                        detail = (await r.json()).get("detail")
                    except Exception:
                        detail = None
                    raise DarbError(f"{r.status}: {detail or r.reason}")
                return await r.json()
        except DarbError:
            raise
        except Exception as e:  # network / timeout / non-JSON
            raise DarbError(str(e) or type(e).__name__) from e

    async def async_fleet(self) -> dict:
        return await self._request("GET", API_FLEET)

    async def async_notifications(self, limit: int = 20) -> list[dict]:
        return await self._request("GET", API_NOTIFICATIONS, params={"limit": limit})

    async def async_approvals(self) -> list[dict]:
        return await self._request("GET", API_APPROVALS)

    async def async_answer_approval(self, request_id: str, decision: str) -> Any:
        return await self._request(
            "POST", f"{API_APPROVALS}/{request_id}", json={"decision": decision}
        )

    async def async_create_task(self, task: dict) -> dict:
        return await self._request("POST", API_TASKS, json=task)

    async def async_converse(self, turn: dict) -> dict:
        # One model turn on the hub; a small model with tools can take a while.
        return await self._request("POST", API_CONVERSE, timeout=75, json=turn)
