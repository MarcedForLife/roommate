"""Switch platform for Roommate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .manager import RoommateManager
from .room import Room


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]["manager"]
    entities: list[SwitchEntity] = [GuestModeSwitch(manager)]

    for room in manager.rooms.values():
        entities.append(PresenceLightingSwitch(room))
        if room.has_bed_sensor:
            entities.append(BedAutomationsSwitch(room))

    async_add_entities(entities)


class GuestModeSwitch(SwitchEntity, RestoreEntity):
    """Global toggle to suppress sleep light activation when guests are present."""

    _attr_has_entity_name = True
    _attr_name = "Guest Mode"
    _attr_icon = "mdi:account-group"
    _attr_should_poll = False

    def __init__(self, manager: RoommateManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{DOMAIN}_guest_mode"
        self._attr_suggested_object_id = "roommate_guest_mode"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "global")},
            name="Roommate",
            manufacturer="Roommate",
            model="Roommate",
        )

    @property
    def is_on(self) -> bool:
        return self._manager.guest_mode

    async def async_added_to_hass(self) -> None:
        if (last_state := await self.async_get_last_state()) is not None:
            self._manager.set_guest_mode(last_state.state == STATE_ON)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._manager.set_guest_mode(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._manager.set_guest_mode(False)
        self.async_write_ha_state()


class PresenceLightingSwitch(SwitchEntity, RestoreEntity):
    """Toggle for presence-based lighting in a room."""

    _attr_has_entity_name = True
    _attr_name = "Presence Automations"
    _attr_icon = "mdi:motion-sensor"
    _attr_should_poll = False

    def __init__(self, room: Room) -> None:
        self._room = room
        self._attr_unique_id = f"{DOMAIN}_presence_automations_{room.name}"
        self._attr_suggested_object_id = f"roommate_presence_automations_{room.name}"
        room.presence_lighting_switch = self

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._room.name)})

    @property
    def is_on(self) -> bool:
        return self._room.presence_lighting_enabled

    async def async_added_to_hass(self) -> None:
        if (last_state := await self.async_get_last_state()) is not None:
            self._room.set_presence_lighting_enabled(last_state.state == STATE_ON)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._room.set_presence_lighting_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._room.set_presence_lighting_enabled(False)
        self.async_write_ha_state()


class BedAutomationsSwitch(SwitchEntity, RestoreEntity):
    """Toggle for bed-related automations in a room."""

    _attr_has_entity_name = True
    _attr_name = "Bed Automations"
    _attr_icon = "mdi:bed"
    _attr_should_poll = False

    def __init__(self, room: Room) -> None:
        self._room = room
        self._attr_unique_id = f"{DOMAIN}_bed_automations_{room.name}"
        self._attr_suggested_object_id = f"roommate_bed_automations_{room.name}"
        room.bed_automations_switch = self

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._room.name)})

    @property
    def is_on(self) -> bool:
        return self._room.bed_automations_enabled

    async def async_added_to_hass(self) -> None:
        if (last_state := await self.async_get_last_state()) is not None:
            self._room.set_bed_automations_enabled(last_state.state == STATE_ON)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._room.set_bed_automations_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._room.set_bed_automations_enabled(False)
        self.async_write_ha_state()
