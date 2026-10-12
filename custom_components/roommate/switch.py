"""Switch platform for Roommate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RoommateConfigEntry
from .entity import GlobalEntity, RoomEntity
from .manager import RoommateManager
from .room import Room


@dataclass(frozen=True, kw_only=True)
class RoomSwitchDescription(SwitchEntityDescription):
    """Describes a per-room toggle backed by a Room setter."""

    is_on_fn: Callable[[Room], bool]
    set_fn: Callable[[Room, bool], None]
    exists_fn: Callable[[Room], bool] = lambda room: True


ROOM_SWITCHES: tuple[RoomSwitchDescription, ...] = (
    RoomSwitchDescription(
        key="presence_automations",
        name="Presence Automations",
        icon="mdi:motion-sensor",
        is_on_fn=lambda room: room.presence_lighting_enabled,
        set_fn=Room.set_presence_lighting_enabled,
    ),
    RoomSwitchDescription(
        key="bed_automations",
        name="Bed Automations",
        icon="mdi:bed",
        is_on_fn=lambda room: room.bed_automations_enabled,
        set_fn=Room.set_bed_automations_enabled,
        exists_fn=lambda room: room.has_bed_sensor,
    ),
    RoomSwitchDescription(
        key="illuminance_gating",
        name="Illuminance Gating",
        icon="mdi:brightness-6",
        is_on_fn=lambda room: room.illuminance_gate_enabled,
        set_fn=Room.set_illuminance_gate_enabled,
        exists_fn=lambda room: room.illuminance_sensor_id is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoommateConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    entities: list[SwitchEntity] = [GuestModeSwitch(manager)]
    for room in manager.rooms.values():
        entities.extend(
            RoomSwitch(room, description)
            for description in ROOM_SWITCHES
            if description.exists_fn(room)
        )
    async_add_entities(entities)


def _restored_toggle_state(last_state: Any) -> bool | None:
    """Translate a restored state into a toggle value, or None when it carries no answer."""
    if last_state is None or last_state.state not in (STATE_ON, STATE_OFF):
        return None
    return last_state.state == STATE_ON


class GuestModeSwitch(GlobalEntity, SwitchEntity, RestoreEntity):
    """Global toggle to suppress sleep light activation when guests are present."""

    _attr_name = "Guest Mode"
    _attr_icon = "mdi:account-group"

    def __init__(self, manager: RoommateManager) -> None:
        super().__init__(manager, "guest_mode")

    @property
    def is_on(self) -> bool:
        return self._manager.guest_mode

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = _restored_toggle_state(await self.async_get_last_state())
        if restored is not None:
            self._manager.set_guest_mode(restored)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._manager.set_guest_mode(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._manager.set_guest_mode(False)
        self.async_write_ha_state()


class RoomSwitch(RoomEntity, SwitchEntity, RestoreEntity):
    """Per-room toggle whose state lives on the Room."""

    entity_description: RoomSwitchDescription

    def __init__(self, room: Room, description: RoomSwitchDescription) -> None:
        super().__init__(room, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self._room)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        restored = _restored_toggle_state(await self.async_get_last_state())
        if restored is not None:
            self.entity_description.set_fn(self._room, restored)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set(False)

    def _set(self, enabled: bool) -> None:
        self.entity_description.set_fn(self._room, enabled)
        self._room.notify_entities()
