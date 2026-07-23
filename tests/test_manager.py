"""Tests for Roommate manager logic."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_ON
from homeassistant.core import Context, HomeAssistant, ServiceCall
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
