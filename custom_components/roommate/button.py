"""Button platform for Roommate."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .room import Room


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities(
        RestoreAutoBrightnessButton(room)
        for room in manager.rooms.values()
        if room.al_switch_id and room.light_entities
    )


class RestoreAutoBrightnessButton(ButtonEntity):
    """Button to restore adaptive lighting auto-brightness for a room."""

    _attr_has_entity_name = True
    _attr_name = "Restore Auto Brightness"
    _attr_icon = "mdi:brightness-auto"
    _attr_should_poll = False

    def __init__(self, room: Room) -> None:
        self._room = room
        self._attr_unique_id = f"{DOMAIN}_restore_auto_brightness_{room.name}"
        self._attr_suggested_object_id = f"roommate_restore_auto_brightness_{room.name}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._room.name)})

    async def async_press(self) -> None:
        await self._room.restore_adaptive_lighting()
