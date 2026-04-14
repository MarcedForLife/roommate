"""Per-room state machine and automation logic."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ADAPTIVE_LIGHTING,
    CONF_BED,
    CONF_BED_EXIT_DELAY,
    CONF_BED_RETURN_TIMEOUT,
    CONF_DIM_BRIGHTNESS,
    CONF_FANS,
    CONF_LIGHTS,
    CONF_OCCUPANTS,
    CONF_PERSONS,
    CONF_PRESENCE,
    CONF_PRESENCE_OFF_DELAY,
    CONF_RECENTLY_ON_THRESHOLD,
    CONF_SENSORS,
    CONF_SLEEP_MODE,
    CONF_SPEAKERS,
    CONF_SWITCH,
    CONF_TRANSITION_DIM,
    CONF_TRANSITION_OFF,
    CONF_TRANSITION_ON,
    CONF_WAKE_TRANSITION,
    RECENTLY_ON_OFF_TRANSITION,
)

if TYPE_CHECKING:
    from .binary_sensor import RoommateSensor
    from .manager import RoommateManager
    from .sensor import RoomDiagnosticSensor
    from .switch import BedAutomationsSwitch, PresenceLightingSwitch

_LOGGER = logging.getLogger(__name__)

INVALID_STATES = {STATE_UNAVAILABLE, STATE_UNKNOWN}
MAX_CONTEXTS = 100


class Room:
    """Per-room state and automation logic."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        config: dict[str, Any],
        manager: RoommateManager,
    ) -> None:
        self.hass = hass
        self.name = name
        self.config = config
        self._manager = manager

        self._is_present = False
        self._is_in_bed = False
        self._presence_lighting_enabled = True
        self._bed_automations_enabled = True

        self._bed_exit_timer: CALLBACK_TYPE | None = None
        self._presence_off_timer: CALLBACK_TYPE | None = None
        self._snapshot_timer: CALLBACK_TYPE | None = None
        self._pre_exit_snapshot: dict[str, Any] | None = None
        self._our_context_ids: set[str] = set()

        # Entity references (set during platform setup)
        self.presence_entity: RoommateSensor | None = None
        self.presence_lighting_switch: PresenceLightingSwitch | None = None
        self.bed_automations_switch: BedAutomationsSwitch | None = None
        self.diagnostic_entity: RoomDiagnosticSensor | None = None

    @property
    def _bed_sensors(self) -> dict[str, Any]:
        return self.config[CONF_SENSORS].get(CONF_BED, {})

    @property
    def _al_config(self) -> dict[str, Any]:
        return self.config.get(CONF_ADAPTIVE_LIGHTING, {})

    @property
    def presence_sensor_id(self) -> str:
        return self.config[CONF_SENSORS][CONF_PRESENCE]

    @property
    def bed_sensor_id(self) -> str | None:
        return self._bed_sensors.get(CONF_PRESENCE)

    @property
    def occupant_count_id(self) -> str | None:
        return self._bed_sensors.get(CONF_OCCUPANTS)

    @property
    def has_bed_sensor(self) -> bool:
        bed = self._bed_sensors
        return CONF_PRESENCE in bed or CONF_OCCUPANTS in bed

    @property
    def has_occupant_count(self) -> bool:
        return CONF_OCCUPANTS in self._bed_sensors

    @property
    def bed_persons(self) -> list[str]:
        return self._bed_sensors.get(CONF_PERSONS, [])

    @property
    def light_entities(self) -> list[str]:
        return self.config[CONF_LIGHTS]

    @property
    def al_switch_id(self) -> str | None:
        return self._al_config.get(CONF_SWITCH)

    @property
    def sleep_mode_id(self) -> str | None:
        return self._al_config.get(CONF_SLEEP_MODE)

    @property
    def is_present(self) -> bool:
        return self._is_present

    @property
    def is_in_bed(self) -> bool:
        return self._is_in_bed

    @property
    def presence_lighting_enabled(self) -> bool:
        return self._presence_lighting_enabled

    @property
    def bed_automations_enabled(self) -> bool:
        return self._bed_automations_enabled

    @property
    def bed_exit_timer_active(self) -> bool:
        return self._bed_exit_timer is not None

    @property
    def presence_off_timer_active(self) -> bool:
        return self._presence_off_timer is not None

    @property
    def snapshot_active(self) -> bool:
        return self._pre_exit_snapshot is not None

    def is_lights_on(self) -> bool:
        return any(_entity_is_on(self.hass, light) for light in self.light_entities)

    def _is_bed_occupied(self) -> bool:
        bed_id = self.bed_sensor_id
        if bed_id:
            return _entity_is_on(self.hass, bed_id)
        occ_id = self.occupant_count_id
        if occ_id:
            count = _get_numeric_state(self.hass, occ_id)
            return count is not None and count > 0
        return False

    def get_occupant_count(self) -> int:
        occ_id = self.occupant_count_id
        if occ_id:
            return int(_get_numeric_state(self.hass, occ_id) or 0)
        if self.bed_sensor_id:
            return 1 if _entity_is_on(self.hass, self.bed_sensor_id) else 0
        return 0

    def initialize_state(self) -> None:
        """Set initial state from current sensor values without taking actions."""
        self._update_presence_state()
        self._is_in_bed = self._is_bed_occupied()

    def _update_presence_state(self) -> None:
        self._is_present = (
            _entity_is_on(self.hass, self.presence_sensor_id) or self._is_bed_occupied()
        )

    def set_presence_lighting_enabled(self, enabled: bool) -> None:
        self._presence_lighting_enabled = enabled

    def set_bed_automations_enabled(self, enabled: bool) -> None:
        self._bed_automations_enabled = enabled

    @callback
    def handle_presence_change(self) -> None:
        was_present = self._is_present
        self._update_presence_state()

        if self._is_present and not was_present:
            self._cancel_presence_off_timer()
            self.hass.async_create_task(self._on_presence_detected())
        elif not self._is_present and was_present:
            self._start_presence_off_timer()

        if self.presence_entity:
            self.presence_entity.async_write_ha_state()
        if self.diagnostic_entity:
            self.diagnostic_entity.async_write_ha_state()

    @callback
    def handle_bed_change(self, old: str, new: str) -> None:
        if not self._bed_automations_enabled:
            return

        if new == STATE_ON and old != STATE_ON:
            self._cancel_bed_exit_timer()
            self._is_in_bed = True
            self.hass.async_create_task(self._on_getting_in_bed())
        elif old == STATE_ON and new != STATE_ON:
            self._start_bed_exit_timer()

        if self.diagnostic_entity:
            self.diagnostic_entity.async_write_ha_state()

    @callback
    def handle_occupant_change(self, old: str, new: str) -> None:
        if not self._bed_automations_enabled:
            return
        try:
            old_count, new_count = int(float(old)), int(float(new))
        except (ValueError, TypeError):
            return

        # Room-level bed entry/exit for rooms without a bed presence sensor
        if not self.bed_sensor_id:
            if new_count > 0 and old_count == 0:
                self._is_in_bed = True
                self.hass.async_create_task(self._on_getting_in_bed())
            elif new_count == 0 and old_count > 0:
                self.hass.async_create_task(self._on_leaving_bed())

        # Household-level sleep/wake
        if new_count > old_count:
            self.hass.async_create_task(self._manager.async_on_sleeping(self))
        elif new_count < old_count:
            self.hass.async_create_task(self._manager.async_on_waking(self))
            self.hass.async_create_task(self._manager.async_on_everyone_up(self))

        if self.diagnostic_entity:
            self.diagnostic_entity.async_write_ha_state()

    @callback
    def handle_light_change(self, old: str, new: str, context: Context | None) -> None:
        if self._is_our_context(context):
            return

        turned_off = old == STATE_ON and new != STATE_ON
        turned_on = old != STATE_ON and new == STATE_ON

        if turned_off and self._is_present:
            self._presence_lighting_enabled = False
            _LOGGER.debug("Room %s: manual light off, disabling presence lighting", self.name)
        elif turned_on and not self._presence_lighting_enabled:
            self._presence_lighting_enabled = True
            _LOGGER.debug("Room %s: manual light on, re-enabling presence lighting", self.name)
        else:
            return

        if self.presence_lighting_switch:
            self.presence_lighting_switch.async_write_ha_state()
        if self.diagnostic_entity:
            self.diagnostic_entity.async_write_ha_state()

    async def _on_presence_detected(self) -> None:
        if not self._presence_lighting_enabled:
            return
        _LOGGER.debug("Room %s: presence detected", self.name)
        await self._call_service(
            "light",
            "turn_on",
            entity_id=self.light_entities,
            transition=self.config[CONF_TRANSITION_ON],
        )

    async def _on_presence_ended(self) -> None:
        if not self._presence_lighting_enabled:
            return
        _LOGGER.debug("Room %s: presence ended", self.name)
        await self._call_service(
            "light",
            "turn_off",
            entity_id=self.light_entities,
            transition=self.config[CONF_TRANSITION_OFF],
        )

    async def _on_getting_in_bed(self) -> None:
        # Quick return: restore previous room state instead of normal bed entry
        if self._pre_exit_snapshot:
            await self._restore_snapshot()
            return

        if not self.is_lights_on():
            return

        first_light = self.hass.states.get(self.light_entities[0])
        elapsed = (
            (dt_util.utcnow() - first_light.last_changed).total_seconds()
            if first_light
            else float("inf")
        )

        if elapsed < self.config[CONF_RECENTLY_ON_THRESHOLD]:
            _LOGGER.debug("Room %s: getting in bed, lights recently on, turning off", self.name)
            await self._call_service(
                "light",
                "turn_off",
                entity_id=self.light_entities,
                transition=RECENTLY_ON_OFF_TRANSITION,
            )
        else:
            dim = self.config[CONF_DIM_BRIGHTNESS]
            _LOGGER.debug("Room %s: getting in bed, dimming to %d%%", self.name, dim)
            await self._call_service(
                "light",
                "turn_on",
                entity_id=self.light_entities,
                brightness_pct=dim,
                transition=self.config[CONF_TRANSITION_DIM],
            )

    async def _on_leaving_bed(self) -> None:
        self._is_in_bed = False
        _LOGGER.debug("Room %s: leaving bed", self.name)

        self._save_snapshot()

        # Disable room-level sleep mode
        if self.sleep_mode_id:
            await self._call_service("switch", "turn_off", entity_id=self.sleep_mode_id)

        coros: list = []

        if self.is_lights_on():
            if self.al_switch_id and self.light_entities:
                coros.append(self.restore_adaptive_lighting())
            self._presence_lighting_enabled = True
            if self.presence_lighting_switch:
                self.presence_lighting_switch.async_write_ha_state()
        elif self.config.get(CONF_WAKE_TRANSITION) and self._is_present:
            coros.append(
                self._call_service(
                    "light",
                    "turn_on",
                    entity_id=self.light_entities,
                    transition=self.config[CONF_WAKE_TRANSITION],
                )
            )

        for fan in self.config[CONF_FANS]:
            coros.append(self._call_service("fan", "turn_off", entity_id=fan))
        for speaker in self.config[CONF_SPEAKERS]:
            coros.append(self._call_service("media_player", "media_stop", entity_id=speaker))

        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

        # Wake/everyone-up checks (skip if occupant_count handles it)
        if self.bed_persons and not self.has_occupant_count:
            await self._manager.async_on_waking(self)
            await self._manager.async_on_everyone_up(self)

    async def restore_adaptive_lighting(self) -> None:
        """Restore adaptive lighting automatic control for this room."""
        al_switch = self.al_switch_id
        lights = self.light_entities
        if not al_switch or not lights:
            return

        if not self.hass.services.has_service("adaptive_lighting", "set_manual_control"):
            return

        await self.hass.services.async_call(
            "adaptive_lighting",
            "set_manual_control",
            service_data={
                "entity_id": al_switch,
                "manual_control": False,
                "lights": lights,
            },
        )

    def _save_snapshot(self) -> None:
        """Capture room state before leaving-bed actions modify it."""
        timeout = self.config[CONF_BED_RETURN_TIMEOUT]
        if timeout <= 0:
            return

        snapshot: dict[str, Any] = {"lights": {}, "fans": {}}

        for light_id in self.light_entities:
            state = self.hass.states.get(light_id)
            if state:
                snapshot["lights"][light_id] = {
                    "state": state.state,
                    "brightness": state.attributes.get("brightness"),
                    "color_temp": state.attributes.get("color_temp"),
                }

        for fan_id in self.config[CONF_FANS]:
            state = self.hass.states.get(fan_id)
            if state:
                snapshot["fans"][fan_id] = {
                    "state": state.state,
                    "percentage": state.attributes.get("percentage"),
                }

        if self.sleep_mode_id:
            state = self.hass.states.get(self.sleep_mode_id)
            snapshot["sleep_mode"] = state.state if state else None

        self._pre_exit_snapshot = snapshot
        self._cancel_snapshot_timer()
        self._snapshot_timer = async_call_later(self.hass, timeout, self._on_snapshot_expired)
        _LOGGER.debug("Room %s: saved state snapshot (expires in %ds)", self.name, timeout)

    async def _restore_snapshot(self) -> None:
        """Restore room state from a saved snapshot."""
        snapshot = self._pre_exit_snapshot
        self._clear_snapshot()

        if not snapshot:
            return

        _LOGGER.debug("Room %s: restoring state snapshot (quick bed return)", self.name)
        coros: list = []

        for light_id, attrs in snapshot.get("lights", {}).items():
            if attrs["state"] == STATE_ON:
                data = {
                    key: attrs[key]
                    for key in ("brightness", "color_temp")
                    if attrs.get(key) is not None
                }
                coros.append(self._call_service("light", "turn_on", entity_id=light_id, **data))
            else:
                coros.append(self._call_service("light", "turn_off", entity_id=light_id))

        for fan_id, attrs in snapshot.get("fans", {}).items():
            if attrs["state"] == STATE_ON:
                data = {}
                if attrs.get("percentage") is not None:
                    data["percentage"] = attrs["percentage"]
                coros.append(self._call_service("fan", "turn_on", entity_id=fan_id, **data))

        if snapshot.get("sleep_mode") == STATE_ON and self.sleep_mode_id:
            coros.append(self._call_service("switch", "turn_on", entity_id=self.sleep_mode_id))

        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    @callback
    def _on_snapshot_expired(self, _now: Any) -> None:
        self._snapshot_timer = None
        self._pre_exit_snapshot = None
        _LOGGER.debug("Room %s: state snapshot expired", self.name)

    def _cancel_snapshot_timer(self) -> None:
        if self._snapshot_timer:
            self._snapshot_timer()
            self._snapshot_timer = None

    def _clear_snapshot(self) -> None:
        self._cancel_snapshot_timer()
        self._pre_exit_snapshot = None

    def _start_bed_exit_timer(self) -> None:
        self._cancel_bed_exit_timer()
        delay = self.config[CONF_BED_EXIT_DELAY]
        if delay > 0:
            self._bed_exit_timer = async_call_later(self.hass, delay, self._on_bed_exit_timer)
        else:
            self.hass.async_create_task(self._on_leaving_bed())

    @callback
    def _on_bed_exit_timer(self, _now: Any) -> None:
        self._bed_exit_timer = None
        self.hass.async_create_task(self._on_leaving_bed())

    def _cancel_bed_exit_timer(self) -> None:
        if self._bed_exit_timer:
            self._bed_exit_timer()
            self._bed_exit_timer = None

    def _start_presence_off_timer(self) -> None:
        self._cancel_presence_off_timer()
        delay = self.config[CONF_PRESENCE_OFF_DELAY]
        if delay > 0:
            self._presence_off_timer = async_call_later(
                self.hass, delay, self._on_presence_off_timer
            )
        else:
            self.hass.async_create_task(self._on_presence_ended())

    @callback
    def _on_presence_off_timer(self, _now: Any) -> None:
        self._presence_off_timer = None
        if not self._is_present:
            self.hass.async_create_task(self._on_presence_ended())

    def _cancel_presence_off_timer(self) -> None:
        if self._presence_off_timer:
            self._presence_off_timer()
            self._presence_off_timer = None

    def cancel_timers(self) -> None:
        self._cancel_bed_exit_timer()
        self._cancel_presence_off_timer()
        self._clear_snapshot()

    async def _call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        context = Context()
        self._our_context_ids.add(context.id)
        if len(self._our_context_ids) > MAX_CONTEXTS:
            self._our_context_ids.clear()
            self._our_context_ids.add(context.id)

        try:
            await self.hass.services.async_call(
                domain,
                service,
                service_data=kwargs or None,
                target={"entity_id": entity_id} if entity_id else None,
                context=context,
            )
        except Exception:
            _LOGGER.exception("Room %s: failed to call %s.%s", self.name, domain, service)

    def _is_our_context(self, context: Context | None) -> bool:
        if context is None:
            return False
        return context.id in self._our_context_ids or context.parent_id in self._our_context_ids


def _entity_is_on(hass: HomeAssistant, entity_id: str, target_state: str = STATE_ON) -> bool:
    """Check if an entity is in the target state (default: 'on')."""
    state = hass.states.get(entity_id)
    return state is not None and state.state not in INVALID_STATES and state.state == target_state


def _get_numeric_state(hass: HomeAssistant, entity_id: str) -> float | None:
    """Read a numeric entity state, returning None if unavailable or invalid."""
    state = hass.states.get(entity_id)
    if state and state.state not in INVALID_STATES:
        try:
            return float(state.state)
        except (ValueError, TypeError):
            pass
    return None
