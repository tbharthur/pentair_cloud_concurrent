# pentair_cloud - Concurrent Control Edition
Homeassistant Pentair cloud custom integration with enhanced concurrent program control.

Supports the Pentair IntelliFlo 3 VS Pump with the Wifi module. This integration provides:
- **Pump Speed Control** - A 0-100% slider that maps to your configured pump speed programs
- **Individual Relay Switches** - Separate switches for pool lights and heater
- **Legacy Program Support** - Virtual "Light" entities for each program (backward compatibility)
- **Concurrent Program Activation** - Run pump speed and relay programs simultaneously

Data is pulled from the Pentair Web service used by the Pentair Home App.
Note: This project is not associated with or endorsed by Pentair.

## What's New in Concurrent Control Edition

This fork enables **independent control** of pump speed and relay states by leveraging a discovered capability: multiple programs can be active simultaneously. One program controls the pump motor (tracked by s14), while other programs can control relays independently.

### Key Features:
- **Pump Speed Slider**: Control pump speed from 0-100% (mapped to your preset programs)
- **Relay Switches**: Turn lights and heater on/off independently
- **Smart Control**: Relays only activate when pump is running
- **Full Integration**: Perfect for creating climate entities with external temperature sensors

Example: You can now run your pump at 50% speed while independently controlling your pool lights and heater - something not possible with the original single-program limitation.
## Installation with HACS

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)

The simplest way to install this integration is with the Home Assistant Community Store (HACS). This is not (yet) part of the default store and will need to be added as a custom repository.

Setting up a custom repository is done by:

1. Go into HACS from the side bar.
2. Click into Integrations.
3. Click the 3-dot menu in the top right and select `Custom repositories`
4. In the UI that opens, copy and paste the [url for this github repo](https://github.com/tbharthur/pentair_cloud_concurrent) into the `Add custom repository URL` field.
5. Set the category to `Integration`.
6. Click the `Add` button. Further configuration is done within the Integrations configuration in Home Assistant. You may need to restart home assistant and clear your browser cache before it appears, try ctrl+shift+r if you don't see it in the configuration list.

## Configuration

### Required Program Setup

For this integration to work properly, you need to configure your Pentair programs as follows:

**Speed Programs** (configure these with your desired speeds):
- 4 programs with different pump speeds (e.g., 30%, 50%, 75%, 100%)

**Relay Control Programs** (configure these with appropriate relay settings):
- 1 program for Lights (Relay 1 ON, Relay 2 OFF)
- 1 program for Heater (Relay 1 OFF, Relay 2 ON)

During setup, you'll be able to select which programs control each function from a dropdown list showing your actual program names. You can also update these selections later in the integration options.

## Usage

After installation and configuration, you'll have these entities:

### Primary Controls (Use These!)

#### Pump Speed Control
- **Entity**: `number.[device_name]_speed_control`
- **Name**: "[Device Name] Speed Control"
- **Control**: 0-100% slider (0 = off)

#### Relay Switches
- **Light Entity**: `switch.[device_name]_light`
- **Light Name**: "[Device Name] Light"
- **Heater Entity**: `switch.[device_name]_heater`
- **Heater Name**: "[Device Name] Heater"

### Program Entities (Hidden by Default)
- `light.[device_name]_[program_name]_program` - Individual program controls
- These are marked as diagnostic entities and hidden by default
- Only use if you need direct program control for automation

## Example Automations

### Create a Pool Heater Climate Entity
```yaml
climate:
  - platform: generic_thermostat
    name: Pool Heater
    heater: switch.pentair_pool_relay_heater
    target_sensor: sensor.pool_temperature
    min_temp: 70
    max_temp: 90
```

### Dashboard Card
```yaml
type: vertical-stack
cards:
  - type: entities
    title: Pool Control
    entities:
      - entity: number.pentair_pool_pump_speed
        name: Pump Speed
      - entity: switch.pentair_pool_relay_lights
        name: Pool Lights
      - entity: climate.pool_heater
        name: Pool Heater
```

## Manual Installation

If you don't want to use HACS or just prefer manual installs, you can install this like any other custom component. Just merge the `custom_components` folder with the one in your Home Assistant config folder and you may need to manually install the `pycognito` and `requests-aws4auth` library.

## Technical Details

This integration leverages the ability to have multiple Pentair programs active simultaneously:
- One program controls the pump motor speed (tracked by field s14)
- Other programs can control relays independently (tracked by fields s30/s31)
- Programs use the e10 field with value 3 to indicate active control
- Both relay programs can be active at the same time, eliminating the need for a "both relays" program

This approach provides granular control over pump speed and relay states that isn't possible through the standard Pentair app interface.
