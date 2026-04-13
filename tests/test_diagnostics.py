"""Tests for Roommate diagnostics."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roommate import CONFIG_SCHEMA
from custom_components.roommate.const import DOMAIN
from custom_components.roommate.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics(hass: HomeAssistant, full_config: dict) -> None:
    """Test diagnostics returns expected structure."""
    validated = CONFIG_SCHEMA(full_config)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=validated[DOMAIN])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert "config" in diag
    assert "guest_mode" in diag
    assert diag["guest_mode"] is False

    assert "bedroom" in diag["rooms"]
    room = diag["rooms"]["bedroom"]
    assert room["is_present"] is False
    assert room["is_in_bed"] is False
    assert room["presence_lighting_enabled"] is True
    assert room["bed_automations_enabled"] is True
    assert room["has_bed_sensor"] is True
    assert room["bed_exit_timer_active"] is False
    assert room["snapshot_active"] is False

    assert "entity_map" in diag
    assert "binary_sensor.bedroom_presence" in diag["entity_map"]
    bindings = diag["entity_map"]["binary_sensor.bedroom_presence"]
    assert bindings[0]["room"] == "bedroom"
    assert bindings[0]["role"] == "presence"

    assert await hass.config_entries.async_unload(entry.entry_id)
