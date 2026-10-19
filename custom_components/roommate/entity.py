"""Shared entity base classes for Roommate."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import RoommateManager
from .room import Room

GLOBAL_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "global")},
    name="Roommate",
    manufacturer="Roommate",
    model="Roommate",
)


class GlobalEntity(Entity):
    """Entity on the global Roommate device."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_info = GLOBAL_DEVICE_INFO

    def __init__(self, manager: RoommateManager, key: str) -> None:
        self._manager = manager
        self._attr_unique_id = f"{DOMAIN}_{key}"


class RoomEntity(Entity):
    """Entity on a room device. Writes its state whenever the room signals a change."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, room: Room, key: str) -> None:
        self._room = room
        self._attr_unique_id = f"{DOMAIN}_{room.name}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.name)},
            name=f"Roommate {room.name.replace('_', ' ').title()}",
            manufacturer="Roommate",
            model="Roommate",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._room.update_signal, self.async_write_ha_state)
        )
