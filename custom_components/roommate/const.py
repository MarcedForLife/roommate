"""Constants for Roommate integration."""

from __future__ import annotations

DOMAIN = "roommate"

# Top-level config keys
CONF_ROOMS = "rooms"
CONF_SLEEP_LIGHTS = "sleep_lights"
CONF_SLEEP_MODES = "sleep_modes"

# Room config keys
CONF_SENSORS = "sensors"
CONF_LIGHTS = "lights"
CONF_FANS = "fans"
CONF_SPEAKERS = "speakers"
CONF_ADAPTIVE_LIGHTING = "adaptive_lighting"
CONF_WAKE_TRANSITION = "wake_transition"
CONF_DIM_BRIGHTNESS = "dim_brightness"
CONF_RECENTLY_ON_THRESHOLD = "recently_on_threshold"
CONF_TRANSITION_ON = "transition_on"
CONF_TRANSITION_OFF = "transition_off"
CONF_TRANSITION_DIM = "transition_dim"
CONF_BED_EXIT_DELAY = "bed_exit_delay"
CONF_BED_RETURN_TIMEOUT = "bed_return_timeout"
CONF_PRESENCE_OFF_DELAY = "presence_off_delay"

# Sensor config keys
CONF_PRESENCE = "presence"
CONF_BED = "bed"
CONF_OCCUPANTS = "occupants"
CONF_PERSONS = "persons"
CONF_ILLUMINANCE = "illuminance"
CONF_TEMPERATURE = "temperature"
CONF_HUMIDITY = "humidity"

# Adaptive lighting config keys
CONF_SWITCH = "switch"
CONF_SLEEP_MODE = "sleep_mode"

# Global config keys
CONF_ILLUMINANCE_SENSOR = "illuminance_sensor"
CONF_ILLUMINANCE_THRESHOLD = "illuminance_threshold"
CONF_ENTITY_ID = "entity_id"
CONF_INHIBIT = "inhibit"
CONF_SLEEP_LIGHT_TRANSITION = "sleep_light_transition"

# Global defaults
DEFAULT_ILLUMINANCE_THRESHOLD = 4000
DEFAULT_SLEEP_LIGHT_TRANSITION = 5

# Room tuning parameters, keyed by config name: (default, min, max, unit).
# Used by the YAML schema, config flow selectors, and _apply_defaults.
TUNING_PARAMS: dict[str, tuple[int, int, int, str]] = {
    CONF_DIM_BRIGHTNESS: (5, 1, 100, "%"),
    CONF_RECENTLY_ON_THRESHOLD: (8, 0, 60, "s"),
    CONF_TRANSITION_ON: (2, 0, 30, "s"),
    CONF_TRANSITION_OFF: (5, 0, 30, "s"),
    CONF_TRANSITION_DIM: (5, 0, 30, "s"),
    CONF_BED_EXIT_DELAY: (10, 0, 120, "s"),
    CONF_BED_RETURN_TIMEOUT: (180, 0, 600, "s"),
    CONF_PRESENCE_OFF_DELAY: (0, 0, 120, "s"),
}

# Wake transition range (optional, no default)
WAKE_TRANSITION_RANGE = (0, 300, "s")
