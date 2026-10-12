"""Button platform for Roommate."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoommateConfigEntry
from .entity import RoomEntity
from .room import Room


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoommateConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        RestoreAutoBrightnessButton(room)
        for room in entry.runtime_data.rooms.values()
        if room.al_switch_id
    )


class RestoreAutoBrightnessButton(RoomEntity, ButtonEntity):
    """Button to restore adaptive lighting auto-brightness for a room."""

    _attr_name = "Restore Auto Brightness"
    _attr_icon = "mdi:brightness-auto"

    def __init__(self, room: Room) -> None:
        super().__init__(room, "restore_auto_brightness")

    async def async_press(self) -> None:
        await self._room.restore_adaptive_lighting()
