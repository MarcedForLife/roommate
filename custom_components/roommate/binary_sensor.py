"""Binary sensor platform for Roommate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    async_add_entities(RoomPresenceSensor(room) for room in entry.runtime_data.rooms.values())


class RoomPresenceSensor(RoomEntity, BinarySensorEntity):
    """Combined presence sensor for a room (motion OR bed)."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_name = "Presence"

    def __init__(self, room: Room) -> None:
        super().__init__(room, "presence")

    @property
    def is_on(self) -> bool:
        return self._room.is_present

    @property
    def icon(self) -> str:
        return "mdi:bed" if self._room.is_in_bed else "mdi:motion-sensor"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"room": self._room.name}
        if self._room.has_bed_sensor:
            attrs["in_bed"] = self._room.is_in_bed
            attrs["occupants"] = self._room.get_occupant_count()
        return attrs
