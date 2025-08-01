"""Platform for pool light control via relay programs."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEBUG_INFO
from .pentaircloud_modified import PentairCloudHub, PentairDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pentair relay lights."""
    hub = hass.data[DOMAIN][config_entry.entry_id]["pentair_cloud_hub"]
    devices: list[PentairDevice] = await hass.async_add_executor_job(hub.get_devices)
    
    # Get relay program mapping from config
    lights_program = config_entry.data.get("relay_lights", 5)
    
    entities = []
    for device in devices:
        # Create light entity for pool lights
        entities.append(PentairRelayLight(_LOGGER, hub, device, lights_program))
    
    async_add_entities(entities)


class PentairRelayLight(LightEntity):
    """Representation of a Pentair pool light controlled via relay."""
    
    _attr_icon = "mdi:lightbulb"
    
    def __init__(
        self,
        logger: logging.Logger,
        hub: PentairCloudHub,
        device: PentairDevice,
        lights_program: int,
    ) -> None:
        """Initialize the relay light."""
        self._logger = logger
        self._hub = hub
        self._device = device
        self._lights_program = lights_program
        self._attr_name = f"{device.nickname} Light"
        self._attr_unique_id = f"pentair_{device.pentair_device_id}_pool_light"
        self._is_on = False
    
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
        """Return true if the light is on."""
        return self._is_on
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        if DEBUG_INFO:
            self._logger.info(f"Turning on pool lights")
        
        # Check if pump is running
        if not self._device.pump_running:
            self._logger.warning(
                "Cannot turn on lights - pump is not running"
            )
            return
        
        # Activate lights program
        await self.hass.async_add_executor_job(
            self._hub.activate_program_concurrent,
            self._device.pentair_device_id,
            self._lights_program
        )
        
        self._is_on = True
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        if DEBUG_INFO:
            self._logger.info(f"Turning off pool lights")
        
        # Deactivate lights program
        await self.hass.async_add_executor_job(
            self._hub.deactivate_program,
            self._device.pentair_device_id,
            self._lights_program
        )
        
        self._is_on = False
    
    def update(self) -> None:
        """Update the light state."""
        self._hub.update_pentair_devices_status()
        
        # Check if lights program is active
        for program in self._device.programs:
            if program.id == self._lights_program:
                self._is_on = program.running  # This checks e10 = 3
                break
        
        if DEBUG_INFO:
            self._logger.info(
                f"Pool lights program {self._lights_program} is {'active' if self._is_on else 'inactive'}"
            )