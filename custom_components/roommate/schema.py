"""YAML validation schemas for Roommate configuration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ADAPTIVE_LIGHTING,
    CONF_BED,
    CONF_ENTITY_ID,
    CONF_FANS,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_ILLUMINANCE_SENSOR,
    CONF_ILLUMINANCE_THRESHOLD,
    CONF_INHIBIT,
    CONF_LIGHTS,
    CONF_OCCUPANTS,
    CONF_PERSONS,
    CONF_PRESENCE,
    CONF_ROOMS,
    CONF_SENSORS,
    CONF_SLEEP_LIGHT_TRANSITION,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_MODE,
    CONF_SLEEP_MODES,
    CONF_SPEAKERS,
    CONF_SWITCH,
    CONF_TEMPERATURE,
    CONF_WAKE_TRANSITION,
    DEFAULT_ILLUMINANCE_THRESHOLD,
    DEFAULT_SLEEP_LIGHT_TRANSITION,
    DOMAIN,
    TUNING_PARAMS,
    WAKE_TRANSITION_RANGE,
)


def _validate_bed_sensors(config: dict) -> dict:
    """Ensure at least one of presence or occupants is configured."""
    if CONF_PRESENCE not in config and CONF_OCCUPANTS not in config:
        raise vol.Invalid("bed config requires at least 'presence' or 'occupants'")
    return config


SLEEP_LIGHT_SCHEMA = vol.Any(
    cv.entity_id,
    vol.Schema(
        {
            vol.Required(CONF_ENTITY_ID): cv.entity_id,
            vol.Optional(CONF_INHIBIT, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        }
    ),
)


def _normalize_sleep_lights(config: list) -> list[dict]:
    """Normalize sleep lights to list of dicts."""
    return [
        {CONF_ENTITY_ID: item, CONF_INHIBIT: []} if isinstance(item, str) else item
        for item in config
    ]


BED_SENSORS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(CONF_PRESENCE): cv.entity_id,
            vol.Optional(CONF_OCCUPANTS): cv.entity_id,
            vol.Optional(CONF_PERSONS, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        }
    ),
    _validate_bed_sensors,
)

SENSORS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PRESENCE): cv.entity_id,
        vol.Optional(CONF_BED): BED_SENSORS_SCHEMA,
        vol.Optional(CONF_ILLUMINANCE): cv.entity_id,
        vol.Optional(CONF_TEMPERATURE): cv.entity_id,
        vol.Optional(CONF_HUMIDITY): cv.entity_id,
    }
)

ADAPTIVE_LIGHTING_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SWITCH): cv.entity_id,
        vol.Optional(CONF_SLEEP_MODE): cv.entity_id,
    }
)


def _build_tuning_fields() -> dict:
    """Generate voluptuous fields for room tuning parameters from TUNING_PARAMS."""
    fields: dict = {}
    for key, (default, low, high, _unit) in TUNING_PARAMS.items():
        fields[vol.Optional(key, default=default)] = vol.All(
            vol.Coerce(int), vol.Range(min=low, max=high)
        )
    return fields


ROOM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SENSORS): SENSORS_SCHEMA,
        vol.Required(CONF_LIGHTS): vol.All(cv.ensure_list, [cv.entity_id], vol.Length(min=1)),
        vol.Optional(CONF_FANS, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_SPEAKERS, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_ADAPTIVE_LIGHTING): ADAPTIVE_LIGHTING_SCHEMA,
        vol.Optional(CONF_WAKE_TRANSITION): vol.All(
            vol.Coerce(int),
            vol.Range(min=WAKE_TRANSITION_RANGE[0], max=WAKE_TRANSITION_RANGE[1]),
        ),
        **_build_tuning_fields(),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {
                vol.Required(CONF_ROOMS): vol.Schema({cv.slug: ROOM_SCHEMA}),
                vol.Optional(CONF_SLEEP_LIGHTS, default=[]): vol.All(
                    cv.ensure_list, [SLEEP_LIGHT_SCHEMA], _normalize_sleep_lights
                ),
                vol.Optional(CONF_SLEEP_MODES, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
                vol.Optional(CONF_ILLUMINANCE_SENSOR): cv.entity_id,
                vol.Optional(
                    CONF_ILLUMINANCE_THRESHOLD,
                    default=DEFAULT_ILLUMINANCE_THRESHOLD,
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Optional(
                    CONF_SLEEP_LIGHT_TRANSITION,
                    default=DEFAULT_SLEEP_LIGHT_TRANSITION,
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)
