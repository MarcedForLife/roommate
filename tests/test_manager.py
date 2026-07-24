"""Tests for Roommate manager logic."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_ON
from homeassistant.core import Context, HomeAssistant, ServiceCall, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.roommate.const import CONF_BED_RETURN_TIMEOUT, DOMAIN
from custom_components.roommate.manager import RoommateManager


async def test_presence_detection(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    assert not room.is_present

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()
    assert room.is_present


async def test_presence_combined_with_bed(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]

    # Motion on, bed off
    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    hass.states.async_set("binary_sensor.bed_occupancy", "off")
    room.handle_presence_change()
    assert room.is_present

    # Motion off, bed on, still present
    hass.states.async_set("binary_sensor.bedroom_presence", "off")
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    room.handle_presence_change()
    assert room.is_present

    # Both off
    hass.states.async_set("binary_sensor.bed_occupancy", "off")
    room.handle_presence_change()
    assert not room.is_present


async def test_manual_override_off(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()

    room.handle_light_change(STATE_ON, "off", None)
    assert not room.presence_lighting_enabled


async def test_manual_override_on(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()

    room.handle_light_change(STATE_ON, "off", None)
    room.handle_light_change("off", STATE_ON, None)
    assert room.presence_lighting_enabled


async def test_manual_override_ignores_own_context(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()

    ctx = Context()
    room._our_context_ids.add(ctx.id)
    room.handle_light_change(STATE_ON, "off", ctx)
    assert room.presence_lighting_enabled


async def test_manual_override_not_triggered_when_absent(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    room.handle_light_change(STATE_ON, "off", None)
    assert room.presence_lighting_enabled


async def test_occupant_count(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("sensor.bed_occupants", "0")
    assert room.get_occupant_count() == 0

    hass.states.async_set("sensor.bed_occupants", "2")
    assert room.get_occupant_count() == 2


async def test_occupant_count_fallback_to_bed_sensor(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    bed_config = room.config["sensors"]["bed"]
    original = bed_config.pop("occupants")

    try:
        hass.states.async_set("binary_sensor.bed_occupancy", "off")
        assert room.get_occupant_count() == 0

        hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
        assert room.get_occupant_count() == 1
    finally:
        bed_config["occupants"] = original


async def test_occupant_count_handles_invalid_state(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("sensor.bed_occupants", "unavailable")
    assert room.get_occupant_count() == 0

    # An invalid count falls back to the binary bed sensor instead of reading 0.
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    assert room.get_occupant_count() == 1


async def test_is_lights_on(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    assert not room.is_lights_on()

    hass.states.async_set("light.lamp_1", STATE_ON)
    assert room.is_lights_on()


async def test_on_presence_detected_calls_light_service(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_presence_detected()
        mock.assert_called_once_with(
            "light", "turn_on", entity_id=["light.lamp_1", "light.lamp_2"], transition=2
        )


async def test_on_presence_detected_skipped_when_overridden(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    room.set_presence_lighting_enabled(False)

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_presence_detected()
        mock.assert_not_called()


async def test_on_presence_detected_skipped_when_room_is_bright(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("sensor.illuminance", "5000")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_presence_detected()
        mock.assert_not_called()


async def test_on_presence_detected_fires_when_room_is_dark(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("sensor.illuminance", "100")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_presence_detected()
        mock.assert_called_once()


async def test_illuminance_gate_disabled_bypasses_threshold(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("sensor.illuminance", "5000")
    room.set_illuminance_gate_enabled(False)

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_presence_detected()
        mock.assert_called_once()


async def test_room_illuminance_threshold_overrides_global(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    # Global threshold is 4000; room override 200 makes 1500 lux too bright
    room.config["illuminance_threshold"] = 200
    hass.states.async_set("sensor.illuminance", "1500")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_presence_detected()
        mock.assert_not_called()


async def test_on_getting_in_bed_dims_lights(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]

    # Set lights on with an old last_changed (not recently turned on)
    old_time = dt_util.utcnow() - timedelta(minutes=5)
    hass.states.async_set("light.lamp_1", STATE_ON)
    hass.states.async_set("light.lamp_2", STATE_ON)
    hass.states.get("light.lamp_1").last_changed = old_time
    hass.states.get("light.lamp_2").last_changed = old_time

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_getting_in_bed()
        mock.assert_called_once()
        assert mock.call_args.kwargs["brightness_pct"] == 5


async def test_on_getting_in_bed_turns_off_when_recently_on(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]

    # Lights just turned on (last_changed is now)
    hass.states.async_set("light.lamp_1", STATE_ON)
    hass.states.async_set("light.lamp_2", STATE_ON)

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_getting_in_bed()
        mock.assert_called_once()
        assert mock.call_args.args[1] == "turn_off"


async def test_on_getting_in_bed_skipped_when_lights_off(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_getting_in_bed()
        mock.assert_not_called()


async def test_on_leaving_bed_turns_off_fans(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_leaving_bed()
        fan_calls = [c for c in mock.call_args_list if c.args[0] == "fan"]
        assert len(fan_calls) == 1
        assert fan_calls[0].kwargs["entity_id"] == "fan.bedroom_fan"

    room.cancel_timers()


async def test_on_leaving_bed_pauses_playing_speakers(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("media_player.bedroom_speaker", "playing")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_leaving_bed()
        speaker_calls = [c for c in mock.call_args_list if c.args[0] == "media_player"]
        assert len(speaker_calls) == 1
        assert speaker_calls[0].args[1] == "media_pause"

    room.cancel_timers()


async def test_on_leaving_bed_skips_non_playing_speakers(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("media_player.bedroom_speaker", "idle")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_leaving_bed()
        speaker_calls = [c for c in mock.call_args_list if c.args[0] == "media_player"]
        assert len(speaker_calls) == 0

    room.cancel_timers()


async def test_on_leaving_bed_stops_speakers_when_snapshot_disabled(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    room.config[CONF_BED_RETURN_TIMEOUT] = 0
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("media_player.bedroom_speaker", "playing")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_leaving_bed()
        speaker_calls = [c for c in mock.call_args_list if c.args[0] == "media_player"]
        assert len(speaker_calls) == 1
        assert speaker_calls[0].args[1] == "media_stop"


async def test_paused_speaker_resumes_on_quick_return(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("media_player.bedroom_speaker", "playing")

    with patch.object(room, "_call_service", new_callable=AsyncMock):
        await room._on_leaving_bed()

    assert room._pre_exit_snapshot["speakers"]["media_player.bedroom_speaker"]["state"] == "playing"

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_getting_in_bed()
        speaker_calls = [c for c in mock.call_args_list if c.args[0] == "media_player"]
        assert len(speaker_calls) == 1
        assert speaker_calls[0].args[1] == "media_play"


async def test_paused_speaker_stops_on_snapshot_expiry(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("media_player.bedroom_speaker", "playing")

    with patch.object(room, "_call_service", new_callable=AsyncMock):
        await room._on_leaving_bed()

    timeout = room.config[CONF_BED_RETURN_TIMEOUT]
    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=timeout + 1))
        await hass.async_block_till_done()
        speaker_calls = [c for c in mock.call_args_list if c.args[0] == "media_player"]
        assert len(speaker_calls) == 1
        assert speaker_calls[0].args[1] == "media_stop"


async def test_snapshot_restore_on_quick_return(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("fan.bedroom_fan", STATE_ON, {"percentage": 50})

    with patch.object(room, "_call_service", new_callable=AsyncMock):
        await room._on_leaving_bed()

    assert room._pre_exit_snapshot is not None
    assert room._pre_exit_snapshot["fans"]["fan.bedroom_fan"]["percentage"] == 50

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_getting_in_bed()
        fan_calls = [c for c in mock.call_args_list if c.args[0] == "fan"]
        assert len(fan_calls) == 1
        assert fan_calls[0].kwargs["percentage"] == 50

    assert room._pre_exit_snapshot is None
    room.cancel_timers()


async def test_snapshot_expires(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")

    with patch.object(room, "_call_service", new_callable=AsyncMock):
        await room._on_leaving_bed()

    assert room._pre_exit_snapshot is not None

    timeout = room.config[CONF_BED_RETURN_TIMEOUT]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=timeout + 1))
    await hass.async_block_till_done()

    assert room._pre_exit_snapshot is None


async def test_bed_automations_disabled_skips_bed_change(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    room.set_bed_automations_enabled(False)

    with patch.object(room, "_on_getting_in_bed", new_callable=AsyncMock) as mock:
        room.handle_bed_change("off", STATE_ON)
        mock.assert_not_called()


async def test_presence_lighting_reenabled_on_bed_exit(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """Test that presence lighting is re-enabled when leaving bed, even if lights are off."""
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()

    # Manual light off while present disables presence lighting
    room.handle_light_change(STATE_ON, "off", None)
    assert not room.presence_lighting_enabled

    # Leave bed with lights off
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")

    with patch.object(room, "_call_service", new_callable=AsyncMock):
        await room._on_leaving_bed()

    assert room.presence_lighting_enabled
    room.cancel_timers()


async def test_guest_mode(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    assert not manager.guest_mode
    manager.set_guest_mode(True)
    assert manager.guest_mode


async def test_bed_persons_drives_sleep_participation(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    assert room.bed_persons == ["person.alice", "person.bob"]


async def test_everyone_in_bed_check(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))
    hass.services.async_register("switch", "turn_on", lambda call: calls.append(call))

    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("sensor.bed_occupants", "2")

    await manager.async_on_sleeping(room)
    await hass.async_block_till_done()

    domains = [c.domain for c in calls]
    assert "light" in domains
    assert "switch" in domains


async def test_everyone_in_bed_with_one_away(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))
    hass.services.async_register("switch", "turn_on", lambda call: calls.append(call))

    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "not_home")
    hass.states.async_set("sensor.bed_occupants", "1")

    await manager.async_on_sleeping(room)
    await hass.async_block_till_done()

    assert len(calls) > 0  # Should trigger (1 home, 1 in bed)


async def test_everyone_in_bed_blocked_when_not_enough(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("sensor.bed_occupants", "1")

    await manager.async_on_sleeping(room)
    await hass.async_block_till_done()

    assert len(calls) == 0


async def test_waking_respects_guest_mode(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]
    manager.set_guest_mode(True)
    hass.states.async_set("switch.sleep_mode_living_room", STATE_ON)

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))

    await manager.async_on_waking(room)
    await hass.async_block_till_done()

    assert len(calls) == 0


async def test_waking_skipped_when_no_sleep_mode_active(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))

    # No sleep_mode_living_room set to on, daytime bed sensor toggle shouldn't fire sleep lights
    await manager.async_on_waking(room)
    await hass.async_block_till_done()

    assert len(calls) == 0


async def test_waking_respects_per_light_inhibitors(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))

    # Theatre lighting is on, should inhibit living_room but not toilet
    hass.states.async_set("switch.theatre_lighting", STATE_ON)
    hass.states.async_set("switch.sleep_mode_living_room", STATE_ON)

    await manager.async_on_waking(room)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["light.toilet_light"]


async def test_waking_all_lights_when_no_inhibitors_active(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))

    # Theatre lighting is off, all lights should activate
    hass.states.async_set("switch.theatre_lighting", "off")
    hass.states.async_set("switch.sleep_mode_living_room", STATE_ON)

    await manager.async_on_waking(room)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert set(calls[0].data["entity_id"]) == {"light.living_room", "light.toilet_light"}


async def test_everyone_up_disables_sleep_modes(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    manager = setup_integration
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("switch", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("sensor.bed_occupants", "0")
    hass.states.async_set("binary_sensor.bed_occupancy", "off")

    await manager.async_on_everyone_up(room)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].domain == "switch"


async def test_state_restored_on_entity_appearance(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """Test that room state is corrected when sensor entities first appear after startup."""
    room = setup_integration.rooms["bedroom"]

    # Before any sensor states are set, room should be vacant
    assert not room.is_present
    assert not room.is_in_bed

    # Simulate sensors appearing after startup (old_state=None).
    # async_set on a new entity fires STATE_CHANGED with old_state=None.
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    await hass.async_block_till_done()

    assert room.is_in_bed
    assert room.is_present


async def test_state_restored_on_recovery_from_unavailable(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """Test that room state is corrected when a sensor recovers from unavailable."""
    room = setup_integration.rooms["bedroom"]

    # Sensor starts available, then goes unavailable, then recovers
    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    await hass.async_block_till_done()
    assert room.is_present

    hass.states.async_set("binary_sensor.bedroom_presence", "unavailable")
    await hass.async_block_till_done()

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    await hass.async_block_till_done()
    assert room.is_present


def _binary_bed_config(persons: list[str]) -> dict:
    """Config with a binary-only bed (no occupant count) participating in sleep."""
    return {
        DOMAIN: {
            "sleep_lights": ["light.living_room"],
            "sleep_modes": ["switch.house_sleep_mode"],
            "rooms": {
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "bed": {
                            "presence": "binary_sensor.bed_occupancy",
                            "persons": persons,
                        },
                    },
                    "lights": ["light.bedroom_lamp"],
                },
            },
        },
    }


async def test_binary_bed_triggers_household_sleep(hass: HomeAssistant, make_manager) -> None:
    """A binary-only bed must activate household sleep on bed entry."""
    manager = await make_manager(_binary_bed_config(["person.alice"]))
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))
    hass.services.async_register("switch", "turn_on", lambda call: calls.append(call))

    hass.states.async_set("person.alice", "home")
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    room.handle_bed_change("off", STATE_ON)
    await hass.async_block_till_done()

    domains = {c.domain for c in calls}
    assert "light" in domains  # sleep lights turned off
    assert "switch" in domains  # sleep modes turned on


async def test_two_person_binary_bed_can_sleep(hass: HomeAssistant, make_manager) -> None:
    """Two assigned persons on a single binary mat must not block sleep."""
    manager = await make_manager(_binary_bed_config(["person.alice", "person.bob"]))
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))
    hass.services.async_register("switch", "turn_on", lambda call: calls.append(call))

    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)

    await manager.async_on_sleeping(room)
    await hass.async_block_till_done()

    assert len(calls) > 0  # binary "occupied" counts as both persons in bed


def _overlap_config() -> dict:
    """A room whose light is also a global sleep light, plus a bedroom that drives sleep."""
    return {
        DOMAIN: {
            "sleep_lights": ["light.living_room"],
            "sleep_modes": ["switch.house_sleep_mode"],
            "rooms": {
                "living_room": {
                    "sensors": {"presence": "binary_sensor.living_presence"},
                    "lights": ["light.living_room"],
                },
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "bed": {
                            "presence": "binary_sensor.bed_occupancy",
                            "persons": ["person.alice"],
                        },
                    },
                    "lights": ["light.bedroom_lamp"],
                },
            },
        },
    }


def _propagate_light_state(hass: HomeAssistant, state: str):
    """Service handler that applies the requested light state, carrying the call context
    through to the resulting state-change event (as a real light integration would).

    Must be a @callback so it runs in the event loop; a plain function would run in an
    executor thread where async_set raises and the state-change echo never fires.
    """

    @callback
    def _handler(call: ServiceCall) -> None:
        ids = call.data["entity_id"]
        for entity_id in [ids] if isinstance(ids, str) else ids:
            hass.states.async_set(entity_id, state, context=call.context)

    return _handler


async def test_sleep_light_off_not_treated_as_manual_override(
    hass: HomeAssistant, make_manager
) -> None:
    """Sleep turning off an overlapping room light must not flip that room to overridden."""
    manager = await make_manager(_overlap_config())
    living = manager.rooms["living_room"]
    bedroom = manager.rooms["bedroom"]

    hass.services.async_register("light", "turn_off", _propagate_light_state(hass, "off"))
    hass.services.async_register("switch", "turn_on", lambda call: None)

    hass.states.async_set("binary_sensor.living_presence", STATE_ON)
    living.handle_presence_change()
    hass.states.async_set("light.living_room", STATE_ON)
    assert living.is_present
    assert living.presence_lighting_enabled

    hass.states.async_set("person.alice", "home")
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    await manager.async_on_sleeping(bedroom)
    await hass.async_block_till_done()

    assert living.presence_lighting_enabled  # not misread as a manual override


async def test_sleep_light_on_does_not_wipe_manual_override(
    hass: HomeAssistant, make_manager
) -> None:
    """Waking turning on an overlapping sleep light must not re-enable a real override."""
    manager = await make_manager(_overlap_config())
    living = manager.rooms["living_room"]
    bedroom = manager.rooms["bedroom"]

    hass.services.async_register("light", "turn_on", _propagate_light_state(hass, STATE_ON))

    # Living room present, then the user manually turns the light off (a real override).
    hass.states.async_set("binary_sensor.living_presence", STATE_ON)
    living.handle_presence_change()
    hass.states.async_set("light.living_room", STATE_ON)
    living.handle_light_change(STATE_ON, "off", Context())
    hass.states.async_set("light.living_room", "off")
    assert not living.presence_lighting_enabled

    # Someone gets up; sleep mode active so waking turns the sleep light back on.
    hass.states.async_set("switch.house_sleep_mode", STATE_ON)
    await manager.async_on_waking(bedroom)
    await hass.async_block_till_done()

    assert not living.presence_lighting_enabled  # override preserved


async def test_room_light_call_ignored_by_room_sharing_the_light(
    hass: HomeAssistant, make_manager
) -> None:
    """A room's own light call must not read as a manual override in a room sharing it."""
    config = {
        DOMAIN: {
            "rooms": {
                "study": {
                    "sensors": {"presence": "binary_sensor.study_presence"},
                    "lights": ["light.shared", "light.study_lamp"],
                },
                "hall": {
                    "sensors": {"presence": "binary_sensor.hall_presence"},
                    "lights": ["light.shared"],
                },
            },
        },
    }
    manager = await make_manager(config)
    study = manager.rooms["study"]
    hall = manager.rooms["hall"]

    hass.services.async_register("light", "turn_on", _propagate_light_state(hass, STATE_ON))

    hass.states.async_set("light.shared", "off")
    hass.states.async_set("binary_sensor.study_presence", "off")
    await hass.async_block_till_done()

    # The hall's lighting is overridden; the study's automation turning the shared
    # light on must not be misread as a manual light-on that clears the override.
    hall.set_presence_lighting_enabled(False)

    hass.states.async_set("binary_sensor.study_presence", STATE_ON)
    await hass.async_block_till_done()
    # The tracker defers dispatch via loop.call_soon, and the light echo is induced
    # one dispatch deep (presence event -> light call), so settle one more iteration.
    await hass.async_block_till_done()

    assert study.presence_lighting_enabled
    assert not hall.presence_lighting_enabled  # override preserved


async def test_recovery_runs_lost_bed_exit(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """A bed exit that happens while the sensor is unavailable still runs on recovery."""
    room = setup_integration.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("fan", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    await hass.async_block_till_done()
    assert room.is_in_bed
    hass.states.async_set("fan.bedroom_fan", STATE_ON)

    # Sensor drops out, then recovers reporting the person already left.
    hass.states.async_set("binary_sensor.bed_occupancy", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.bed_occupancy", "off")
    await hass.async_block_till_done()

    assert not room.is_in_bed
    assert any(c.domain == "fan" for c in calls)  # lost leaving-bed actions ran


async def test_recovery_runs_lost_presence_off(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """A presence-ended that happens during an unavailable gap turns lights off on recovery."""
    room = setup_integration.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    await hass.async_block_till_done()
    assert room.is_present

    hass.states.async_set("binary_sensor.bedroom_presence", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.bedroom_presence", "off")
    await hass.async_block_till_done()

    assert not room.is_present
    assert any(c.domain == "light" for c in calls)  # lost presence-off ran


async def test_first_appearance_takes_no_action(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """First sensor appearance at startup updates state but must not actuate."""
    room = setup_integration.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))
    hass.services.async_register("fan", "turn_off", lambda call: calls.append(call))

    # old_state is None -> passive re-read, no side effects.
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    await hass.async_block_till_done()

    assert room.is_in_bed
    assert room.is_present
    assert len(calls) == 0


async def test_light_recovery_does_not_resync_bed(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """A recovering light must not misread a still-unavailable bed sensor as a bed exit."""
    room = setup_integration.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("fan", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("sensor.bed_occupants", "0")  # count sensor sees nobody
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    hass.states.async_set("light.lamp_1", STATE_ON)
    await hass.async_block_till_done()
    assert room.is_in_bed

    hass.states.async_set("binary_sensor.bed_occupancy", "unavailable")
    hass.states.async_set("light.lamp_1", "unavailable")
    await hass.async_block_till_done()

    hass.states.async_set("light.lamp_1", "off")  # light recovers, bed still unavailable
    await hass.async_block_till_done()

    assert room.is_in_bed  # no phantom bed exit
    assert len(calls) == 0


async def test_occupant_recovery_dispatches_household(hass: HomeAssistant, make_manager) -> None:
    """A last-person-up transition hidden by an unavailable gap still ends sleep."""
    config = {
        DOMAIN: {
            "sleep_modes": ["switch.house_sleep_mode"],
            "rooms": {
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "bed": {"occupants": "sensor.bed_count", "persons": ["person.alice"]},
                    },
                    "lights": ["light.bedroom_lamp"],
                },
            },
        },
    }
    manager = await make_manager(config)
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("switch", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("sensor.bed_count", "1")
    await hass.async_block_till_done()
    assert room.is_in_bed

    hass.states.async_set("switch.house_sleep_mode", STATE_ON)
    hass.states.async_set("sensor.bed_count", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.bed_count", "0")
    await hass.async_block_till_done()

    assert not room.is_in_bed
    assert any(c.domain == "switch" for c in calls)  # everyone-up ran on recovery


async def test_presence_off_rechecks_live_presence(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """_on_presence_ended must skip the turn-off if the room is present again.

    The default presence_off_delay is 0, so the off action is scheduled directly with
    no debounce; a quick off->on flap must not turn the lights off under the room.
    """
    room = setup_integration.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))

    # Presence has returned by the time the scheduled off action runs.
    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()
    assert room.is_present

    await room._on_presence_ended()

    assert len(calls) == 0  # lights not turned off while present


async def test_bed_exit_timer_cancelled_when_automations_disabled(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """Disabling bed automations cancels a pending bed-exit timer."""
    room = setup_integration.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("fan", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    room.handle_bed_change("off", STATE_ON)
    hass.states.async_set("binary_sensor.bed_occupancy", "off")
    room.handle_bed_change(STATE_ON, "off")
    assert room.bed_exit_timer_active

    room.set_bed_automations_enabled(False)
    assert not room.bed_exit_timer_active

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=15))
    await hass.async_block_till_done()
    assert len(calls) == 0


async def test_occupant_bed_exit_uses_debounce(hass: HomeAssistant, make_manager) -> None:
    """Occupant-count bed exit goes through the bed-exit delay like a binary bed."""
    config = {
        DOMAIN: {
            "rooms": {
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "bed": {"occupants": "sensor.bed_count"},
                    },
                    "lights": ["light.bedroom_lamp"],
                    "fans": ["fan.bedroom_fan"],
                },
            },
        },
    }
    manager = await make_manager(config)
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("fan", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("sensor.bed_count", "1")
    room.handle_occupant_change("0", "1")
    assert room.is_in_bed

    hass.states.async_set("sensor.bed_count", "0")
    room.handle_occupant_change("1", "0")
    assert not room.is_in_bed
    assert room.bed_exit_timer_active
    await hass.async_block_till_done()
    assert len(calls) == 0  # debounced, not fired yet

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=15))
    await hass.async_block_till_done()
    assert any(c.domain == "fan" for c in calls)


async def test_everyone_up_ignores_non_participating_bed(hass: HomeAssistant, make_manager) -> None:
    """A bed without bed_persons must not keep household sleep modes on."""
    config = {
        DOMAIN: {
            "sleep_modes": ["switch.house_sleep_mode"],
            "rooms": {
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "bed": {"occupants": "sensor.bed_count", "persons": ["person.alice"]},
                    },
                    "lights": ["light.bedroom_lamp"],
                },
                "guest_room": {
                    "sensors": {
                        "presence": "binary_sensor.guest_presence",
                        "bed": {"occupants": "sensor.guest_count"},
                    },
                    "lights": ["light.guest_lamp"],
                },
            },
        },
    }
    manager = await make_manager(config)
    bedroom = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("switch", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("sensor.bed_count", "0")  # the household sleeper is up
    hass.states.async_set("sensor.guest_count", "1")  # unrelated guest still in bed

    await manager.async_on_everyone_up(bedroom)
    await hass.async_block_till_done()

    assert len(calls) == 1  # sleep modes disabled despite the guest bed


async def test_waking_honors_room_illuminance_gate(hass: HomeAssistant, make_manager) -> None:
    """Disabling a room's illuminance gate makes sleep lights fire even when bright."""
    config = {
        DOMAIN: {
            "illuminance_sensor": "sensor.lux",
            "illuminance_threshold": 100,
            "sleep_lights": ["light.hall"],
            "sleep_modes": ["switch.house_sleep_mode"],
            "rooms": {
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "bed": {
                            "presence": "binary_sensor.bed_occupancy",
                            "persons": ["person.alice"],
                        },
                    },
                    "lights": ["light.bedroom_lamp"],
                },
            },
        },
    }
    manager = await make_manager(config)
    room = manager.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))

    hass.states.async_set("switch.house_sleep_mode", STATE_ON)
    hass.states.async_set("sensor.lux", "500")  # above threshold -> gated

    await manager.async_on_waking(room)
    await hass.async_block_till_done()
    assert len(calls) == 0

    room.set_illuminance_gate_enabled(False)
    await manager.async_on_waking(room)
    await hass.async_block_till_done()
    assert len(calls) == 1  # gate off -> sleep lights fire despite brightness


async def test_illuminance_threshold_zero_disables_gating(
    hass: HomeAssistant, make_manager
) -> None:
    """An effective illuminance threshold of 0 means gating off, not always-skip."""
    config = {
        DOMAIN: {
            "illuminance_sensor": "sensor.lux",
            "illuminance_threshold": 0,
            "rooms": {
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "illuminance": "sensor.lux",
                    },
                    "lights": ["light.bedroom_lamp"],
                },
            },
        },
    }
    manager = await make_manager(config)
    room = manager.rooms["bedroom"]

    hass.states.async_set("sensor.lux", "5000")
    assert room.should_skip_for_illuminance() is False


async def test_leaving_bed_aborts_on_reentry(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """If the user returns to bed mid-leave, the rest of the leave actions abort."""
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("fan.bedroom_fan", STATE_ON)

    async def fake_call(domain: str, service: str, **kwargs: object) -> None:
        if domain == "switch" and service == "turn_off":
            room._is_in_bed = True  # back in bed while the sleep-mode call is awaiting

    mock = AsyncMock(side_effect=fake_call)
    with patch.object(room, "_call_service", mock):
        await room._on_leaving_bed()

    assert not [c for c in mock.call_args_list if c.args[0] == "fan"]  # leave aborted

    room.cancel_timers()


async def test_leaving_bed_speaker_pause_uses_presnapshot_state(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """Speaker pause/stop is decided from the pre-await snapshot state."""
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")
    hass.states.async_set("media_player.bedroom_speaker", "playing")

    async def fake_call(domain: str, service: str, **kwargs: object) -> None:
        if domain == "switch" and service == "turn_off":
            room._pre_exit_snapshot = None  # snapshot cleared mid-await (not a re-entry)

    mock = AsyncMock(side_effect=fake_call)
    with patch.object(room, "_call_service", mock):
        await room._on_leaving_bed()

    speaker_calls = [c for c in mock.call_args_list if c.args[0] == "media_player"]
    assert len(speaker_calls) == 1
    assert speaker_calls[0].args[1] == "media_pause"  # not media_stop

    room.cancel_timers()


async def test_recently_on_uses_latest_on_light(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """The recently-on decision keys off the on-light, not light_entities[0]."""
    room = setup_integration.rooms["bedroom"]

    # First configured light is OFF and changed just now; the other is ON but old.
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", STATE_ON)
    hass.states.get("light.lamp_2").last_changed = dt_util.utcnow() - timedelta(minutes=5)

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_getting_in_bed()
        mock.assert_called_once()
        # lamp_2 has been on for 5 minutes -> dim, not turn off.
        assert mock.call_args.kwargs.get("brightness_pct") == 5


async def test_occupant_change_refreshes_presence(hass: HomeAssistant, make_manager) -> None:
    """An occupants-only room's combined presence updates on occupant changes."""
    config = {
        DOMAIN: {
            "rooms": {
                "bedroom": {
                    "sensors": {
                        "presence": "binary_sensor.bedroom_presence",
                        "bed": {"occupants": "sensor.bed_count"},
                    },
                    "lights": ["light.bedroom_lamp"],
                },
            },
        },
    }
    manager = await make_manager(config)
    room = manager.rooms["bedroom"]

    hass.states.async_set("binary_sensor.bedroom_presence", "off")
    hass.states.async_set("sensor.bed_count", "0")
    await hass.async_block_till_done()
    assert not room.is_present

    hass.states.async_set("sensor.bed_count", "2")
    await hass.async_block_till_done()
    assert room.is_present  # combined presence reflects bed occupancy


async def test_bed_occupied_is_union_of_sensors(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """With both bed sensors, either reporting occupancy counts as occupied."""
    room = setup_integration.rooms["bedroom"]

    hass.states.async_set("binary_sensor.bed_occupancy", "off")
    hass.states.async_set("sensor.bed_occupants", "2")
    assert room._is_bed_occupied()

    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    hass.states.async_set("sensor.bed_occupants", "0")
    assert room._is_bed_occupied()

    hass.states.async_set("binary_sensor.bed_occupancy", "off")
    hass.states.async_set("sensor.bed_occupants", "0")
    assert not room._is_bed_occupied()


async def test_presence_held_while_bed_sensor_unavailable(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """A presence flicker while the bed sensor is unavailable must not end presence."""
    room = setup_integration.rooms["bedroom"]

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    await hass.async_block_till_done()
    assert room.is_in_bed
    assert room.is_present

    hass.states.async_set("binary_sensor.bed_occupancy", "unavailable")
    hass.states.async_set("binary_sensor.bedroom_presence", "off")
    await hass.async_block_till_done()

    assert room.is_present  # held by the cached bed state
    assert len(calls) == 0


async def test_presence_detected_skipped_while_in_bed(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """Presence flipping on via the bed union must not blast lights while in bed."""
    room = setup_integration.rooms["bedroom"]
    room._is_in_bed = True

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_presence_detected()
        mock.assert_not_called()


async def test_leaving_bed_noop_when_already_back_in_bed(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """A leave task that runs after a re-entry must not act at all."""
    room = setup_integration.rooms["bedroom"]
    room._is_in_bed = True

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_leaving_bed()
        mock.assert_not_called()

    assert room._pre_exit_snapshot is None


def _two_person_household_config() -> dict:
    """Two separate bedrooms, each with one assigned person, sharing the household."""
    return {
        DOMAIN: {
            "sleep_lights": ["light.hall"],
            "sleep_modes": ["switch.house_sleep_mode"],
            "rooms": {
                "alice_room": {
                    "sensors": {
                        "presence": "binary_sensor.alice_presence",
                        "bed": {"occupants": "sensor.alice_count", "persons": ["person.alice"]},
                    },
                    "lights": ["light.alice_lamp"],
                },
                "bob_room": {
                    "sensors": {
                        "presence": "binary_sensor.bob_presence",
                        "bed": {"occupants": "sensor.bob_count", "persons": ["person.bob"]},
                    },
                    "lights": ["light.bob_lamp"],
                },
            },
        },
    }


async def test_multi_room_sleep_requires_all_rooms(hass: HomeAssistant, make_manager) -> None:
    """Household sleep activates only once every participating room is occupied."""
    manager = await make_manager(_two_person_household_config())

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_off", lambda call: calls.append(call))
    hass.services.async_register("switch", "turn_on", lambda call: calls.append(call))

    hass.states.async_set("person.alice", "home")
    hass.states.async_set("person.bob", "home")
    hass.states.async_set("sensor.alice_count", "1")
    hass.states.async_set("sensor.bob_count", "0")

    await manager.async_on_sleeping(manager.rooms["alice_room"])
    await hass.async_block_till_done()
    assert len(calls) == 0  # bob is still up

    hass.states.async_set("sensor.bob_count", "1")
    await manager.async_on_sleeping(manager.rooms["bob_room"])
    await hass.async_block_till_done()
    assert len(calls) > 0  # everyone in bed -> sleep


async def test_multi_room_everyone_up_requires_all_empty(hass: HomeAssistant, make_manager) -> None:
    """Sleep modes stay on until every participating bed is empty."""
    manager = await make_manager(_two_person_household_config())

    calls: list[ServiceCall] = []
    hass.services.async_register("switch", "turn_off", lambda call: calls.append(call))

    hass.states.async_set("sensor.alice_count", "0")
    hass.states.async_set("sensor.bob_count", "1")

    await manager.async_on_everyone_up(manager.rooms["alice_room"])
    await hass.async_block_till_done()
    assert len(calls) == 0  # bob is still in bed

    hass.states.async_set("sensor.bob_count", "0")
    await manager.async_on_everyone_up(manager.rooms["bob_room"])
    await hass.async_block_till_done()
    assert len(calls) > 0  # everyone up -> sleep modes off


async def test_service_failure_does_not_propagate(hass: HomeAssistant, make_manager) -> None:
    """A failing service call is logged, not raised, so coordination still completes."""
    manager = await make_manager(_two_person_household_config())

    def boom(call: ServiceCall) -> None:
        raise RuntimeError("boom")

    hass.services.async_register("switch", "turn_off", boom)
    hass.states.async_set("sensor.alice_count", "0")
    hass.states.async_set("sensor.bob_count", "0")

    # Must not raise despite the failing sleep-mode service call.
    await manager.async_on_everyone_up(manager.rooms["alice_room"])
    await hass.async_block_till_done()
