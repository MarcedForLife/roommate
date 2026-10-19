"""Roommate integration for Home Assistant."""

from __future__ import annotations

import copy
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ROOMS, DOMAIN, GLOBAL_TUNING_PARAMS, TUNING_PARAMS
from .manager import RoommateManager
from .schema import CONFIG_SCHEMA, OPTIONS_SCHEMA  # noqa: F401 (CONFIG_SCHEMA is read by HA)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type RoommateConfigEntry = ConfigEntry[RoommateManager]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import YAML configuration into a config entry."""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RoommateConfigEntry) -> bool:
    """Set up Roommate from a config entry."""
    manager = RoommateManager(hass, _validated_options(entry))
    entry.runtime_data = manager

    await manager.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    room_names = ", ".join(manager.rooms) or "(none)"
    _LOGGER.info("Roommate loaded with %d room(s): %s", len(manager.rooms), room_names)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RoommateConfigEntry) -> bool:
    """Unload a Roommate config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.shutdown()
    return unload_ok


def _validated_options(entry: ConfigEntry) -> dict[str, Any]:
    """Run the stored options through the schema so every default is filled in."""
    try:
        return OPTIONS_SCHEMA(dict(entry.options))
    except vol.Invalid as err:
        raise ConfigEntryError(f"Invalid Roommate configuration: {err}") from err


def _strip_tuning(config: dict[str, Any]) -> dict[str, Any]:
    """Copy of a validated config with tuning values removed, leaving only its structure."""
    stripped = copy.deepcopy(config)
    for key in GLOBAL_TUNING_PARAMS:
        stripped.pop(key, None)
    for room_config in stripped[CONF_ROOMS].values():
        for key in TUNING_PARAMS:
            room_config.pop(key, None)
    return stripped


async def _async_update_listener(hass: HomeAssistant, entry: RoommateConfigEntry) -> None:
    """Reload only when structural options changed; tuning-only edits apply in place."""
    manager = entry.runtime_data
    config = _validated_options(entry)
    if _strip_tuning(config) != _strip_tuning(manager.config):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    manager.apply_tuning(config)
