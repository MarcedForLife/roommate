"""Roommate manager for coordinating rooms and household sleep/wake."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.const import STATE_HOME
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BED,
    CONF_ENTITY_ID,
    CONF_ILLUMINANCE_SENSOR,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_INHIBIT,
    CONF_LIGHTS,
    CONF_OCCUPANTS,
    CONF_PRESENCE,
    CONF_ROOMS,
    CONF_SENSORS,
    CONF_SLEEP_LIGHT_TRANSITION,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_MODES,
)
from .room import INVALID_STATES, Room, _entity_is_on, _get_numeric_state

_LOGGER = logging.getLogger(__name__)


class RoommateManager:
    """Coordinates household sleep/wake lifecycle and routes entity state changes to rooms."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self.hass = hass
        self._config = config

        self._guest_mode = False
        self._rooms: dict[str, Room] = {}
        self._entity_map: dict[str, list[tuple[Room, str]]] = {}
        self._unsub_listeners: list[CALLBACK_TYPE] = []

        for name, room_config in config[CONF_ROOMS].items():
            room = Room(hass, name, room_config, self)
            self._rooms[name] = room

            sensors = room_config[CONF_SENSORS]
            self._register(sensors[CONF_PRESENCE], room, "presence")

            bed = sensors.get(CONF_BED, {})
            if CONF_PRESENCE in bed:
                self._register(bed[CONF_PRESENCE], room, "bed")
            if CONF_OCCUPANTS in bed:
                self._register(bed[CONF_OCCUPANTS], room, "occupant")

            for light in room_config[CONF_LIGHTS]:
                self._register(light, room, "light")

    @property
    def rooms(self) -> dict[str, Room]:
        return self._rooms

    @property
    def guest_mode(self) -> bool:
        return self._guest_mode

    def set_guest_mode(self, enabled: bool) -> None:
        self._guest_mode = enabled

    @property
    def sleep_lights(self) -> list[dict]:
        return self._config[CONF_SLEEP_LIGHTS]

    @property
    def all_sleep_light_ids(self) -> list[str]:
        return [light[CONF_ENTITY_ID] for light in self.sleep_lights]

    @property
    def sleep_modes(self) -> list[str]:
        return self._config[CONF_SLEEP_MODES]

    def update_config(self, key: str, value: Any) -> None:
        """Update a global config value in memory."""
        self._config[key] = value

    def _register(self, entity_id: str, room: Room, role: str) -> None:
        self._entity_map.setdefault(entity_id, []).append((room, role))

    async def async_setup(self) -> None:
        """Subscribe to state changes and initialize room states."""
        entity_ids = list(self._entity_map)
        if entity_ids:
            self._unsub_listeners.append(
                async_track_state_change_event(self.hass, entity_ids, self._handle_state_change)
            )

        for room in self._rooms.values():
            room.initialize_state()

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        """Route state change events to the appropriate room handlers."""
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]

        if new_state is None or new_state.state in INVALID_STATES:
            return

        # Entity just became available (startup or recovery from unavailable).
        # Re-read all sensors for affected rooms since there's no valid previous
        # state to compare against.
        if old_state is None or old_state.state in INVALID_STATES:
            for room, _role in self._entity_map.get(event.data["entity_id"], []):
                room.initialize_state()
                if room.presence_entity:
                    room.presence_entity.async_write_ha_state()
                if room.diagnostic_entity:
                    room.diagnostic_entity.async_write_ha_state()
            return

        for room, role in self._entity_map.get(event.data["entity_id"], []):
            if role == "presence":
                room.handle_presence_change()
            elif role == "bed":
                room.handle_presence_change()
                room.handle_bed_change(old_state.state, new_state.state)
            elif role == "occupant":
                room.handle_occupant_change(old_state.state, new_state.state)
            elif role == "light":
                room.handle_light_change(old_state.state, new_state.state, new_state.context)

    async def async_on_sleeping(self, triggering_room: Room) -> None:
        """Check if all tracked persons are in bed. If so, activate sleep mode."""
        if not triggering_room.bed_persons:
            return

        tracked_rooms = [room for room in self._rooms.values() if room.bed_persons]
        if not tracked_rooms:
            return

        for room in tracked_rooms:
            persons_home = sum(
                1
                for pid in room.bed_persons
                if _entity_is_on(self.hass, pid, target_state=STATE_HOME)
            )
            if persons_home > 0 and room.get_occupant_count() < persons_home:
                return

        _LOGGER.debug("Everyone is in bed")
        transition = self._config[CONF_SLEEP_LIGHT_TRANSITION]
        coros: list = []
        if self.all_sleep_light_ids:
            coros.append(
                self.hass.services.async_call(
                    "light",
                    "turn_off",
                    service_data={"transition": transition},
                    target={"entity_id": self.all_sleep_light_ids},
                )
            )
        for sleep_mode in self.sleep_modes:
            coros.append(
                self.hass.services.async_call(
                    "switch",
                    "turn_on",
                    target={"entity_id": sleep_mode},
                )
            )
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def async_on_waking(self, room: Room) -> None:
        """Someone got up, turn on uninhibited sleep lights."""
        if not room.bed_persons or not self.sleep_lights:
            return

        illuminance_id = self._config.get(CONF_ILLUMINANCE_SENSOR)
        if illuminance_id:
            value = _get_numeric_state(self.hass, illuminance_id)
            if value is not None and value >= self._config[CONF_ILLUMINANCE_THRESHOLD]:
                return

        if self._guest_mode:
            return

        # Collect lights that aren't inhibited
        lights_to_activate = [
            light[CONF_ENTITY_ID]
            for light in self.sleep_lights
            if not any(_entity_is_on(self.hass, inh) for inh in light[CONF_INHIBIT])
        ]

        if not lights_to_activate:
            return

        _LOGGER.debug("Someone got up in %s, turning on sleep lights", room.name)
        transition = self._config[CONF_SLEEP_LIGHT_TRANSITION]
        await self.hass.services.async_call(
            "light",
            "turn_on",
            service_data={"transition": transition},
            target={"entity_id": lights_to_activate},
        )

    async def async_on_everyone_up(self, triggering_room: Room) -> None:
        """All beds empty, disable sleep modes."""
        if not triggering_room.bed_persons or not self.sleep_modes:
            return

        # Check if any bed still has occupants (use live state, not cached)
        for room in self._rooms.values():
            if room.has_bed_sensor and room.get_occupant_count() > 0:
                return

        _LOGGER.debug("Everyone is up, disabling sleep modes")
        coros = [
            self.hass.services.async_call(
                "switch",
                "turn_off",
                target={"entity_id": mode},
            )
            for mode in self.sleep_modes
        ]
        await asyncio.gather(*coros, return_exceptions=True)

    @callback
    def shutdown(self) -> None:
        """Unsubscribe listeners and cancel all room timers."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        for room in self._rooms.values():
            room.cancel_timers()
