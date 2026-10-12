"""Sensor platform for Roommate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoommateConfigEntry
from .const import STATE_EMPTY, STATE_IN_BED, STATE_PRESENT
from .entity import RoomEntity
from .room import Room


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoommateConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(RoomDiagnosticSensor(room) for room in entry.runtime_data.rooms.values())


class RoomDiagnosticSensor(RoomEntity, SensorEntity):
    """Room state (empty, present, or in_bed) with automation and timer details."""

    _attr_name = "Room State"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, room: Room) -> None:
        super().__init__(room, "room_state")

    @property
    def native_value(self) -> str:
        if self._room.is_in_bed:
            return STATE_IN_BED
        if self._room.is_present:
            return STATE_PRESENT
        return STATE_EMPTY

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        room = self._room
        attrs: dict[str, Any] = {
            "presence_lighting": "active" if room.presence_lighting_enabled else "overridden",
        }
        if room.has_bed_sensor:
            attrs["bed_automations"] = "enabled" if room.bed_automations_enabled else "disabled"
            attrs["occupant_count"] = room.get_occupant_count()
            attrs["bed_exit_timer"] = room.bed_exit_timer_active
            attrs["snapshot"] = room.snapshot_active
        attrs["presence_off_timer"] = room.presence_off_timer_active
        attrs["presence_reset_timer"] = room.presence_reset_timer_active
        return attrs
