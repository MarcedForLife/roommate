"""Roommate integration for Home Assistant."""

from __future__ import annotations

import copy
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BED,
    CONF_FANS,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_PERSONS,
    CONF_ROOMS,
    CONF_SENSORS,
    CONF_SLEEP_LIGHT_TRANSITION,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_MODES,
    CONF_SPEAKERS,
    DEFAULT_ILLUMINANCE_THRESHOLD,
    DEFAULT_SLEEP_LIGHT_TRANSITION,
    DOMAIN,
    TUNING_PARAMS,
)
from .manager import RoommateManager
from .schema import CONFIG_SCHEMA  # noqa: F401 (used by HA)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]


def _apply_defaults(config: dict[str, Any]) -> dict[str, Any]:
    """Ensure top-level config keys exist with sensible defaults."""
    config.setdefault(CONF_ROOMS, {})
    config.setdefault(CONF_SLEEP_LIGHTS, [])
    config.setdefault(CONF_SLEEP_MODES, [])
    config.setdefault(CONF_ILLUMINANCE_THRESHOLD, DEFAULT_ILLUMINANCE_THRESHOLD)
    config.setdefault(CONF_SLEEP_LIGHT_TRANSITION, DEFAULT_SLEEP_LIGHT_TRANSITION)
    for room_config in config[CONF_ROOMS].values():
        room_config.setdefault(CONF_FANS, [])
        room_config.setdefault(CONF_SPEAKERS, [])
        bed = room_config.get(CONF_SENSORS, {}).get(CONF_BED)
        if bed:
            bed.setdefault(CONF_PERSONS, [])
        for key, (default, _low, _high, _unit) in TUNING_PARAMS.items():
            room_config.setdefault(key, default)
    return config


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import YAML configuration into a config entry."""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Roommate from a config entry."""
    config = _apply_defaults(copy.deepcopy(dict(entry.options)))

    manager = RoommateManager(hass, config)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"manager": manager}

    await manager.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    room_names = ", ".join(manager.rooms) or "(none)"
    _LOGGER.info("Roommate loaded with %d room(s): %s", len(manager.rooms), room_names)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Roommate config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        data["manager"].shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
