"""Number platform for Roommate tuning parameters."""

from __future__ import annotations

import copy

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoommateConfigEntry
from .const import (
    CONF_BED_EXIT_DELAY,
    CONF_BED_RETURN_TIMEOUT,
    CONF_DIM_BRIGHTNESS,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_RECENTLY_ON_THRESHOLD,
    CONF_ROOMS,
    CONF_SLEEP_LIGHT_TRANSITION,
    CONF_TRANSITION_DIM,
    CONF_WAKE_TRANSITION,
    GLOBAL_TUNING_PARAMS,
    TUNING_PARAMS,
    TuningParam,
)
from .entity import GlobalEntity, RoomEntity
from .manager import RoommateManager
from .room import Room

# Tuning params that only apply to rooms with a bed sensor
BED_TUNING_KEYS = {
    CONF_DIM_BRIGHTNESS,
    CONF_RECENTLY_ON_THRESHOLD,
    CONF_TRANSITION_DIM,
    CONF_BED_EXIT_DELAY,
    CONF_BED_RETURN_TIMEOUT,
    CONF_WAKE_TRANSITION,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoommateConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    entities: list[NumberEntity] = []

    for room in manager.rooms.values():
        for key in TUNING_PARAMS:
            if key in BED_TUNING_KEYS and not room.has_bed_sensor:
                continue
            if key == CONF_ILLUMINANCE_THRESHOLD and not room.illuminance_sensor_id:
                continue
            entities.append(RoomTuningNumber(room, key, entry))

    if manager.sleep_lights:
        entities.append(GlobalSettingNumber(manager, entry, CONF_SLEEP_LIGHT_TRANSITION))
    if manager.illuminance_sensor_id:
        entities.append(GlobalSettingNumber(manager, entry, CONF_ILLUMINANCE_THRESHOLD))

    async_add_entities(entities)


class TuningNumber(NumberEntity):
    """Config number whose range and label come from a TuningParam."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def _apply_param(self, param: TuningParam) -> None:
        self._attr_name = param.name
        self._attr_native_min_value = param.minimum
        self._attr_native_max_value = param.maximum
        self._attr_native_step = param.step
        self._attr_native_unit_of_measurement = param.unit


class RoomTuningNumber(RoomEntity, TuningNumber):
    """Adjustable tuning parameter for a room."""

    def __init__(self, room: Room, key: str, entry: ConfigEntry) -> None:
        super().__init__(room, key)
        self._key = key
        self._entry = entry
        self._apply_param(TUNING_PARAMS[key])

    @property
    def native_value(self) -> float:
        return self._room.config[self._key]

    async def async_set_native_value(self, value: float) -> None:
        """Update the tuning param in memory and persist without reloading."""
        int_value = int(value)
        self._room.config[self._key] = int_value

        options = copy.deepcopy(dict(self._entry.options))
        options[CONF_ROOMS][self._room.name][self._key] = int_value
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()


class GlobalSettingNumber(GlobalEntity, TuningNumber):
    """Adjustable global setting on the Roommate device."""

    def __init__(self, manager: RoommateManager, entry: ConfigEntry, key: str) -> None:
        super().__init__(manager, key)
        self._key = key
        self._entry = entry
        self._apply_param(GLOBAL_TUNING_PARAMS[key])

    @property
    def native_value(self) -> float:
        return self._manager.config[self._key]

    async def async_set_native_value(self, value: float) -> None:
        """Update the global setting and persist without reloading."""
        coerced = int(value) if self._attr_native_step == 1 else float(value)
        self._manager.config[self._key] = coerced

        options = {**self._entry.options, self._key: coerced}
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
