"""Diagnostics for Roommate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a Roommate config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]["manager"]

    rooms: dict[str, Any] = {}
    for name, room in manager.rooms.items():
        rooms[name] = {
            "is_present": room.is_present,
            "is_in_bed": room.is_in_bed,
            "presence_lighting_enabled": room.presence_lighting_enabled,
            "bed_automations_enabled": room.bed_automations_enabled,
            "lights_on": room.is_lights_on(),
            "occupant_count": room.get_occupant_count(),
            "has_bed_sensor": room.has_bed_sensor,
            "bed_exit_timer_active": room.bed_exit_timer_active,
            "presence_off_timer_active": room.presence_off_timer_active,
            "snapshot_active": room.snapshot_active,
        }

    entity_map: dict[str, list[dict[str, str]]] = {}
    for entity_id, bindings in manager._entity_map.items():
        entity_map[entity_id] = [{"room": room.name, "role": role} for room, role in bindings]

    return {
        "config": dict(entry.options),
        "guest_mode": manager.guest_mode,
        "rooms": rooms,
        "entity_map": entity_map,
    }
