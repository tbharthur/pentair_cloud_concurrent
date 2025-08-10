# pentair_cloud - Concurrent Control Edition
Homeassistant Pentair cloud custom integration with enhanced concurrent program control.

Supports the Pentair IntelliFlo 3 VS Pump with the Wifi module. This integration provides:
- **Pump Speed Control** - Fan entity with 0-100% speed control and preset modes (HomeKit compatible!)
- **Heater Safety Logic** - Automatic pump speed enforcement when heater is running (minimum 50%)
- **Individual Relay Control** - Pool lights as light entity, heater as switch
- **Automatic Climate Entity** - Optional thermostat creation with temperature sensor
- **Legacy Program Support** - Virtual "Light" entities for each program (backward compatibility)
- **Concurrent Program Activation** - Run pump speed and relay programs simultaneously

Data is pulled from the Pentair Web service used by the Pentair Home App.
Note: This project is not associated with or endorsed by Pentair.

## What's New in Concurrent Control Edition

This fork enables **independent control** of pump speed and relay states by leveraging a discovered capability: multiple programs can be active simultaneously. One program controls the pump motor (tracked by s14), while other programs can control relays independently.

### 🎉 Version 2.0 - Fan Entity Update
- **NEW: Fan Entity for Pump Control** - Replaces number entity with proper fan entity
- **NEW: HomeKit Compatible** - Works natively with Apple HomeKit as a fan with speed control
- **NEW: Heater Safety Logic** - Pump automatically maintains minimum 50% speed when heater is on
- **NEW: Preset Modes** - Easy selection: Off, Low (30%), Medium (50%), High (75%), Max (100%)
- **IMPROVED: Response Time** - Reduced delays from 30s/60s to 5s/10s for better responsiveness
- **IMPROVED: Debouncing** - Smooth slider control without command flooding

### Key Features:
- **Pump Speed Control**: Fan entity with percentage and preset modes
- **Safety Enforcement**: Prevents unsafe pump operation when heater is running
- **Relay Switches**: Turn lights and heater on/off independently
- **Smart Control**: Automatic pump management for heater operation
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

**Speed Programs** (required for fan entity speed control):
- **Program 1**: Quick Clean or Max Speed (100%)
- **Program 2**: Regular or Medium Speed (50%)
- **Program 3**: Low Speed (30%)
- **Program 4**: Service Mode or High Speed (75%)

**Relay Control Programs** (configure these with appropriate relay settings):
- **Program 5 or 6**: Lights (Relay 1 ON, Relay 2 OFF)
- **Program 6 or 7**: Heater (Relay 1 OFF, Relay 2 ON)

During setup, you'll be able to:
- Select which programs control each function from dropdown lists
- Optionally select a temperature sensor for automatic pool heater thermostat creation
- Update these selections later in the integration options

## Usage

After installation and configuration, you'll have these entities:

### Primary Controls (Use These!)

#### Pump Speed Control (NEW - Fan Entity!)
- **Entity**: `fan.[device_name]_pump`
- **Name**: "[Device Name] Pump"
- **Type**: Fan entity with speed control
- **Control**: 
  - Percentage: 0-100% speed control
  - Preset Modes: Off, Low (30%), Medium (50%), High (75%), Max (100%)
- **HomeKit**: Appears as a fan with speed control
- **Safety**: Enforces minimum 50% speed when heater is on

#### Pool Light
- **Entity**: `light.[device_name]_light`
- **Name**: "[Device Name] Light"
- **Type**: Light entity with on/off control

#### Pool Heater Switch
- **Entity**: `switch.[device_name]_heater`
- **Name**: "[Device Name] Heater"
- **Type**: Switch entity for manual control

#### Pool Heater Thermostat (if temperature sensor selected)
- **Entity**: `climate.[device_name]_pool_heater`
- **Name**: "[Device Name] Pool Heater"
- **Type**: Climate entity with temperature control (60-104°F)

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
      - entity: fan.pool_pump
        name: Pump Speed
      - entity: light.pool_lights
        name: Pool Lights
      - entity: climate.pool_heater
        name: Pool Heater
```

### HomeKit Configuration
```yaml
homekit:
  filter:
    include_entities:
      - fan.pool_pump  # Will appear as fan with speed control
      - light.pool_lights
      - climate.pool_heater
```

### Example Automations with Fan Entity
```yaml
# Turn pump to medium speed at sunset
automation:
  - alias: "Pool Pump Evening Schedule"
    trigger:
      - platform: sun
        event: sunset
    action:
      - service: fan.turn_on
        target:
          entity_id: fan.pool_pump
        data:
          percentage: 50  # or use preset_mode: "medium"

# Use preset modes for easy control
  - alias: "Pool Cleaning Mode"
    trigger:
      - platform: time
        at: "10:00:00"
    action:
      - service: fan.set_preset_mode
        target:
          entity_id: fan.pool_pump
        data:
          preset_mode: "max"  # Run at 100% for cleaning
```

## Migration from v1.x (Number Entity) to v2.0 (Fan Entity)

If you're upgrading from the previous version that used a number entity for pump control:

1. **Update the integration** through HACS or manually
2. **Restart Home Assistant**
3. The old `number.[device]_speed_control` entity will be gone
4. New entity: `fan.[device]_pump` will appear
5. **Update your automations** to use fan services:
   - Old: `number.set_value` with `value: 50`
   - New: `fan.turn_on` with `percentage: 50` or `preset_mode: "medium"`
6. **Update dashboards** to reference the new fan entity
7. **Add to HomeKit** if desired - it will appear as a fan with speed control

## Manual Installation

If you don't want to use HACS or just prefer manual installs, you can install this like any other custom component. Just merge the `custom_components` folder with the one in your Home Assistant config folder and you may need to manually install the `pycognito` and `requests-aws4auth` library.

## Technical Details

### Concurrent Program Control
This integration leverages the ability to have multiple Pentair programs active simultaneously:
- One program controls the pump motor speed (tracked by field s14)
- Other programs can control relays independently (tracked by fields s30/s31)
- Programs use the e10 field with value 3 to indicate active control
- Both relay programs can be active at the same time, eliminating the need for a "both relays" program

### Heater Safety Implementation
The fan entity includes built-in safety logic to prevent equipment damage:
- **Minimum Speed Enforcement**: Pump automatically maintains 50% minimum speed when heater is on
- **Turn-off Prevention**: Pump cannot be turned off while heater is running
- **Automatic Start**: If heater turns on while pump is off/slow, pump automatically starts at 50%
- **User Notifications**: Clear persistent notifications explain when and why safety overrides occur

### Performance Improvements
- **Reduced API Delays**: UPDATE_MIN_SECONDS reduced from 60s to 10s
- **Faster Command Response**: PROGRAM_START_MIN_SECONDS reduced from 30s to 5s
- **Debounced Control**: 1.5 second debounce prevents command flooding during slider adjustments

This approach provides granular control over pump speed and relay states that isn't possible through the standard Pentair app interface.
