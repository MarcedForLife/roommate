"""Sensor platform for Roommate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATE_IN_BED, STATE_PRESENT, STATE_VACANT
from .room import Room


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities(RoomDiagnosticSensor(room) for room in manager.rooms.values())


class RoomDiagnosticSensor(SensorEntity):
    """Live room state for debugging (vacant, present, or in_bed with detail attributes)."""

    _attr_has_entity_name = True
    _attr_name = "Room State"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, room: Room) -> None:
        self._room = room
        self._attr_unique_id = f"{DOMAIN}_{room.name}_room_state"
        room.diagnostic_entity = self

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._room.name)})

    @property
    def native_value(self) -> str:
        if self._room.is_in_bed:
            return STATE_IN_BED
        if self._room.is_present:
            return STATE_PRESENT
        return STATE_VACANT

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
        return attrs
