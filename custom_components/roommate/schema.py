"""Validation schemas for Roommate configuration, shared by YAML import and config entries."""

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
    DOMAIN,
    GLOBAL_TUNING_PARAMS,
    TUNING_PARAMS,
    TuningParam,
)


def _validate_bed_sensors(config: dict) -> dict:
    """Ensure at least one of presence or occupants is configured."""
    if CONF_PRESENCE not in config and CONF_OCCUPANTS not in config:
        raise vol.Invalid("bed config requires at least 'presence' or 'occupants'")
    return config


def _normalize_sleep_lights(config: list) -> list[dict]:
    """Normalize sleep lights to list of dicts."""
    return [
        {CONF_ENTITY_ID: item, CONF_INHIBIT: []} if isinstance(item, str) else item
        for item in config
    ]


def _bounded_int(param: TuningParam) -> vol.All:
    return vol.All(vol.Coerce(int), vol.Range(min=param.minimum, max=param.maximum))


SLEEP_LIGHT_SCHEMA = vol.Any(
    cv.entity_id,
    vol.Schema(
        {
            vol.Required(CONF_ENTITY_ID): cv.entity_id,
            vol.Optional(CONF_INHIBIT, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        }
    ),
)

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

ROOM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SENSORS): SENSORS_SCHEMA,
        vol.Required(CONF_LIGHTS): vol.All(cv.ensure_list, [cv.entity_id], vol.Length(min=1)),
        vol.Optional(CONF_FANS, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_SPEAKERS, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_ADAPTIVE_LIGHTING): ADAPTIVE_LIGHTING_SCHEMA,
        **{
            vol.Optional(key, default=param.default): _bounded_int(param)
            for key, param in TUNING_PARAMS.items()
        },
    }
)

_ILLUMINANCE_THRESHOLD = GLOBAL_TUNING_PARAMS[CONF_ILLUMINANCE_THRESHOLD]
_SLEEP_LIGHT_TRANSITION = GLOBAL_TUNING_PARAMS[CONF_SLEEP_LIGHT_TRANSITION]

# The stored config entry options, and the body of the YAML "roommate:" block.
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ROOMS): vol.Schema({cv.slug: ROOM_SCHEMA}),
        vol.Optional(CONF_SLEEP_LIGHTS, default=[]): vol.All(
            cv.ensure_list, [SLEEP_LIGHT_SCHEMA], _normalize_sleep_lights
        ),
        vol.Optional(CONF_SLEEP_MODES, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_ILLUMINANCE_SENSOR): cv.entity_id,
        vol.Optional(CONF_ILLUMINANCE_THRESHOLD, default=_ILLUMINANCE_THRESHOLD.default): vol.All(
            vol.Coerce(float), vol.Range(min=_ILLUMINANCE_THRESHOLD.minimum)
        ),
        vol.Optional(
            CONF_SLEEP_LIGHT_TRANSITION, default=_SLEEP_LIGHT_TRANSITION.default
        ): _bounded_int(_SLEEP_LIGHT_TRANSITION),
    }
)

CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): OPTIONS_SCHEMA}, extra=vol.ALLOW_EXTRA)
