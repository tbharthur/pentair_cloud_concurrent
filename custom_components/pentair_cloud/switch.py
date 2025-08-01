"""Platform for switch integration (relay control)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEBUG_INFO
from .pentaircloud_modified import PentairCloudHub, PentairDevice

_LOGGER = logging.getLogger(__name__)

# Default relay program mappings - will be overridden by config
DEFAULT_RELAY_PROGRAMS = {
    "lights": 5,   # Program for lights
    "heater": 6,   # Program for heater
}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pentair relay switches."""
    hub = hass.data[DOMAIN][config_entry.entry_id]["pentair_cloud_hub"]
    devices: list[PentairDevice] = await hass.async_add_executor_job(hub.get_devices)
    
    # Get relay program mappings from config
    relay_programs = {
        "lights": config_entry.data.get("relay_lights", 5),
        "heater": config_entry.data.get("relay_heater", 6),
    }
    
    entities = []
    for device in devices:
        # Create switches for each relay
        entities.append(PentairRelaySwitch(_LOGGER, hub, device, "lights", 1, relay_programs))
        entities.append(PentairRelaySwitch(_LOGGER, hub, device, "heater", 2, relay_programs))
    
    async_add_entities(entities)


class PentairRelaySwitch(SwitchEntity):
    """Representation of a Pentair relay switch."""
    
    def __init__(
        self,
        logger: logging.Logger,
        hub: PentairCloudHub,
        device: PentairDevice,
        relay_name: str,
        relay_number: int,
        relay_programs: dict[str, int],
    ) -> None:
        """Initialize the relay switch."""
        self._logger = logger
        self._hub = hub
        self._device = device
        self._relay_name = relay_name
        self._relay_number = relay_number
        self._relay_programs = relay_programs
        self._attr_name = f"Pentair {device.nickname} {relay_name.title()}"
        self._attr_unique_id = f"pentair_{device.pentair_device_id}_relay_{relay_name}"
        self._is_on = False
        
        # Set icon based on relay type
        if relay_name == "lights":
            self._attr_icon = "mdi:lightbulb"
        elif relay_name == "heater":
            self._attr_icon = "mdi:fire"
    
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
    def is_on(self) -> bool:
        """Return true if the relay is on."""
        return self._is_on
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the relay."""
        if DEBUG_INFO:
            self._logger.info(f"Turning on {self._relay_name}")
        
        # Check if pump is running
        if not self._device.pump_running:
            self._logger.warning(
                f"Cannot turn on {self._relay_name} - pump is not running"
            )
            return
        
        # Simply activate this relay's program
        program_id = self._relay_programs[self._relay_name]
        
        await self.hass.async_add_executor_job(
            self._hub.activate_program_concurrent,
            self._device.pentair_device_id,
            program_id
        )
        
        self._is_on = True
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the relay."""
        if DEBUG_INFO:
            self._logger.info(f"Turning off {self._relay_name}")
        
        # Simply deactivate this relay's program
        program_id = self._relay_programs[self._relay_name]
        
        await self.hass.async_add_executor_job(
            self._hub.deactivate_program,
            self._device.pentair_device_id,
            program_id
        )
        
        self._is_on = False
    
    def update(self) -> None:
        """Update the relay state."""
        self._hub.update_pentair_devices_status()
        
        # Check if this relay's program is active
        relay_program_id = self._relay_programs[self._relay_name]
        
        # Find the program and check if it's active
        for program in self._device.programs:
            if program.id == relay_program_id:
                self._is_on = program.running  # This checks e10 = 3
                break
        
        if DEBUG_INFO:
            self._logger.info(
                f"Relay {self._relay_name} program {relay_program_id} is {'active' if self._is_on else 'inactive'}"
            )