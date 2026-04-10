"""Tests for Roommate manager logic."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util

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
    from homeassistant.core import Context

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


async def test_on_leaving_bed_stops_speakers(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    hass.states.async_set("light.lamp_1", "off")
    hass.states.async_set("light.lamp_2", "off")

    with patch.object(room, "_call_service", new_callable=AsyncMock) as mock:
        await room._on_leaving_bed()
        speaker_calls = [c for c in mock.call_args_list if c.args[0] == "media_player"]
        assert len(speaker_calls) == 1
        assert speaker_calls[0].args[1] == "media_stop"

    room.cancel_timers()




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
    room._clear_snapshot()
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

    calls: list[ServiceCall] = []
    hass.services.async_register("light", "turn_on", lambda call: calls.append(call))

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
