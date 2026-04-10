"""Config flow for Roommate integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    NumberSelector,
    SelectSelector,
    TextSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_ADAPTIVE_LIGHTING,
    CONF_BED,
    CONF_ENTITY_ID,
    CONF_FANS,
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
    CONF_WAKE_TRANSITION,
    DEFAULT_ILLUMINANCE_THRESHOLD,
    DEFAULT_SLEEP_LIGHT_TRANSITION,
    DOMAIN,
    TUNING_PARAMS,
    WAKE_TRANSITION_RANGE,
)


class RoommateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle initial Roommate setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Confirm integration setup."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title="Roommate",
                data={},
                options={
                    CONF_ROOMS: {},
                    CONF_SLEEP_LIGHTS: [],
                    CONF_SLEEP_MODES: [],
                    CONF_ILLUMINANCE_THRESHOLD: DEFAULT_ILLUMINANCE_THRESHOLD,
                    CONF_SLEEP_LIGHT_TRANSITION: DEFAULT_SLEEP_LIGHT_TRANSITION,
                },
            )

        return self.async_show_form(step_id="user")

    async def async_step_import(self, import_data: dict[str, Any]):
        """Import configuration from YAML."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(
            title="Roommate",
            data={},
            options=import_data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> RoommateOptionsFlow:
        return RoommateOptionsFlow()


class RoommateOptionsFlow(OptionsFlow):
    """Manage rooms and global settings."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._room_data: dict[str, Any] = {}
        self._room_name: str = ""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show the main configuration menu."""
        self._options = dict(self.config_entry.options)
        rooms = self._options.get(CONF_ROOMS, {})

        menu = ["add_room"]
        if rooms:
            menu.extend(["edit_room", "remove_room"])
        menu.append("global_settings")

        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None):
        """Prompt for the new room's name."""
        errors: dict[str, str] = {}

        if user_input is not None:
            slug = slugify(user_input["name"])
            if not slug:
                errors["name"] = "invalid_name"
            elif slug in self._options.get(CONF_ROOMS, {}):
                errors["name"] = "room_exists"
            else:
                self._room_name = slug
                self._room_data = {}
                return await self.async_step_room_sensors()

        return self.async_show_form(
            step_id="add_room",
            data_schema=vol.Schema({vol.Required("name"): TextSelector()}),
            errors=errors,
        )

    async def async_step_edit_room(self, user_input: dict[str, Any] | None = None):
        """Select a room to edit."""
        rooms = self._options.get(CONF_ROOMS, {})

        if user_input is not None:
            name = user_input["room"]
            self._room_name = name
            self._room_data = dict(rooms[name])
            return await self.async_step_room_sensors()

        return self.async_show_form(
            step_id="edit_room",
            data_schema=vol.Schema(
                {vol.Required("room"): _room_selector(rooms)}
            ),
        )

    async def async_step_remove_room(self, user_input: dict[str, Any] | None = None):
        """Select and remove a room."""
        rooms = self._options.get(CONF_ROOMS, {})

        if user_input is not None:
            rooms_copy = dict(rooms)
            del rooms_copy[user_input["room"]]
            self._options[CONF_ROOMS] = rooms_copy
            return self.async_create_entry(data=self._options)

        return self.async_show_form(
            step_id="remove_room",
            data_schema=vol.Schema(
                {vol.Required("room"): _room_selector(rooms)}
            ),
        )

    def _placeholders(self) -> dict[str, str]:
        return {"room_name": self._room_name.replace("_", " ").title()}

    async def async_step_room_sensors(self, user_input: dict[str, Any] | None = None):
        """Configure room sensors."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sensors: dict[str, Any] = {CONF_PRESENCE: user_input["presence"]}

            bed_presence = user_input.get("bed_presence")
            bed_occupants = user_input.get("bed_occupants")
            bed_persons = user_input.get("bed_persons", [])

            has_bed_fields = bed_presence or bed_occupants or bed_persons
            if has_bed_fields and not bed_presence and not bed_occupants:
                errors["bed_presence"] = "bed_requires_sensor"
            else:
                if bed_presence or bed_occupants:
                    bed: dict[str, Any] = {}
                    if bed_presence:
                        bed[CONF_PRESENCE] = bed_presence
                    if bed_occupants:
                        bed[CONF_OCCUPANTS] = bed_occupants
                    bed[CONF_PERSONS] = bed_persons
                    sensors[CONF_BED] = bed

                self._room_data[CONF_SENSORS] = sensors
                return await self.async_step_room_lights()

        existing = self._room_data.get(CONF_SENSORS, {})
        existing_bed = existing.get(CONF_BED, {})
        suggested = {
            "presence": existing.get(CONF_PRESENCE),
            "bed_presence": existing_bed.get(CONF_PRESENCE),
            "bed_occupants": existing_bed.get(CONF_OCCUPANTS),
            "bed_persons": existing_bed.get(CONF_PERSONS),
        }

        schema = vol.Schema(
            {
                vol.Required("presence"): EntitySelector({"domain": "binary_sensor"}),
                vol.Optional("bed_presence"): EntitySelector({"domain": "binary_sensor"}),
                vol.Optional("bed_occupants"): EntitySelector({"domain": "sensor"}),
                vol.Optional("bed_persons"): EntitySelector(
                    {"domain": "person", "multiple": True}
                ),
            }
        )

        return self.async_show_form(
            step_id="room_sensors",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_room_lights(self, user_input: dict[str, Any] | None = None):
        """Configure room lights."""
        if user_input is not None:
            self._room_data[CONF_LIGHTS] = user_input["lights"]
            return await self.async_step_room_devices()

        suggested = {"lights": self._room_data.get(CONF_LIGHTS)}
        schema = vol.Schema(
            {
                vol.Required("lights"): EntitySelector(
                    {"domain": "light", "multiple": True}
                ),
            }
        )

        return self.async_show_form(
            step_id="room_lights",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            description_placeholders=self._placeholders(),
        )

    async def async_step_room_devices(self, user_input: dict[str, Any] | None = None):
        """Configure fans, speakers, adaptive lighting, and wake transition."""
        if user_input is not None:
            self._room_data[CONF_FANS] = user_input.get("fans", [])
            self._room_data[CONF_SPEAKERS] = user_input.get("speakers", [])

            al_switch = user_input.get("al_switch")
            if al_switch:
                al_config: dict[str, str] = {CONF_SWITCH: al_switch}
                al_sleep = user_input.get("al_sleep_mode")
                if al_sleep:
                    al_config[CONF_SLEEP_MODE] = al_sleep
                self._room_data[CONF_ADAPTIVE_LIGHTING] = al_config
            else:
                self._room_data.pop(CONF_ADAPTIVE_LIGHTING, None)

            wake = user_input.get("wake_transition")
            if wake is not None:
                self._room_data[CONF_WAKE_TRANSITION] = int(wake)
            else:
                self._room_data.pop(CONF_WAKE_TRANSITION, None)

            return await self.async_step_room_tuning()

        al_existing = self._room_data.get(CONF_ADAPTIVE_LIGHTING, {})
        wake_low, wake_high, wake_unit = WAKE_TRANSITION_RANGE
        suggested = {
            "fans": self._room_data.get(CONF_FANS) or None,
            "speakers": self._room_data.get(CONF_SPEAKERS) or None,
            "al_switch": al_existing.get(CONF_SWITCH),
            "al_sleep_mode": al_existing.get(CONF_SLEEP_MODE),
            "wake_transition": self._room_data.get(CONF_WAKE_TRANSITION),
        }

        schema = vol.Schema(
            {
                vol.Optional("fans"): EntitySelector(
                    {"domain": "fan", "multiple": True}
                ),
                vol.Optional("speakers"): EntitySelector(
                    {"domain": "media_player", "multiple": True}
                ),
                vol.Optional("al_switch"): EntitySelector({"domain": "switch"}),
                vol.Optional("al_sleep_mode"): EntitySelector({"domain": "switch"}),
                vol.Optional("wake_transition"): NumberSelector(
                    {
                        "min": wake_low,
                        "max": wake_high,
                        "step": 1,
                        "unit_of_measurement": wake_unit,
                        "mode": "box",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="room_devices",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            description_placeholders=self._placeholders(),
        )

    async def async_step_room_tuning(self, user_input: dict[str, Any] | None = None):
        """Configure timing and brightness parameters."""
        if user_input is not None:
            for key in TUNING_PARAMS:
                self._room_data[key] = int(user_input[key])

            rooms = dict(self._options.get(CONF_ROOMS, {}))
            rooms[self._room_name] = self._room_data
            self._options[CONF_ROOMS] = rooms
            return self.async_create_entry(data=self._options)

        suggested = {
            key: self._room_data.get(key, default)
            for key, (default, _low, _high, _unit) in TUNING_PARAMS.items()
        }

        return self.async_show_form(
            step_id="room_tuning",
            data_schema=self.add_suggested_values_to_schema(
                _tuning_schema(), suggested
            ),
            description_placeholders=self._placeholders(),
        )

    async def async_step_global_settings(self, user_input: dict[str, Any] | None = None):
        """Configure global sleep and illuminance settings."""
        if user_input is not None:
            # Preserve per-light inhibit config for existing sleep lights
            new_ids = user_input.get("sleep_lights", [])
            existing_map = {
                sl[CONF_ENTITY_ID]: sl
                for sl in self._options.get(CONF_SLEEP_LIGHTS, [])
            }
            self._options[CONF_SLEEP_LIGHTS] = [
                existing_map.get(lid, {CONF_ENTITY_ID: lid, CONF_INHIBIT: []})
                for lid in new_ids
            ]

            self._options[CONF_SLEEP_MODES] = user_input.get("sleep_modes", [])

            illuminance = user_input.get("illuminance_sensor")
            if illuminance:
                self._options[CONF_ILLUMINANCE_SENSOR] = illuminance
            else:
                self._options.pop(CONF_ILLUMINANCE_SENSOR, None)

            self._options[CONF_ILLUMINANCE_THRESHOLD] = float(
                user_input.get(
                    CONF_ILLUMINANCE_THRESHOLD, DEFAULT_ILLUMINANCE_THRESHOLD
                )
            )
            self._options[CONF_SLEEP_LIGHT_TRANSITION] = int(
                user_input.get(
                    CONF_SLEEP_LIGHT_TRANSITION, DEFAULT_SLEEP_LIGHT_TRANSITION
                )
            )

            return self.async_create_entry(data=self._options)

        current_light_ids = [
            sl[CONF_ENTITY_ID]
            for sl in self._options.get(CONF_SLEEP_LIGHTS, [])
        ]
        suggested = {
            "sleep_lights": current_light_ids or None,
            "sleep_modes": self._options.get(CONF_SLEEP_MODES) or None,
            "illuminance_sensor": self._options.get(CONF_ILLUMINANCE_SENSOR),
            CONF_ILLUMINANCE_THRESHOLD: self._options.get(
                CONF_ILLUMINANCE_THRESHOLD, DEFAULT_ILLUMINANCE_THRESHOLD
            ),
            CONF_SLEEP_LIGHT_TRANSITION: self._options.get(
                CONF_SLEEP_LIGHT_TRANSITION, DEFAULT_SLEEP_LIGHT_TRANSITION
            ),
        }

        schema = vol.Schema(
            {
                vol.Optional("sleep_lights"): EntitySelector(
                    {"domain": "light", "multiple": True}
                ),
                vol.Optional("sleep_modes"): EntitySelector(
                    {"domain": "switch", "multiple": True}
                ),
                vol.Optional("illuminance_sensor"): EntitySelector(
                    {"domain": "sensor"}
                ),
                vol.Required(CONF_ILLUMINANCE_THRESHOLD): NumberSelector(
                    {
                        "min": 0,
                        "max": 100000,
                        "step": 100,
                        "unit_of_measurement": "lx",
                        "mode": "box",
                    }
                ),
                vol.Required(CONF_SLEEP_LIGHT_TRANSITION): NumberSelector(
                    {
                        "min": 0,
                        "max": 30,
                        "step": 1,
                        "unit_of_measurement": "s",
                        "mode": "box",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="global_settings",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )


def _room_selector(rooms: dict) -> SelectSelector:
    """Build a dropdown selector from the current room names."""
    return SelectSelector(
        {
            "options": [
                {"value": name, "label": name.replace("_", " ").title()}
                for name in sorted(rooms)
            ],
            "mode": "dropdown",
        }
    )


def _tuning_schema() -> vol.Schema:
    """Build the tuning parameter schema from the central TUNING_PARAMS table."""
    fields: dict = {}
    for key, (_default, low, high, unit) in TUNING_PARAMS.items():
        fields[vol.Required(key)] = NumberSelector(
            {
                "min": low,
                "max": high,
                "step": 1,
                "unit_of_measurement": unit,
                "mode": "box",
            }
        )
    return vol.Schema(fields)
