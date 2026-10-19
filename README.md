<img src="custom_components/roommate/brand/icon.png"
     alt="Roommate icon" height="55" align="right" />

# Roommate

[![GitHub Release](https://img.shields.io/github/v/release/MarcedForLife/roommate.svg?style=flat-square)](https://github.com/MarcedForLife/roommate/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/MarcedForLife/roommate.svg?style=flat-square)](LICENSE.md)

Roommate is a Home Assistant integration for presence lighting and bedtime routines. Start with a presence sensor and a light. Add bed sensors to dim the lights when you get into bed, fade them on when you get up, and coordinate sleep mode across rooms.

It supports manual lighting overrides, illuminance thresholds, Adaptive Lighting, and room resets after a period of vacancy. You can adjust brightness and timing from the room's device page.

## Install

Requires Home Assistant 2025.12 or later.

[![Open Roommate in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MarcedForLife&repository=roommate&category=Integration)

Install through HACS using the link above, or add `https://github.com/MarcedForLife/roommate` as a custom repository with the Integration category. Download Roommate and restart Home Assistant.

For a manual install, copy `custom_components/roommate` into your Home Assistant configuration directory's `custom_components` folder, then restart.

## Set up

In Settings > Devices & services > Add integration, search for Roommate. Add a room, select its presence sensor and lights, then finish setup. Bed sensors, fans, speakers, and Adaptive Lighting are optional. Use the integration's configuration menu to add, edit, or remove rooms and change global settings.

You can also import an initial configuration from YAML. Add this to `configuration.yaml`, replace the entity IDs, and restart Home Assistant.

```yaml
roommate:
  rooms:
    bedroom:
      sensors:
        presence: binary_sensor.bedroom_presence
      lights:
        - light.bedroom_lamp
```

YAML is imported only when no Roommate config entry exists. After import, manage settings through the UI. Editing YAML and restarting does not update an existing entry.

See [example_config.yaml](example_config.yaml) for bed sensors, household settings, and all tuning defaults.

## Room behaviour

| Event | Action |
| --- | --- |
| Presence detected | Turn on the room lights, unless overridden, the bed is occupied, or the room is bright enough. |
| Room becomes empty | Turn off the lights after `presence_off_delay`, unless overridden. |
| Bed becomes occupied | Dim the room lights if any are on. If a light was just turned on, turn them off instead. |
| Bed becomes empty | Wait for `bed_exit_delay`, restore presence lighting, turn off fans, and pause or stop speakers. |
| Return to bed within `bed_return_timeout` | Restore the saved lights, fans, sleep mode, and previously playing media. |

Combined presence includes both the room presence sensor and bed occupancy. A bed can use a binary presence sensor, an occupant count sensor, or both. When both are configured, either can keep combined presence active. The binary sensor triggers room bed-entry and bed-exit actions, while count changes trigger household sleep and wake checks.

On bed exit, lights that are already on return to automatic control when Adaptive Lighting is configured. If the lights are off and the room is still occupied and dark enough, they fade on over `wake_transition` seconds.

The quick return window starts after `bed_exit_delay` (10 seconds by default) and lasts for `bed_return_timeout` (180 seconds by default). Returning before the exit delay ends cancels the pending bed-exit actions. Once the return window expires, Roommate discards the snapshot and stops the speakers it paused. Set `bed_return_timeout` to `0` to disable snapshots and stop speakers after the exit delay without pausing first.

### Manual overrides and resets

Turning a room light off while the room is occupied disables presence lighting. Turning a light on, leaving bed, or enabling the Presence Automations switch restores it.

Two optional timers handle empty rooms. Both default to `0` (disabled) and count minutes of continuous vacancy.

| Setting | Action when the timer expires |
| --- | --- |
| `presence_reset_timeout` | Re-enable presence lighting. |
| `room_reset_timeout` | Re-enable presence lighting, turn off lights and fans, stop speakers, and turn off the room's sleep mode. |

A nonzero `room_reset_timeout` takes precedence over `presence_reset_timeout` and runs even when there is no manual override.

### Illuminance

A room uses its own illuminance sensor when configured, otherwise the global sensor. A room threshold of `0` uses the global threshold, which defaults to 4000 lux. Turn off the room's Illuminance Gating switch to bypass the threshold.

### Household sleep and wake

Rooms with `sensors.bed.persons` configured participate in household sleep tracking. Roommate checks which people are home and whether their beds are occupied. An occupant count sensor checks how many people are in bed. A binary sensor treats an occupied bed as enough for everyone assigned to it.

When everyone tracked at home is in bed, Roommate turns off the global `sleep_lights` and enables `sleep_modes`. When someone gets up, it turns on eligible sleep lights. Once all tracked beds are empty, it disables the sleep modes.

Sleep lights use the waking room's illuminance settings. Guest Mode suppresses their activation, and each sleep light can have `inhibit` entities that block it while any is on. If global sleep modes are configured, at least one must be on for sleep lights to activate on waking.

## Entities and controls

Each room has a Roommate device. These are example entity IDs for a room named `bedroom`. Home Assistant may assign different IDs if they already exist or have been renamed.

| Entity | Available when | Purpose |
| --- | --- | --- |
| `binary_sensor.roommate_bedroom_presence` | Always | Combined room and bed presence |
| `sensor.roommate_bedroom_room_state` | Always | `empty`, `present`, or `in_bed` |
| `switch.roommate_bedroom_presence_automations` | Always | Enable presence lighting |
| `switch.roommate_bedroom_bed_automations` | Bed sensor configured | Enable bed automations |
| `switch.roommate_bedroom_illuminance_gating` | Illuminance sensor available | Apply the lux threshold |
| `button.roommate_bedroom_restore_auto_brightness` | Adaptive Lighting configured | Restore automatic light control |
| `number.roommate_bedroom_*` | Relevant sensor configured | Adjust brightness, transitions, and timers |

Presence timing controls are always available. Bed controls require a bed sensor, and the room illuminance threshold requires a room or global illuminance sensor. Number changes are saved and apply without reloading the integration.

Disabling Bed Automations excludes bed readings from combined presence and household sleep tracking. The reported occupant count becomes `0`.

The Room State sensor reports overrides in its `presence_lighting` attribute as `active` or `overridden`. It also exposes timer status and, for rooms with a bed sensor, bed automation status, occupant count, and snapshot status.

The global Roommate device contains Guest Mode, Sleep Light Transition when sleep lights are configured, and Illuminance Threshold when a global illuminance sensor is configured.

## Development

The development environment requires Python 3.14.2 or later and `uv`. From the repository root, run the same test and lint checks used in CI.

```sh
uv sync --locked
uv run --no-sync ruff check
uv run --no-sync ruff format --check
uv run --no-sync pytest --cov=custom_components.roommate
```

The integration source is in `custom_components/roommate`, with tests in `tests`. The development Python requirement comes from the test environment. Ruff targets Python 3.13 for compatibility with the minimum supported Home Assistant version.

UI labels live in `custom_components/roommate/translations/en.json`. Shared setup and options labels appear under both `config` and `options`. Update both sections when changing them.
