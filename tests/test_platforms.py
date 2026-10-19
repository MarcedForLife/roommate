"""Tests for the Roommate entity platforms set up through a config entry."""

from __future__ import annotations

import copy

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.roommate import CONFIG_SCHEMA
from custom_components.roommate.const import DOMAIN

PRESENCE_ID = "binary_sensor.roommate_bedroom_presence"
ROOM_STATE_ID = "sensor.roommate_bedroom_room_state"


async def _setup(hass: HomeAssistant, config: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=CONFIG_SCHEMA(config)[DOMAIN])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_room_entities_follow_room_state(hass: HomeAssistant, full_config: dict) -> None:
    await _setup(hass, full_config)
    assert hass.states.get(PRESENCE_ID).state == STATE_OFF
    assert hass.states.get(ROOM_STATE_ID).state == "empty"

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(PRESENCE_ID).state == STATE_ON
    assert hass.states.get(ROOM_STATE_ID).state == "present"

    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(ROOM_STATE_ID).state == "in_bed"
    assert hass.states.get(PRESENCE_ID).attributes["icon"] == "mdi:bed"


async def test_room_switch_drives_room(hass: HomeAssistant, full_config: dict) -> None:
    entry = await _setup(hass, full_config)
    room = entry.runtime_data.rooms["bedroom"]
    switch_id = "switch.roommate_bedroom_presence_automations"
    assert hass.states.get(switch_id).state == STATE_ON

    await hass.services.async_call("switch", "turn_off", {"entity_id": switch_id}, blocking=True)
    assert not room.presence_lighting_enabled
    assert hass.states.get(switch_id).state == STATE_OFF
    assert hass.states.get(ROOM_STATE_ID).attributes["presence_lighting"] == "overridden"

    await hass.services.async_call("switch", "turn_on", {"entity_id": switch_id}, blocking=True)
    assert room.presence_lighting_enabled
    assert hass.states.get(ROOM_STATE_ID).attributes["presence_lighting"] == "active"


async def test_room_switch_restores_last_state(hass: HomeAssistant, full_config: dict) -> None:
    mock_restore_cache(hass, [State("switch.roommate_bedroom_bed_automations", STATE_OFF)])
    entry = await _setup(hass, full_config)
    assert not entry.runtime_data.rooms["bedroom"].bed_automations_enabled
    assert hass.states.get("switch.roommate_bedroom_bed_automations").state == STATE_OFF


async def test_guest_mode_switch_restores_last_state(
    hass: HomeAssistant, full_config: dict
) -> None:
    mock_restore_cache(hass, [State("switch.roommate_guest_mode", STATE_ON)])
    entry = await _setup(hass, full_config)
    assert entry.runtime_data.guest_mode

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.roommate_guest_mode"}, blocking=True
    )
    assert not entry.runtime_data.guest_mode


async def test_optional_entities_need_their_sensor(
    hass: HomeAssistant, minimal_config: dict
) -> None:
    await _setup(hass, minimal_config)
    assert hass.states.get("switch.roommate_bedroom_presence_automations") is not None
    assert hass.states.get("switch.roommate_bedroom_bed_automations") is None
    assert hass.states.get("switch.roommate_bedroom_illuminance_gating") is None
    assert hass.states.get("number.roommate_bedroom_turn_on_transition") is not None
    assert hass.states.get("number.roommate_bedroom_dim_brightness") is None
    assert hass.states.get("button.roommate_bedroom_restore_auto_brightness") is None
    assert hass.states.get("number.roommate_illuminance_threshold") is None


async def test_room_number_persists_and_reflects_options(
    hass: HomeAssistant, full_config: dict
) -> None:
    entry = await _setup(hass, full_config)
    room = entry.runtime_data.rooms["bedroom"]
    number_id = "number.roommate_bedroom_dim_brightness"
    assert hass.states.get(number_id).state == "5"

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 42}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.options["rooms"]["bedroom"]["dim_brightness"] == 42
    assert room.config["dim_brightness"] == 42
    assert hass.states.get(number_id).state == "42"

    # An options-flow edit of the same value refreshes the number without a reload.
    new_options = copy.deepcopy(dict(entry.options))
    new_options["rooms"]["bedroom"]["dim_brightness"] = 33
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.async_block_till_done()
    assert entry.runtime_data.rooms["bedroom"] is room
    assert hass.states.get(number_id).state == "33"


async def test_global_number_persists(hass: HomeAssistant, full_config: dict) -> None:
    entry = await _setup(hass, full_config)
    number_id = "number.roommate_illuminance_threshold"

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 1200}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.options["illuminance_threshold"] == 1200
    assert entry.runtime_data.illuminance_threshold == 1200
    assert entry.runtime_data.rooms["bedroom"].illuminance_threshold == 1200
