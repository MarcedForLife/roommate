"""Tests for Roommate diagnostic sensor."""

from __future__ import annotations

from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.roommate.manager import RoommateManager
from custom_components.roommate.sensor import RoomDiagnosticSensor


def _make_sensor(room) -> RoomDiagnosticSensor:
    """Build a sensor without linking it to the room's diagnostic_entity.

    Linking causes async_write_ha_state calls in handlers, which requires
    full HA entity registration. For unit tests we just read properties.
    """
    sensor = RoomDiagnosticSensor.__new__(RoomDiagnosticSensor)
    sensor._room = room
    sensor._attr_unique_id = f"roommate_{room.name}_room_state"
    return sensor


async def test_sensor_vacant(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]
    sensor = _make_sensor(room)

    assert sensor.native_value == "empty"
    attrs = sensor.extra_state_attributes
    assert attrs["presence_lighting"] == "active"
    assert attrs["bed_automations"] == "enabled"
    assert attrs["bed_exit_timer"] is False
    assert attrs["presence_off_timer"] is False
    assert attrs["snapshot"] is False


async def test_sensor_present(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()

    sensor = _make_sensor(room)
    assert sensor.native_value == "present"


async def test_sensor_in_bed(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    hass.states.async_set("binary_sensor.bed_occupancy", STATE_ON)
    room.handle_presence_change()
    room.handle_bed_change("off", STATE_ON)

    sensor = _make_sensor(room)
    assert sensor.native_value == "in_bed"


async def test_sensor_override(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    room = setup_integration.rooms["bedroom"]

    hass.states.async_set("binary_sensor.bedroom_presence", STATE_ON)
    room.handle_presence_change()
    room.handle_light_change(STATE_ON, "off", None)

    sensor = _make_sensor(room)
    assert sensor.extra_state_attributes["presence_lighting"] == "overridden"


async def test_sensor_bed_attributes_only_with_bed_sensor(
    hass: HomeAssistant,
    setup_integration: RoommateManager,
) -> None:
    """Bed-specific attributes are only present for rooms with bed sensors."""
    room = setup_integration.rooms["bedroom"]
    sensor = _make_sensor(room)

    attrs = sensor.extra_state_attributes
    assert "bed_automations" in attrs
    assert "occupant_count" in attrs
    assert "bed_exit_timer" in attrs
    assert "snapshot" in attrs
