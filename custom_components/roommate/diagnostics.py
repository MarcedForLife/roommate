"""Diagnostics for Roommate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import RoommateConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RoommateConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a Roommate config entry."""
    manager = entry.runtime_data

    rooms: dict[str, Any] = {}
    for name, room in manager.rooms.items():
        rooms[name] = {
            "is_present": room.is_present,
            "is_in_bed": room.is_in_bed,
            "presence_lighting_enabled": room.presence_lighting_enabled,
            "bed_automations_enabled": room.bed_automations_enabled,
            "illuminance_gate_enabled": room.illuminance_gate_enabled,
            "illuminance_sensor_id": room.illuminance_sensor_id,
            "illuminance_threshold": room.illuminance_threshold,
            "lights_on": room.is_lights_on(),
            "occupant_count": room.get_occupant_count(),
            "has_bed_sensor": room.has_bed_sensor,
            "bed_exit_timer_active": room.bed_exit_timer_active,
            "presence_off_timer_active": room.presence_off_timer_active,
            "presence_reset_timer_active": room.presence_reset_timer_active,
            "snapshot_active": room.snapshot_active,
        }

    entity_map = {
        entity_id: [{"room": room.name, "role": role} for room, role in bindings]
        for entity_id, bindings in manager.entity_map.items()
    }

    return {
        "config": dict(entry.options),
        "guest_mode": manager.guest_mode,
        "rooms": rooms,
        "entity_map": entity_map,
    }
