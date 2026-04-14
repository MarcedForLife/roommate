"""Binary sensor platform for Roommate."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    async_add_entities(RoommateSensor(room) for room in manager.rooms.values())


class RoommateSensor(BinarySensorEntity):
    """Combined presence sensor for a room (motion OR bed)."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_has_entity_name = True
    _attr_name = "Presence"
    _attr_should_poll = False

    def __init__(self, room: Room) -> None:
        self._room = room
        self._attr_unique_id = f"{DOMAIN}_{room.name}_presence"
        room.presence_entity = self

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._room.name)},
            name=f"Roommate {self._room.name.replace('_', ' ').title()}",
            manufacturer="Roommate",
            model="Roommate",
        )

    @property
    def is_on(self) -> bool:
        return self._room.is_present

    @property
    def icon(self) -> str:
        bed_id = self._room.bed_sensor_id
        if bed_id:
            bed_state = self.hass.states.get(bed_id)
            if bed_state and bed_state.state == "on":
                return "mdi:bed"
        return "mdi:motion-sensor"

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {"room": self._room.name}
        if self._room.has_bed_sensor:
            attrs["in_bed"] = self._room.is_in_bed
            attrs["occupants"] = self._room.get_occupant_count()
        return attrs
