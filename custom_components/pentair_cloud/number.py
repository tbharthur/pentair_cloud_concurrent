"""Platform for number integration (pump speed control)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEBUG_INFO
from .pentaircloud_modified import PentairCloudHub, PentairDevice

_LOGGER = logging.getLogger(__name__)

# Default speed mappings - will be overridden by config
DEFAULT_SPEED_PROGRAMS = {
    0: None,      # Off
    30: 3,        # Low speed
    50: 2,        # Medium speed
    75: 4,        # High speed
    100: 1        # Max speed
}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pentair pump speed control."""
    hub = hass.data[DOMAIN][config_entry.entry_id]["pentair_cloud_hub"]
    devices: list[PentairDevice] = await hass.async_add_executor_job(hub.get_devices)
    
    # Get program mappings from config
    speed_programs = {
        0: None,
        30: config_entry.data.get("speed_low", 3),
        50: config_entry.data.get("speed_medium", 2),
        75: config_entry.data.get("speed_high", 4),
        100: config_entry.data.get("speed_max", 1)
    }
    
    entities = []
    
    for device in devices:
        # Create pump speed control for each device
        entities.append(PentairPumpSpeed(_LOGGER, hub, device, speed_programs))
    
    _LOGGER.info(f"Setting up {len(entities)} number entities")
    async_add_entities(entities, update_before_add=True)


class PentairPumpSpeed(NumberEntity):
    """Representation of a Pentair pump speed control."""
    
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 25
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:pump"
    _attr_native_unit_of_measurement = "%"
    
    def __init__(
        self,
        logger: logging.Logger,
        hub: PentairCloudHub,
        device: PentairDevice,
        speed_programs: dict[int, int],
    ) -> None:
        """Initialize the pump speed control."""
        self._logger = logger
        self._hub = hub
        self._device = device
        self._speed_programs = speed_programs
        self._attr_name = f"{device.nickname} Speed Control"
        self._attr_unique_id = f"pentair_{device.pentair_device_id}_pump_speed"
        self._current_speed = 0
        
    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {
                (DOMAIN, f"pentair_{self._device.pentair_device_id}")
            },
            "name": self._device.nickname,
            "model": self._device.nickname,
            "sw_version": "1.0",
            "manufacturer": "Pentair",
        }
    
    @property
    def native_value(self) -> float:
        """Return the current pump speed."""
        return self._current_speed
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the pump speed."""
        if DEBUG_INFO:
            self._logger.info(f"Setting pump speed to {value}%")
        
        # Convert speed to program
        if value == 0:
            # Only stop the currently active pump program
            active_program = self._device.active_pump_program
            if active_program:
                if DEBUG_INFO:
                    self._logger.info(f"Deactivating active pump program {active_program}")
                await self.hass.async_add_executor_job(
                    self._hub.deactivate_program,
                    self._device.pentair_device_id,
                    active_program
                )
            self._current_speed = 0
        else:
            # Find closest speed program
            speeds = list(self._speed_programs.keys())
            closest_speed = min(speeds, key=lambda x: abs(x - value))
            program_id = self._speed_programs[closest_speed]
            
            if program_id:
                # Activate the speed program
                await self.hass.async_add_executor_job(
                    self._hub.activate_program_concurrent, 
                    self._device.pentair_device_id, 
                    program_id
                )
                self._current_speed = closest_speed
                
                if DEBUG_INFO:
                    self._logger.info(
                        f"Activated program {program_id} for {closest_speed}% speed"
                    )
    
    def update(self) -> None:
        """Update the current speed based on device status."""
        self._hub.update_pentair_devices_status()
        
        # Check which speed program is active
        active_program = self._device.active_pump_program
        if active_program:
            # Find speed for this program
            for speed, prog_id in self._speed_programs.items():
                if prog_id == active_program:
                    self._current_speed = speed
                    break
        else:
            self._current_speed = 0