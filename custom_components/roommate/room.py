"""Per-room state machine and automation logic."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
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
    State,
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
    CONF_ILLUMINANCE,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_LIGHTS,
    CONF_OCCUPANTS,
    CONF_PERSONS,
    CONF_PRESENCE,
    CONF_PRESENCE_OFF_DELAY,
    CONF_PRESENCE_RESET_TIMEOUT,
    CONF_RECENTLY_ON_THRESHOLD,
    CONF_ROOM_RESET_TIMEOUT,
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
    from .switch import BedAutomationsSwitch, IlluminanceGateSwitch, PresenceLightingSwitch

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
        self._illuminance_gate_enabled = True

        self._bed_exit_timer: CALLBACK_TYPE | None = None
        self._presence_off_timer: CALLBACK_TYPE | None = None
        self._presence_reset_timer: CALLBACK_TYPE | None = None
        self._snapshot_timer: CALLBACK_TYPE | None = None
        self._pre_exit_snapshot: dict[str, Any] | None = None
        self._our_context_ids: set[str] = set()
        self._our_context_order: deque[str] = deque(maxlen=MAX_CONTEXTS)

        # Entity references (set during platform setup)
        self.presence_entity: RoommateSensor | None = None
        self.presence_lighting_switch: PresenceLightingSwitch | None = None
        self.bed_automations_switch: BedAutomationsSwitch | None = None
        self.illuminance_gate_switch: IlluminanceGateSwitch | None = None
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
    def bed_presence_drives_household(self) -> bool:
        """Whether a bed-presence transition drives this room's household sleep/wake.

        True for rooms with bed_persons but no occupant-count sensor; occupant-count
        rooms drive the household from count deltas in handle_occupant_change instead.
        """
        return bool(self.bed_persons) and not self.has_occupant_count

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
    def illuminance_gate_enabled(self) -> bool:
        return self._illuminance_gate_enabled

    @property
    def illuminance_sensor_id(self) -> str | None:
        """Effective illuminance sensor: room override falls back to global."""
        room_sensor = self.config[CONF_SENSORS].get(CONF_ILLUMINANCE)
        if room_sensor:
            return room_sensor
        return self._manager.illuminance_sensor_id

    @property
    def illuminance_threshold(self) -> float:
        """Effective illuminance threshold: room override (0 = use global)."""
        room_threshold = self.config.get(CONF_ILLUMINANCE_THRESHOLD, 0)
        if room_threshold > 0:
            return room_threshold
        return self._manager.illuminance_threshold

    @property
    def bed_exit_timer_active(self) -> bool:
        return self._bed_exit_timer is not None

    @property
    def presence_off_timer_active(self) -> bool:
        return self._presence_off_timer is not None

    @property
    def presence_reset_timer_active(self) -> bool:
        return self._presence_reset_timer is not None

    @property
    def snapshot_active(self) -> bool:
        return self._pre_exit_snapshot is not None

    def is_lights_on(self) -> bool:
        return any(_entity_is_on(self.hass, light) for light in self.light_entities)

    def _bed_occupancy_reading(self) -> bool | None:
        """Union of the configured bed sensors, or None when neither has a valid state."""
        reading: bool | None = None
        bed_id = self.bed_sensor_id
        if bed_id:
            state = self.hass.states.get(bed_id)
            if state is not None and state.state not in INVALID_STATES:
                reading = state.state == STATE_ON
        occ_id = self.occupant_count_id
        if occ_id:
            count = _get_numeric_state(self.hass, occ_id)
            if count is not None:
                reading = bool(reading) or count > 0
        return reading

    def _is_bed_occupied(self) -> bool:
        # Occupied if either sensor reports occupancy, so a count of 0 from one sensor
        # can't override a binary sensor that says the bed is in use (and vice versa).
        # With no valid sensor data at all, keep the cached value rather than assuming
        # empty, matching how the event handler freezes state while unavailable.
        reading = self._bed_occupancy_reading()
        return self._is_in_bed if reading is None else reading

    def get_occupant_count(self) -> int:
        occ_id = self.occupant_count_id
        if occ_id:
            count = _get_numeric_state(self.hass, occ_id)
            if count is not None:
                return int(count)
        # No count sensor, or no valid reading from it: fall back to the binary sensor.
        if self.bed_sensor_id:
            return 1 if _entity_is_on(self.hass, self.bed_sensor_id) else 0
        return 0

    def initialize_state(self) -> None:
        """Set initial state from current sensor values without taking actions."""
        self._update_presence_state()
        self._is_in_bed = self._is_bed_occupied()
        # Reconcile the vacancy countdown: an already-empty room starts it at setup
        # (so a pending reset isn't lost to a restart), and a sensor first appearing
        # as detected clears the one armed before it appeared.
        if self._is_present:
            self._cancel_presence_reset_timer()
        else:
            self._start_presence_reset_timer()

    def resync(self, roles: set[str]) -> None:
        """Re-read sensors after an unavailable/unknown gap and run the handlers for
        any real transition that happened while the entity was unavailable.

        Unlike initialize_state, this dispatches side effects for state deltas so the
        room converges to correct outputs (lights/fans/speakers/sleep) instead of only
        correct cached state. Only state derived from the recovered roles is touched,
        so e.g. a light recovering can't misread a still-unavailable bed sensor as a
        bed exit. A flap with no net change produces no actions.
        """
        if roles & {"bed", "occupant"}:
            self._resync_bed()
        if roles - {"light"}:
            # Recompute combined presence and dispatch its own delta (also writes the
            # presence and diagnostic entities).
            self.handle_presence_change()

    def _resync_bed(self) -> None:
        """Reconcile cached bed state, dispatching entry/exit side effects on a delta.

        Partial count changes hidden by the gap (e.g. 2 -> unavailable -> 1) can't be
        recovered; only the occupied/empty transition is.
        """
        reading = self._bed_occupancy_reading()
        if reading is None or reading == self._is_in_bed:
            return
        self._is_in_bed = reading
        if not self._bed_automations_enabled:
            return

        if reading:
            self._begin_getting_in_bed()
        else:
            # The exit happened at some point during the gap, so skip the debounce.
            self.hass.async_create_task(self._on_leaving_bed())

        # Occupant-count rooms normally drive the household from count deltas in
        # handle_occupant_change, which never saw the gap; dispatch from this delta.
        if self.bed_persons and self.has_occupant_count:
            if reading:
                self.hass.async_create_task(self._manager.async_on_sleeping(self))
            else:
                self.hass.async_create_task(self._manager.async_on_waking(self))
                self.hass.async_create_task(self._manager.async_on_everyone_up(self))

    def _update_presence_state(self) -> None:
        self._is_present = (
            _entity_is_on(self.hass, self.presence_sensor_id) or self._is_bed_occupied()
        )

    def set_presence_lighting_enabled(self, enabled: bool) -> None:
        """Set the override state. Disabling while the room is empty (re)starts the
        reset countdown; the countdown is otherwise vacancy-driven and survives
        re-enabling, so a pending room reset still cleans the room up (see
        _on_presence_reset)."""
        self._presence_lighting_enabled = enabled
        if not enabled and not self._is_present:
            self._start_presence_reset_timer()

    def set_illuminance_gate_enabled(self, enabled: bool) -> None:
        self._illuminance_gate_enabled = enabled

    def should_skip_for_illuminance(self) -> bool:
        """Return True if ambient light is above the threshold and gating is on."""
        if not self._illuminance_gate_enabled:
            return False
        sensor_id = self.illuminance_sensor_id
        if not sensor_id:
            return False
        threshold = self.illuminance_threshold
        if threshold <= 0:
            # A non-positive effective threshold means gating is disabled, not
            # "skip whenever there is any light".
            return False
        value = _get_numeric_state(self.hass, sensor_id)
        if value is None:
            return False
        return value >= threshold

    def set_bed_automations_enabled(self, enabled: bool) -> None:
        self._bed_automations_enabled = enabled
        if not enabled:
            # Don't let a debounce started while enabled fire after the user disabled it.
            self._cancel_bed_exit_timer()

    @callback
    def handle_presence_change(self) -> None:
        was_present = self._is_present
        self._update_presence_state()

        if self._is_present and not was_present:
            self._cancel_presence_off_timer()
            self._cancel_presence_reset_timer()
            self.hass.async_create_task(self._on_presence_detected())
        elif not self._is_present and was_present:
            self._start_presence_off_timer()
            self._start_presence_reset_timer()

        if self.presence_entity:
            self.presence_entity.async_write_ha_state()
        if self.diagnostic_entity:
            self.diagnostic_entity.async_write_ha_state()

    def _begin_getting_in_bed(self) -> None:
        """Schedule bed-entry actions: room dimming, plus (for binary beds) the
        household sleep check. Occupant-count beds drive the household from count
        deltas, so the household call is gated on bed_presence_drives_household.
        """
        self._cancel_bed_exit_timer()
        self.hass.async_create_task(self._on_getting_in_bed())
        if self.bed_presence_drives_household:
            self.hass.async_create_task(self._manager.async_on_sleeping(self))

    @callback
    def handle_bed_change(self, old: str, new: str) -> None:
        if new == STATE_ON and old != STATE_ON:
            self._is_in_bed = True
            if self._bed_automations_enabled:
                self._begin_getting_in_bed()
        elif old == STATE_ON and new != STATE_ON:
            self._is_in_bed = False
            if self._bed_automations_enabled:
                self._start_bed_exit_timer()

        if self.diagnostic_entity:
            self.diagnostic_entity.async_write_ha_state()

    @callback
    def handle_occupant_change(self, old: str, new: str) -> None:
        try:
            old_count, new_count = int(float(old)), int(float(new))
        except (ValueError, TypeError):
            return

        # Room-level bed entry/exit for rooms without a bed presence sensor.
        # Route through the same debounce/cancellation as the binary-bed path so the
        # bed_exit_delay applies and a quick occupant flap can't race entry vs exit.
        if not self.bed_sensor_id:
            if new_count > 0 and old_count == 0:
                self._is_in_bed = True
                if self._bed_automations_enabled:
                    self._begin_getting_in_bed()
            elif new_count == 0 and old_count > 0:
                self._is_in_bed = False
                if self._bed_automations_enabled:
                    self._start_bed_exit_timer()

        # Household-level sleep/wake
        if self._bed_automations_enabled:
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
            self.set_presence_lighting_enabled(False)
            _LOGGER.debug("Room %s: manual light off, disabling presence lighting", self.name)
        elif turned_on and not self._presence_lighting_enabled:
            self.set_presence_lighting_enabled(True)
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
        if self._is_in_bed:
            # Presence flipped on via the bed union (or a recovery) while in bed; the
            # bed logic owns the lights, don't blast them to full brightness.
            return
        if self.should_skip_for_illuminance():
            _LOGGER.debug("Room %s: presence detected but room is bright enough", self.name)
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
        # Re-read live presence: the presence_off_delay==0 path schedules this directly
        # without the recheck the timer callback does, so a quick off->on flap must not
        # turn the lights off while the room is occupied again.
        if self._is_present:
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

        # Base the "recently on" decision on the most recently changed light that is
        # currently on, not just the first configured light (which may be off).
        on_lights = [
            state
            for light_id in self.light_entities
            if (state := self.hass.states.get(light_id)) is not None and state.state == STATE_ON
        ]
        if not on_lights:
            return

        latest_change = max(state.last_changed for state in on_lights)
        elapsed = (dt_util.utcnow() - latest_change).total_seconds()
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
        if self._is_in_bed:
            # Already back in bed before this task ran (a delay-0 flap); skip the leave
            # entirely so the room sleep mode isn't toggled off under the sleeper.
            return
        _LOGGER.debug("Room %s: leaving bed", self.name)

        self._save_snapshot()
        # Capture before any await: a quick return restores and clears the snapshot,
        # which would otherwise flip the speaker handling below from pause to stop.
        snapshot_active = self._pre_exit_snapshot is not None

        # Disable room-level sleep mode
        if self.sleep_mode_id:
            await self._call_service("switch", "turn_off", entity_id=self.sleep_mode_id)

        if self._is_in_bed:
            # Returned to bed while leaving; a getting-in-bed handler has taken over
            # (and may have restored the snapshot). Abort the rest of the leave.
            _LOGGER.debug("Room %s: leaving-bed superseded by re-entry, aborting", self.name)
            return

        coros: list = []

        self.set_presence_lighting_enabled(True)
        if self.presence_lighting_switch:
            self.presence_lighting_switch.async_write_ha_state()

        if self.is_lights_on():
            if self.al_switch_id and self.light_entities:
                coros.append(self.restore_adaptive_lighting())
        elif self._is_present and not self.should_skip_for_illuminance():
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
            if snapshot_active:
                # Pause playing speakers so we can resume on quick return
                if _entity_is_on(self.hass, speaker, target_state="playing"):
                    coros.append(
                        self._call_service("media_player", "media_pause", entity_id=speaker)
                    )
            else:
                coros.append(self._call_service("media_player", "media_stop", entity_id=speaker))

        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

        # Wake/everyone-up checks (occupant-count beds handle these from count deltas)
        if self.bed_presence_drives_household:
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

        await self._call_service(
            "adaptive_lighting",
            "set_manual_control",
            entity_id=al_switch,
            manual_control=False,
            lights=lights,
        )

    def _save_snapshot(self) -> None:
        """Capture room state before leaving-bed actions modify it."""
        timeout = self.config[CONF_BED_RETURN_TIMEOUT]
        if timeout <= 0:
            return

        snapshot: dict[str, Any] = {
            "lights": _snapshot_states(self.hass, self.light_entities, _capture_light_state),
            "fans": _snapshot_states(self.hass, self.config[CONF_FANS], _capture_fan_state),
            "speakers": _snapshot_states(
                self.hass, self.config[CONF_SPEAKERS], _capture_speaker_state
            ),
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
                coros.append(
                    self._call_service(
                        "light", "turn_on", entity_id=light_id, **_light_restore_data(attrs)
                    )
                )
            else:
                coros.append(self._call_service("light", "turn_off", entity_id=light_id))

        for fan_id, attrs in snapshot.get("fans", {}).items():
            if attrs["state"] == STATE_ON:
                data = {}
                # Prefer the preset: fans report a percentage alongside an active
                # preset, and restoring the percentage would drop the preset.
                if attrs.get("preset_mode") is not None:
                    data["preset_mode"] = attrs["preset_mode"]
                elif attrs.get("percentage") is not None:
                    data["percentage"] = attrs["percentage"]
                coros.append(self._call_service("fan", "turn_on", entity_id=fan_id, **data))

        for speaker_id, attrs in snapshot.get("speakers", {}).items():
            if attrs["state"] == "playing":
                coros.append(self._call_service("media_player", "media_play", entity_id=speaker_id))

        if snapshot.get("sleep_mode") == STATE_ON and self.sleep_mode_id:
            coros.append(self._call_service("switch", "turn_on", entity_id=self.sleep_mode_id))

        any_light_on = any(
            attrs["state"] == STATE_ON for attrs in snapshot.get("lights", {}).values()
        )
        if any_light_on and self.al_switch_id:
            coros.append(self.restore_adaptive_lighting())

        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    @callback
    def _on_snapshot_expired(self, _now: Any) -> None:
        self._snapshot_timer = None
        snapshot = self._pre_exit_snapshot
        self._pre_exit_snapshot = None

        speakers_to_stop = [
            speaker_id
            for speaker_id, attrs in (snapshot or {}).get("speakers", {}).items()
            if attrs["state"] == "playing"
        ]
        if speakers_to_stop:
            self.hass.async_create_task(self._stop_speakers(speakers_to_stop))

        if self.diagnostic_entity:
            self.diagnostic_entity.async_write_ha_state()
        _LOGGER.debug("Room %s: state snapshot expired", self.name)

    async def _stop_speakers(self, speaker_ids: list[str]) -> None:
        coros = [
            self._call_service("media_player", "media_stop", entity_id=speaker_id)
            for speaker_id in speaker_ids
        ]
        await asyncio.gather(*coros, return_exceptions=True)

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

    def _reset_timeout_minutes(self) -> int:
        """Effective reset countdown: the full room reset supersedes the
        automations-only presence reset when both are configured."""
        room_timeout = self.config[CONF_ROOM_RESET_TIMEOUT]
        if room_timeout > 0:
            return room_timeout
        return self.config[CONF_PRESENCE_RESET_TIMEOUT]

    def _start_presence_reset_timer(self) -> None:
        self._cancel_presence_reset_timer()
        timeout_minutes = self._reset_timeout_minutes()
        if timeout_minutes > 0:
            self._presence_reset_timer = async_call_later(
                self.hass, timeout_minutes * 60, self._on_presence_reset_timer
            )

    @callback
    def _on_presence_reset_timer(self, _now: Any) -> None:
        self._presence_reset_timer = None
        self.hass.async_create_task(self._on_presence_reset())

    async def _on_presence_reset(self) -> None:
        """Runs after the room has been continuously undetected for the reset timeout.

        presence_reset_timeout mode: lift a stale override (re-enable presence
        automations); a no-op when no override is active.
        room_reset_timeout mode: additionally converge the room to its empty
        baseline (lights and fans off, speakers stopped, room sleep mode off),
        override or not, so nothing left running in an empty room (sleep sounds,
        forced-on lights) stays on until the next manual intervention.
        """
        if self._is_present:
            return
        full_reset = self.config[CONF_ROOM_RESET_TIMEOUT] > 0
        if not full_reset and self._presence_lighting_enabled:
            return
        _LOGGER.debug(
            "Room %s: no presence for %d min, %s",
            self.name,
            self._reset_timeout_minutes(),
            "resetting room" if full_reset else "re-enabling presence automations",
        )
        if not self._presence_lighting_enabled:
            self.set_presence_lighting_enabled(True)
            if self.presence_lighting_switch:
                self.presence_lighting_switch.async_write_ha_state()
            if self.diagnostic_entity:
                self.diagnostic_entity.async_write_ha_state()

        if not full_reset:
            return

        coros: list = []
        if self.is_lights_on():
            coros.append(
                self._call_service(
                    "light",
                    "turn_off",
                    entity_id=self.light_entities,
                    transition=self.config[CONF_TRANSITION_OFF],
                )
            )
        for fan in self.config[CONF_FANS]:
            coros.append(self._call_service("fan", "turn_off", entity_id=fan))
        for speaker in self.config[CONF_SPEAKERS]:
            coros.append(self._call_service("media_player", "media_stop", entity_id=speaker))
        if self.sleep_mode_id:
            coros.append(self._call_service("switch", "turn_off", entity_id=self.sleep_mode_id))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    def _cancel_presence_reset_timer(self) -> None:
        if self._presence_reset_timer:
            self._presence_reset_timer()
            self._presence_reset_timer = None

    def cancel_timers(self) -> None:
        self._cancel_bed_exit_timer()
        self._cancel_presence_off_timer()
        self._cancel_presence_reset_timer()
        self._clear_snapshot()

    def register_context(self, context_id: str) -> None:
        """Record a context id as self-induced so handle_light_change ignores its echo.

        Used for this room's own service calls and for manager-issued sleep-light
        calls that target entities this room also controls.
        """
        if context_id in self._our_context_ids:
            return
        if len(self._our_context_order) == self._our_context_order.maxlen:
            evicted = self._our_context_order.popleft()
            self._our_context_ids.discard(evicted)
        self._our_context_order.append(context_id)
        self._our_context_ids.add(context_id)

    async def _call_service(
        self,
        domain: str,
        service: str,
        entity_id: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        if domain == "light" and entity_id:
            # A light may be shared with another room; register the context with every
            # room controlling it so none of them misreads the echo as manual.
            targets = [entity_id] if isinstance(entity_id, str) else entity_id
            context = self._manager.context_for_lights(targets)
        else:
            context = Context()
        self.register_context(context.id)

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


# Light color attribute to snapshot for each color_mode, mapped to its light.turn_on
# kwarg. color_temp_kelvin is preferred over the deprecated mireds color_temp.
COLOR_MODE_ATTRS = {
    "color_temp": "color_temp_kelvin",
    "hs": "hs_color",
    "rgb": "rgb_color",
    "rgbw": "rgbw_color",
    "rgbww": "rgbww_color",
    "xy": "xy_color",
}


def _snapshot_states(
    hass: HomeAssistant,
    entity_ids: list[str],
    capture: Callable[[State], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Capture the restorable state of each available entity via the given extractor."""
    captured: dict[str, dict[str, Any]] = {}
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state:
            captured[entity_id] = capture(state)
    return captured


def _capture_fan_state(state: State) -> dict[str, Any]:
    """Snapshot a fan's restorable attributes (speed percentage and preset)."""
    return {
        "state": state.state,
        "percentage": state.attributes.get("percentage"),
        "preset_mode": state.attributes.get("preset_mode"),
    }


def _capture_speaker_state(state: State) -> dict[str, Any]:
    """Snapshot a media player's playback state."""
    return {"state": state.state}


def _capture_light_state(state: State) -> dict[str, Any]:
    """Snapshot a light's restorable attributes: brightness, the color matching its
    color_mode, and effect."""
    attributes = state.attributes
    color_mode = attributes.get("color_mode")
    captured: dict[str, Any] = {
        "state": state.state,
        "brightness": attributes.get("brightness"),
        "color_mode": color_mode,
        "effect": attributes.get("effect"),
    }
    color_attr = COLOR_MODE_ATTRS.get(color_mode)
    if color_attr is not None:
        value = attributes.get(color_attr)
        if value is not None:
            captured[color_attr] = list(value) if isinstance(value, list | tuple) else value
    return captured


def _light_restore_data(attrs: dict[str, Any]) -> dict[str, Any]:
    """Build light.turn_on kwargs from a captured light snapshot."""
    data: dict[str, Any] = {}
    if attrs.get("brightness") is not None:
        data["brightness"] = attrs["brightness"]
    color_attr = COLOR_MODE_ATTRS.get(attrs.get("color_mode"))
    if color_attr is not None and attrs.get(color_attr) is not None:
        data[color_attr] = attrs[color_attr]
    effect = attrs.get("effect")
    if effect and effect != "None":
        data["effect"] = effect
    return data
