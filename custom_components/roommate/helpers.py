"""Small Home Assistant helpers shared by the room and manager logic."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

INVALID_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN}


def entity_is_on(hass: HomeAssistant, entity_id: str, target_state: str = STATE_ON) -> bool:
    """Check if an entity is in the target state (default: 'on')."""
    state = hass.states.get(entity_id)
    return state is not None and state.state == target_state


def get_numeric_state(hass: HomeAssistant, entity_id: str) -> float | None:
    """Read a numeric entity state, returning None if unavailable or invalid."""
    state = hass.states.get(entity_id)
    if state is None or state.state in INVALID_STATES:
        return None
    try:
        return float(state.state)
    except (ValueError, TypeError):
        return None


async def async_call_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    entity_id: str | list[str] | None = None,
    context: Context | None = None,
    **service_data: Any,
) -> None:
    """Call a service, logging (rather than raising) any failure."""
    try:
        await hass.services.async_call(
            domain,
            service,
            service_data=service_data or None,
            target={"entity_id": entity_id} if entity_id else None,
            context=context,
        )
    except Exception:
        _LOGGER.exception("Failed to call %s.%s for %s", domain, service, entity_id)


class Timer:
    """One-shot countdown on the event loop.

    Starting again restarts it, and the handle clears itself when it fires so
    `active` stays truthful without the owner bookkeeping it.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._unsub: CALLBACK_TYPE | None = None

    @property
    def active(self) -> bool:
        return self._unsub is not None

    def start(self, delay: float, action: Callable[[], None]) -> None:
        self.cancel()

        @callback
        def _fire(_now: datetime) -> None:
            self._unsub = None
            action()

        self._unsub = async_call_later(self._hass, delay, _fire)

    def cancel(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
