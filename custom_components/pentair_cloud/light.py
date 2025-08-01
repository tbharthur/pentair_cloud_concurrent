"""Platform for light integration."""
from __future__ import annotations

import logging

# Import the device class from the component that you want to support
import homeassistant.helpers.config_validation as cv
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    PLATFORM_SCHEMA,
    LightEntity,
    ColorMode,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from .const import DOMAIN, DEBUG_INFO
from .pentaircloud_modified import PentairCloudHub, PentairDevice, PentairPumpProgram
from logging import Logger

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    hub = hass.data[DOMAIN][config_entry.entry_id]["pentair_cloud_hub"]
    devices: list[PentairDevice] = await hass.async_add_executor_job(hub.get_devices)
    
    entities = []
    
    # Add program entities (hidden by default)
    for device in devices:
        for program in device.programs:
            entities.append(PentairCloudLight(_LOGGER, hub, device, program))
    
    # Add pool light entity
    lights_program = config_entry.data.get("relay_lights", 5)
    for device in devices:
        entities.append(PentairPoolLight(_LOGGER, hub, device, lights_program))
    
    async_add_entities(entities)


class PentairCloudLight(LightEntity):
    global DOMAIN
    global DEBUG_INFO
    
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        LOGGER: Logger,
        hub: PentairCloudHub,
        pentair_device: PentairDevice,
        pentair_program: PentairPumpProgram,
    ) -> None:
        self.LOGGER = LOGGER
        self.hub = hub
        self.pentair_device = pentair_device
        self.pentair_program = pentair_program
        self._name = f"{self.pentair_device.nickname} - {self.pentair_program.name} (Program)"
        self._state = self.pentair_program.running
        # Mark as diagnostic entity to hide by default
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if DEBUG_INFO:
            self.LOGGER.info("Pentair Cloud Pump " + self._name + " Configured")

    @property
    def unique_id(self):
        return (
            f"pentair_"
            + self.pentair_device.pentair_device_id
            + "_"
            + str(self.pentair_program.id)
        )

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, f"pentair_" + self.pentair_device.pentair_device_id)
            },
            "name": self.pentair_device.nickname,
            "model": self.pentair_device.nickname,
            "sw_version": "1.0",
            "manufacturer": "Pentair",
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        if DEBUG_INFO:
            self.LOGGER.info(
                "Pentair Cloud Pump "
                + self.pentair_device.pentair_device_id
                + " Called IS_ON"
            )
        self._state = self.pentair_program.running
        return self._state

    def turn_on(self, **kwargs) -> None:
        """Instruct the light to turn on.
        You can skip the brightness part if your light does not support
        brightness control.
        """
        if DEBUG_INFO:
            self.LOGGER.info(
                "Pentair Cloud Pump "
                + self.pentair_device.pentair_device_id
                + " Called ON program: "
                + str(self.pentair_program.id)
            )
        self._state = True
        self.hub.start_program(
            self.pentair_device.pentair_device_id, self.pentair_program.id
        )

    def turn_off(self, **kwargs) -> None:
        """Instruct the light to turn off."""
        if DEBUG_INFO:
            self.LOGGER.info(
                "Pentair Cloud Pump "
                + self.pentair_device.pentair_device_id
                + " Called OFF program: "
                + str(self.pentair_program.id)
            )
        self._state = False
        self.hub.stop_program(
            self.pentair_device.pentair_device_id, self.pentair_program.id
        )

    def update(self) -> None:
        """Fetch new state data for this light.
        This is the only method that should fetch new data for Home Assistant.
        """
        self.hub.update_pentair_devices_status()
        self._state = self.pentair_program.running
        if DEBUG_INFO:
            self.LOGGER.info(
                "Pentair Cloud Pump "
                + self.pentair_device.pentair_device_id
                + " Called UPDATE"
            )


class PentairPoolLight(LightEntity):
    """Representation of a Pentair pool light controlled via relay."""
    
    _attr_icon = "mdi:lightbulb"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    
    def __init__(
        self,
        logger: Logger,
        hub: PentairCloudHub,
        device: PentairDevice,
        lights_program: int,
    ) -> None:
        """Initialize the pool light."""
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
    
    def turn_on(self, **kwargs) -> None:
        """Turn on the light."""
        if DEBUG_INFO:
            self._logger.info(f"Turning on pool lights")
        
        # Update device status first
        self._hub.update_pentair_devices_status()
        
        # Activate lights program
        if DEBUG_INFO:
            self._logger.info(f"Activating lights program {self._lights_program} on device {self._device.pentair_device_id}")
            
        self._hub.activate_program_concurrent(
            self._device.pentair_device_id,
            self._lights_program
        )
        
        self._is_on = True
        
        if DEBUG_INFO:
            self._logger.info(f"Light activation complete")
    
    def turn_off(self, **kwargs) -> None:
        """Turn off the light."""
        if DEBUG_INFO:
            self._logger.info(f"Turning off pool lights")
        
        # Deactivate lights program
        self._hub.deactivate_program(
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
