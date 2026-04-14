"""Number platform for Roommate tuning parameters."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BED_EXIT_DELAY,
    CONF_BED_RETURN_TIMEOUT,
    CONF_DIM_BRIGHTNESS,
    CONF_ILLUMINANCE_SENSOR,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_RECENTLY_ON_THRESHOLD,
    CONF_ROOMS,
    CONF_SLEEP_LIGHT_TRANSITION,
    CONF_TRANSITION_DIM,
    DOMAIN,
    TUNING_PARAMS,
)
from .manager import RoommateManager
from .room import Room

# Tuning params that only apply to rooms with a bed sensor
BED_TUNING_KEYS = {
    CONF_DIM_BRIGHTNESS,
    CONF_RECENTLY_ON_THRESHOLD,
    CONF_TRANSITION_DIM,
    CONF_BED_EXIT_DELAY,
    CONF_BED_RETURN_TIMEOUT,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    manager: RoommateManager = data["manager"]
    entities: list[NumberEntity] = []

    for room in manager.rooms.values():
        for key in TUNING_PARAMS:
            if key in BED_TUNING_KEYS and not room.has_bed_sensor:
                continue
            entities.append(RoomTuningNumber(room, key, entry))

    if manager.sleep_lights:
        entities.append(
            GlobalSettingNumber(
                manager,
                entry,
                key=CONF_SLEEP_LIGHT_TRANSITION,
                name="Sleep Light Transition",
                low=0,
                high=30,
                unit="s",
            )
        )

    if entry.options.get(CONF_ILLUMINANCE_SENSOR):
        entities.append(
            GlobalSettingNumber(
                manager,
                entry,
                key=CONF_ILLUMINANCE_THRESHOLD,
                name="Illuminance Threshold",
                low=0,
                high=100000,
                step=100,
                unit="lx",
            )
        )

    async_add_entities(entities)


class RoomTuningNumber(NumberEntity):
    """Adjustable tuning parameter for a room."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, room: Room, key: str, entry: ConfigEntry) -> None:
        self._room = room
        self._key = key
        self._entry = entry

        _default, low, high, unit, name = TUNING_PARAMS[key]
        self._attr_unique_id = f"{DOMAIN}_{room.name}_{key}"
        self._attr_name = name
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._room.name)})

    @property
    def native_value(self) -> float:
        return self._room.config[self._key]

    async def async_set_native_value(self, value: float) -> None:
        """Update the tuning param in memory and persist without reloading."""
        int_value = int(value)
        self._room.config[self._key] = int_value

        options = dict(self._entry.options)
        rooms = dict(options.get(CONF_ROOMS, {}))
        room_config = dict(rooms.get(self._room.name, {}))
        room_config[self._key] = int_value
        rooms[self._room.name] = room_config
        options[CONF_ROOMS] = rooms

        self.hass.data[DOMAIN][self._entry.entry_id]["skip_reload"] = True
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()


class GlobalSettingNumber(NumberEntity):
    """Adjustable global setting on the Roommate hub device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(
        self,
        manager: RoommateManager,
        entry: ConfigEntry,
        key: str,
        name: str,
        low: float,
        high: float,
        unit: str,
        step: float = 1,
    ) -> None:
        self._manager = manager
        self._key = key
        self._entry = entry

        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "global")},
            name="Roommate",
            manufacturer="Roommate",
            model="Roommate",
        )

    @property
    def native_value(self) -> float:
        return self._entry.options.get(self._key, 0)

    async def async_set_native_value(self, value: float) -> None:
        """Update the global setting and persist without reloading."""
        coerced = int(value) if self._attr_native_step == 1 else float(value)
        self._manager.update_config(self._key, coerced)

        options = dict(self._entry.options)
        options[self._key] = coerced

        self.hass.data[DOMAIN][self._entry.entry_id]["skip_reload"] = True
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
