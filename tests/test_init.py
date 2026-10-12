"""Tests for Roommate integration setup."""

from __future__ import annotations

import copy

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roommate import CONFIG_SCHEMA
from custom_components.roommate.const import DOMAIN


async def _setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up a config entry through the proper HA flow."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_entry(hass: HomeAssistant, full_config: dict) -> None:
    """Test config entry setup creates manager and loads platforms."""
    validated = CONFIG_SCHEMA(full_config)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=validated[DOMAIN])
    await _setup_entry(hass, entry)

    manager = entry.runtime_data
    assert "bedroom" in manager.rooms

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hasattr(entry, "runtime_data")


async def test_setup_entry_minimal(hass: HomeAssistant, minimal_config: dict) -> None:
    """Test config entry setup with minimal room config."""
    validated = CONFIG_SCHEMA(minimal_config)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=validated[DOMAIN])
    await _setup_entry(hass, entry)

    manager = entry.runtime_data
    room = manager.rooms["bedroom"]
    assert room.presence_sensor_id == "binary_sensor.bedroom_presence"
    assert room.light_entities == ["light.bedroom_lamp"]
    assert not room.has_bed_sensor
    assert not room.bed_persons

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_entry_full(hass: HomeAssistant, full_config: dict) -> None:
    """Test config entry setup with full room config including bed sensors."""
    validated = CONFIG_SCHEMA(full_config)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=validated[DOMAIN])
    await _setup_entry(hass, entry)

    manager = entry.runtime_data
    room = manager.rooms["bedroom"]
    assert room.has_bed_sensor
    assert room.bed_sensor_id == "binary_sensor.bed_occupancy"
    assert room.occupant_count_id == "sensor.bed_occupants"
    assert room.bed_persons == ["person.alice", "person.bob"]
    assert room.al_switch_id == "switch.adaptive_lighting_bedroom"
    assert room.sleep_mode_id == "switch.sleep_mode_bedroom"
    assert manager.all_sleep_light_ids == ["light.living_room", "light.toilet_light"]
    assert manager.sleep_modes == ["switch.sleep_mode_living_room"]

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_entry_empty(hass: HomeAssistant) -> None:
    """Test config entry setup with no rooms."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "rooms": {},
            "sleep_lights": [],
            "sleep_modes": [],
            "illuminance_threshold": 4000,
        },
    )
    await _setup_entry(hass, entry)

    manager = entry.runtime_data
    assert len(manager.rooms) == 0

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_room_tuning_change_applies_in_place(hass: HomeAssistant, full_config: dict) -> None:
    """A tuning-only edit updates the live room without reloading the entry."""
    validated = CONFIG_SCHEMA(full_config)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=validated[DOMAIN])
    await _setup_entry(hass, entry)

    manager_before = entry.runtime_data
    room = manager_before.rooms["bedroom"]
    assert room.config["dim_brightness"] == 5

    new_options = copy.deepcopy(dict(entry.options))
    new_options["rooms"]["bedroom"]["dim_brightness"] = 42
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.async_block_till_done()

    assert entry.runtime_data is manager_before  # no reload
    assert room.config["dim_brightness"] == 42  # applied in place

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_global_tuning_change_applies_in_place(
    hass: HomeAssistant, full_config: dict
) -> None:
    """A global tuning edit updates the manager in place without reloading."""
    validated = CONFIG_SCHEMA(full_config)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=validated[DOMAIN])
    await _setup_entry(hass, entry)

    manager_before = entry.runtime_data

    new_options = copy.deepcopy(dict(entry.options))
    new_options["illuminance_threshold"] = 1234
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.async_block_till_done()

    assert entry.runtime_data is manager_before
    assert manager_before.illuminance_threshold == 1234

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_structural_change_triggers_reload(hass: HomeAssistant, full_config: dict) -> None:
    """A structural edit (changed lights) reloads the entry with a fresh manager."""
    validated = CONFIG_SCHEMA(full_config)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=validated[DOMAIN])
    await _setup_entry(hass, entry)

    manager_before = entry.runtime_data

    new_options = copy.deepcopy(dict(entry.options))
    new_options["rooms"]["bedroom"]["lights"] = ["light.new_lamp"]
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.async_block_till_done()

    manager_after = entry.runtime_data
    assert manager_after is not manager_before  # reloaded
    assert manager_after.rooms["bedroom"].light_entities == ["light.new_lamp"]

    assert await hass.config_entries.async_unload(entry.entry_id)


def test_config_schema_rejects_missing_presence() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA({DOMAIN: {"rooms": {"bedroom": {"sensors": {}, "lights": ["light.lamp"]}}}})


def test_config_schema_rejects_missing_lights() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {DOMAIN: {"rooms": {"bedroom": {"sensors": {"presence": "binary_sensor.x"}}}}}
        )


def test_config_schema_rejects_empty_lights() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {
                DOMAIN: {
                    "rooms": {
                        "bedroom": {
                            "sensors": {"presence": "binary_sensor.x"},
                            "lights": [],
                        }
                    }
                }
            }
        )


def test_config_schema_rejects_bed_without_sensors() -> None:
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {
                DOMAIN: {
                    "rooms": {
                        "bedroom": {
                            "sensors": {
                                "presence": "binary_sensor.x",
                                "bed": {"persons": ["person.alice"]},
                            },
                            "lights": ["light.lamp"],
                        }
                    }
                }
            }
        )


def test_config_schema_defaults() -> None:
    validated = CONFIG_SCHEMA(
        {
            DOMAIN: {
                "rooms": {
                    "bedroom": {
                        "sensors": {"presence": "binary_sensor.x"},
                        "lights": ["light.lamp"],
                    }
                }
            }
        }
    )
    room = validated[DOMAIN]["rooms"]["bedroom"]
    assert room["dim_brightness"] == 5
    assert room["transition_on"] == 2
    assert room["transition_off"] == 5
    assert room["bed_exit_delay"] == 10
    assert room["bed_return_timeout"] == 180
    assert room["fans"] == []
    assert room["speakers"] == []


async def test_invalid_options_fail_setup(hass: HomeAssistant) -> None:
    """Stored options that fail the schema put the entry into a setup error, not a crash."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"rooms": {"bedroom": {"sensors": {"presence": "binary_sensor.x"}, "lights": []}}},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
