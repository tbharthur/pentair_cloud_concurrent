"""Platform for switch integration (relay control)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
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
        # Only create heater switch (lights are handled as light entity)
        entities.append(PentairRelaySwitch(_LOGGER, hub, device, "heater", 2, relay_programs))
    
    _LOGGER.info(f"Setting up {len(entities)} switch entities")
    async_add_entities(entities, update_before_add=True)


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
        # Cleaner naming
        relay_display_name = "Light" if relay_name == "lights" else relay_name.title()
        self._attr_name = f"{device.nickname} {relay_display_name}"
        self._attr_unique_id = f"pentair_{device.pentair_device_id}_relay_{relay_name}"
        self._is_on = False
        
        # Set icon and device class based on relay type
        if relay_name == "lights":
            self._attr_icon = "mdi:lightbulb"
            # No specific device class for pool lights, but the icon helps
        elif relay_name == "heater":
            self._attr_icon = "mdi:fire"
            # No specific device class for pool heater switch
    
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
        
        # For heater, ensure pump is running
        if self._relay_name == "heater":
            if DEBUG_INFO:
                self._logger.info(
                    f"Heater switch activated. Pump running: {self._device.pump_running}, "
                    f"Active pump program: {self._device.active_pump_program}"
                )
            
            if not self._device.pump_running:
                if DEBUG_INFO:
                    self._logger.info(
                        "Heater requested but pump is off - starting pump at medium speed"
                    )
            
            # Get medium speed program from config
            config_entry = self.hass.config_entries.async_get_entry(
                list(self.hass.data[DOMAIN].keys())[0]
            )
            medium_speed_program = config_entry.data.get("speed_medium", 2)
            
            # Turn on pump at medium speed
            await self.hass.async_add_executor_job(
                self._hub.activate_program_concurrent,
                self._device.pentair_device_id,
                medium_speed_program
            )
            
            # Wait a moment for pump to start
            await asyncio.sleep(2)
            
            # Force a status update to get the latest pump state
            await self.hass.async_add_executor_job(
                self._hub.update_pentair_devices_status
            )
            
            # Wait a bit more for the update to complete
            await asyncio.sleep(1)
            
            # Update pump speed entity to reflect the new speed
            pump_speed_entity_id = f"number.{self._device.nickname.lower().replace(' ', '_')}_speed_control"
            try:
                # Force update of the pump speed entity
                await self.hass.services.async_call(
                    "homeassistant",
                    "update_entity",
                    {"entity_id": pump_speed_entity_id},
                    blocking=False
                )
                if DEBUG_INFO:
                    self._logger.info(f"Requested update for pump speed entity: {pump_speed_entity_id}")
            except Exception as e:
                if DEBUG_INFO:
                    self._logger.warning(f"Could not update pump speed entity: {e}")
        
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