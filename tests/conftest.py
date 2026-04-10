"""Fixtures for Roommate tests."""

from __future__ import annotations

import copy

import pytest
from homeassistant.core import HomeAssistant

from custom_components.roommate import CONFIG_SCHEMA
from custom_components.roommate.const import DOMAIN
from custom_components.roommate.manager import RoommateManager


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom component discoverable by HA's loader."""
    yield

MINIMAL_ROOM_CONFIG = {
    DOMAIN: {
        "rooms": {
            "bedroom": {
                "sensors": {
                    "presence": "binary_sensor.bedroom_presence",
                },
                "lights": ["light.bedroom_lamp"],
            },
        },
    },
}

FULL_ROOM_CONFIG = {
    DOMAIN: {
        "illuminance_sensor": "sensor.illuminance",
        "illuminance_threshold": 4000,
        "sleep_lights": [
            {"entity_id": "light.living_room", "inhibit": ["switch.theatre_lighting"]},
            "light.toilet_light",
        ],
        "sleep_modes": ["switch.sleep_mode_living_room"],
        "rooms": {
            "bedroom": {
                "sensors": {
                    "presence": "binary_sensor.bedroom_presence",
                    "bed": {
                        "presence": "binary_sensor.bed_occupancy",
                        "occupants": "sensor.bed_occupants",
                        "persons": ["person.alice", "person.bob"],
                    },
                },
                "lights": ["light.lamp_1", "light.lamp_2"],
                "fans": ["fan.bedroom_fan"],
                "speakers": ["media_player.bedroom_speaker"],
                "adaptive_lighting": {
                    "switch": "switch.adaptive_lighting_bedroom",
                    "sleep_mode": "switch.sleep_mode_bedroom",
                },
                "wake_transition": 30,
                "dim_brightness": 5,
            },
        },
    },
}


@pytest.fixture
def minimal_config():
    return copy.deepcopy(MINIMAL_ROOM_CONFIG)


@pytest.fixture
def full_config():
    return copy.deepcopy(FULL_ROOM_CONFIG)


@pytest.fixture
async def setup_integration(hass: HomeAssistant, full_config: dict):
    """Create manager directly from validated config (for unit tests)."""
    validated = CONFIG_SCHEMA(full_config)
    manager = RoommateManager(hass, validated[DOMAIN])
    await manager.async_setup()
    yield manager
    manager.shutdown()
