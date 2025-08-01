"""Platform for pool heater climate control."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, DEBUG_INFO
from .pentaircloud_modified import PentairCloudHub, PentairDevice

_LOGGER = logging.getLogger(__name__)

# Temperature limits for pool heating
MIN_TEMP = 60  # °F
MAX_TEMP = 104  # °F


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pentair pool heater climate."""
    # Only create climate entity if temperature sensor is configured
    temperature_sensor = config_entry.data.get("temperature_sensor")
    _LOGGER.info(f"Climate setup: temperature_sensor = {temperature_sensor}")
    
    if not temperature_sensor:
        _LOGGER.info("No temperature sensor configured, skipping climate entity")
        return
    
    hub = hass.data[DOMAIN][config_entry.entry_id]["pentair_cloud_hub"]
    devices: list[PentairDevice] = await hass.async_add_executor_job(hub.get_devices)
    
    # Get heater program from config
    heater_program = config_entry.data.get("relay_heater", 6)
    
    entities = []
    
    for device in devices:
        entities.append(
            PentairPoolHeater(
                _LOGGER, 
                hub, 
                device, 
                heater_program,
                temperature_sensor
            )
        )
    
    _LOGGER.info(f"Setting up {len(entities)} climate entities")
    async_add_entities(entities, update_before_add=True)


class PentairPoolHeater(ClimateEntity, RestoreEntity):
    """Representation of a Pentair pool heater."""
    
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 1.0
    
    def __init__(
        self,
        logger: logging.Logger,
        hub: PentairCloudHub,
        device: PentairDevice,
        heater_program: int,
        temperature_sensor: str,
    ) -> None:
        """Initialize the pool heater."""
        self._logger = logger
        self._hub = hub
        self._device = device
        self._heater_program = heater_program
        self._temperature_sensor = temperature_sensor
        
        self._attr_name = f"{device.nickname} Pool Heater"
        self._attr_unique_id = f"pentair_{device.pentair_device_id}_pool_heater"
        
        self._hvac_mode = HVACMode.OFF
        self._target_temperature = 82.0
        self._current_temperature = None
        self._is_heating = False
        self._heater_on = False
        
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        
        # Restore previous state
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in [HVACMode.OFF, HVACMode.HEAT]:
                self._hvac_mode = last_state.state
            if (target_temp := last_state.attributes.get(ATTR_TEMPERATURE)) is not None:
                self._target_temperature = float(target_temp)
        
        # Track temperature sensor changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._temperature_sensor],
                self._async_temperature_changed
            )
        )
        
        # Get initial temperature
        await self._async_update_temperature()
    
    @callback
    async def _async_temperature_changed(self, event) -> None:
        """Handle temperature sensor changes."""
        await self._async_update_temperature()
        await self._async_control_heater()
        self.async_write_ha_state()
    
    async def _async_update_temperature(self) -> None:
        """Update current temperature from sensor."""
        if state := self.hass.states.get(self._temperature_sensor):
            try:
                self._current_temperature = float(state.state)
            except (ValueError, TypeError):
                self._current_temperature = None
    
    async def _async_control_heater(self) -> None:
        """Control heater based on mode and temperature."""
        if self._hvac_mode == HVACMode.OFF:
            # Turn off heater
            if self._heater_on:
                await self._async_turn_off_heater()
        elif self._hvac_mode == HVACMode.HEAT:
            if self._current_temperature is None:
                return
                
            # Simple thermostat logic with 1°F hysteresis
            if self._current_temperature < (self._target_temperature - 1):
                # Turn on heater
                if not self._heater_on:
                    await self._async_turn_on_heater()
            elif self._current_temperature > self._target_temperature:
                # Turn off heater
                if self._heater_on:
                    await self._async_turn_off_heater()
    
    async def _async_turn_on_heater(self) -> None:
        """Turn on the pool heater."""
        # Ensure pump is running
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
            
        await self.hass.async_add_executor_job(
            self._hub.activate_program_concurrent,
            self._device.pentair_device_id,
            self._heater_program
        )
        self._heater_on = True
        self._is_heating = True
    
    async def _async_turn_off_heater(self) -> None:
        """Turn off the pool heater."""
        await self.hass.async_add_executor_job(
            self._hub.deactivate_program,
            self._device.pentair_device_id,
            self._heater_program
        )
        self._heater_on = False
        self._is_heating = False
    
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
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._current_temperature
    
    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._target_temperature
    
    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode."""
        return self._hvac_mode
    
    @property
    def hvac_action(self) -> str:
        """Return the current running hvac operation."""
        if self._hvac_mode == HVACMode.OFF:
            return "off"
        return "heating" if self._is_heating else "idle"
    
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._target_temperature = temperature
            await self._async_control_heater()
            self.async_write_ha_state()
    
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""
        self._hvac_mode = hvac_mode
        await self._async_control_heater()
        self.async_write_ha_state()
    
    def update(self) -> None:
        """Update heater state."""
        self._hub.update_pentair_devices_status()
        
        # Check if heater program is active
        for program in self._device.programs:
            if program.id == self._heater_program:
                self._heater_on = program.running
                self._is_heating = program.running and self._hvac_mode == HVACMode.HEAT
                break