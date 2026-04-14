"""Tests for Roommate config flow and options flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roommate.const import (
    CONF_ENTITY_ID,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_INHIBIT,
    CONF_ROOMS,
    CONF_SLEEP_LIGHT_TRANSITION,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_MODES,
    DEFAULT_ILLUMINANCE_THRESHOLD,
    DEFAULT_SLEEP_LIGHT_TRANSITION,
    DOMAIN,
    TUNING_PARAMS,
)


async def test_user_flow_shows_menu(hass: HomeAssistant) -> None:
    """Test the initial user config flow shows a setup menu."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert "add_room" in result["menu_options"]
    assert "global_settings" in result["menu_options"]
    assert "finish_setup" in result["menu_options"]


async def test_user_flow_finish_empty(hass: HomeAssistant) -> None:
    """Test finishing setup without adding rooms creates an empty entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_setup"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Roommate"
    assert result["options"][CONF_ROOMS] == {}


async def test_user_flow_add_room(hass: HomeAssistant) -> None:
    """Test adding a room during initial setup returns to the menu."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_room"}
    )
    assert result["step_id"] == "add_room"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Living Room"}
    )
    assert result["step_id"] == "room_sensors"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"presence": "binary_sensor.motion"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"lights": ["light.lamp"]}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _tuning_defaults()
    )

    # Returns to the setup menu after adding the room
    assert result["type"] is FlowResultType.MENU

    # Finish to create the entry
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_setup"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    rooms = result["options"][CONF_ROOMS]
    assert "living_room" in rooms
    assert rooms["living_room"]["sensors"]["presence"] == "binary_sensor.motion"


async def test_user_flow_global_settings(hass: HomeAssistant) -> None:
    """Test configuring global settings during initial setup."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "global_settings"}
    )
    assert result["step_id"] == "global_settings"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "sleep_lights": ["light.hallway"],
            CONF_ILLUMINANCE_THRESHOLD: 3000,
            CONF_SLEEP_LIGHT_TRANSITION: 10,
        },
    )
    # Returns to the setup menu
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish_setup"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ILLUMINANCE_THRESHOLD] == 3000.0
    assert result["options"][CONF_SLEEP_LIGHT_TRANSITION] == 10
    assert result["options"][CONF_SLEEP_LIGHTS][0][CONF_ENTITY_ID] == "light.hallway"


async def test_user_flow_single_instance(hass: HomeAssistant) -> None:
    """Test only one Roommate instance is allowed."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_ROOMS: {}})
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_import_flow(hass: HomeAssistant) -> None:
    """Test YAML import creates an entry with the imported config."""
    import_data = {
        CONF_ROOMS: {
            "bedroom": {
                "sensors": {"presence": "binary_sensor.x"},
                "lights": ["light.lamp"],
            }
        },
        CONF_SLEEP_LIGHTS: [],
        CONF_SLEEP_MODES: [],
        CONF_ILLUMINANCE_THRESHOLD: 4000,
    }

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=import_data
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ROOMS]["bedroom"]["sensors"]["presence"] == "binary_sensor.x"


async def test_import_flow_single_instance(hass: HomeAssistant) -> None:
    """Test import is skipped when an entry already exists."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_ROOMS: {}})
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data={}
    )
    assert result["type"] is FlowResultType.ABORT


def _empty_options() -> dict:
    return {
        CONF_ROOMS: {},
        CONF_SLEEP_LIGHTS: [],
        CONF_SLEEP_MODES: [],
        CONF_ILLUMINANCE_THRESHOLD: DEFAULT_ILLUMINANCE_THRESHOLD,
        CONF_SLEEP_LIGHT_TRANSITION: DEFAULT_SLEEP_LIGHT_TRANSITION,
    }


def _tuning_defaults() -> dict:
    return {key: default for key, (default, _, _, _) in TUNING_PARAMS.items()}


async def _start_options_flow(hass, entry):
    """Initialize and return the first (menu) step of the options flow."""
    return await hass.config_entries.options.async_init(entry.entry_id)


async def test_options_add_room(hass: HomeAssistant) -> None:
    """Test the full add-room flow through all steps."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=_empty_options())
    entry.add_to_hass(hass)

    # Menu
    result = await _start_options_flow(hass, entry)
    assert result["type"] is FlowResultType.MENU
    assert "add_room" in result["menu_options"]
    assert "edit_room" not in result["menu_options"]

    # Add room: name
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_room"}
    )
    assert result["step_id"] == "add_room"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Master Bedroom"}
    )
    assert result["step_id"] == "room_sensors"

    # Sensors
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"presence": "binary_sensor.bedroom_motion"},
    )
    assert result["step_id"] == "room_lights"

    # Lights
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"lights": ["light.bedroom"]},
    )
    assert result["step_id"] == "room_devices"

    # Devices (skip all optional)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "room_tuning"

    # Tuning (use defaults)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _tuning_defaults()
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    rooms = result["data"][CONF_ROOMS]
    assert "master_bedroom" in rooms
    room = rooms["master_bedroom"]
    assert room["sensors"]["presence"] == "binary_sensor.bedroom_motion"
    assert room["lights"] == ["light.bedroom"]


async def test_options_add_room_with_bed(hass: HomeAssistant) -> None:
    """Test adding a room with bed sensor configuration."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=_empty_options())
    entry.add_to_hass(hass)

    result = await _start_options_flow(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "bedroom"}
    )

    # Sensors with bed config
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "presence": "binary_sensor.motion",
            "bed_presence": "binary_sensor.bed",
            "bed_occupants": "sensor.occupants",
            "bed_persons": ["person.alice"],
        },
    )
    assert result["step_id"] == "room_lights"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"lights": ["light.lamp"]}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _tuning_defaults()
    )

    room = result["data"][CONF_ROOMS]["bedroom"]
    assert room["sensors"]["bed"]["presence"] == "binary_sensor.bed"
    assert room["sensors"]["bed"]["occupants"] == "sensor.occupants"
    assert room["sensors"]["bed"]["persons"] == ["person.alice"]


async def test_options_add_room_bed_requires_sensor(hass: HomeAssistant) -> None:
    """Test validation: bed persons without a bed sensor shows an error."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=_empty_options())
    entry.add_to_hass(hass)

    result = await _start_options_flow(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "bedroom"}
    )

    # Provide persons but no bed sensor
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "presence": "binary_sensor.motion",
            "bed_persons": ["person.alice"],
        },
    )
    assert result["step_id"] == "room_sensors"
    assert result["errors"]["bed_presence"] == "bed_requires_sensor"


async def test_options_add_room_duplicate_name(hass: HomeAssistant) -> None:
    """Test validation: duplicate room name shows an error."""
    options = _empty_options()
    options[CONF_ROOMS]["bedroom"] = {
        "sensors": {"presence": "binary_sensor.x"},
        "lights": ["light.x"],
    }
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)

    result = await _start_options_flow(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "bedroom"}
    )
    assert result["step_id"] == "add_room"
    assert result["errors"]["name"] == "room_exists"


async def test_options_edit_room(hass: HomeAssistant) -> None:
    """Test editing an existing room updates its config."""
    options = _empty_options()
    options[CONF_ROOMS]["bedroom"] = {
        "sensors": {"presence": "binary_sensor.old_motion"},
        "lights": ["light.old_lamp"],
        "fans": [],
        "speakers": [],
        **_tuning_defaults(),
    }
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)

    result = await _start_options_flow(hass, entry)
    assert "edit_room" in result["menu_options"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"room": "bedroom"}
    )
    assert result["step_id"] == "room_sensors"

    # Change the presence sensor
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"presence": "binary_sensor.new_motion"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"lights": ["light.new_lamp"]}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _tuning_defaults()
    )

    room = result["data"][CONF_ROOMS]["bedroom"]
    assert room["sensors"]["presence"] == "binary_sensor.new_motion"
    assert room["lights"] == ["light.new_lamp"]


async def test_options_remove_room(hass: HomeAssistant) -> None:
    """Test removing a room."""
    options = _empty_options()
    options[CONF_ROOMS]["bedroom"] = {
        "sensors": {"presence": "binary_sensor.x"},
        "lights": ["light.x"],
    }
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)

    result = await _start_options_flow(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_room"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"room": "bedroom"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "bedroom" not in result["data"][CONF_ROOMS]


async def test_options_global_settings(hass: HomeAssistant) -> None:
    """Test configuring global settings."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=_empty_options())
    entry.add_to_hass(hass)

    result = await _start_options_flow(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "global_settings"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sleep_lights": ["light.living_room", "light.hallway"],
            "sleep_modes": ["switch.sleep_mode"],
            "illuminance_sensor": "sensor.outdoor_lux",
            CONF_ILLUMINANCE_THRESHOLD: 5000,
            CONF_SLEEP_LIGHT_TRANSITION: 3,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    data = result["data"]
    assert len(data[CONF_SLEEP_LIGHTS]) == 2
    assert data[CONF_SLEEP_LIGHTS][0][CONF_ENTITY_ID] == "light.living_room"
    assert data[CONF_SLEEP_LIGHTS][0][CONF_INHIBIT] == []
    assert data[CONF_SLEEP_MODES] == ["switch.sleep_mode"]
    assert data["illuminance_sensor"] == "sensor.outdoor_lux"
    assert data[CONF_ILLUMINANCE_THRESHOLD] == 5000.0
    assert data[CONF_SLEEP_LIGHT_TRANSITION] == 3


async def test_options_global_preserves_inhibit(hass: HomeAssistant) -> None:
    """Test that editing global settings preserves per-light inhibit config."""
    options = _empty_options()
    options[CONF_SLEEP_LIGHTS] = [
        {CONF_ENTITY_ID: "light.living_room", CONF_INHIBIT: ["switch.theatre"]},
        {CONF_ENTITY_ID: "light.hallway", CONF_INHIBIT: []},
    ]
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)

    result = await _start_options_flow(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "global_settings"}
    )

    # Re-submit with the same lights
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sleep_lights": ["light.living_room", "light.hallway"],
            CONF_ILLUMINANCE_THRESHOLD: DEFAULT_ILLUMINANCE_THRESHOLD,
            CONF_SLEEP_LIGHT_TRANSITION: DEFAULT_SLEEP_LIGHT_TRANSITION,
        },
    )

    lights = result["data"][CONF_SLEEP_LIGHTS]
    assert lights[0][CONF_INHIBIT] == ["switch.theatre"]
    assert lights[1][CONF_INHIBIT] == []
