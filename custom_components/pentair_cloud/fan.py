"""Fan platform for Pentair pump control with heater safety."""
import logging
from typing import Any, Optional, List
from datetime import datetime, timedelta
import asyncio
import time

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, DEBUG_INFO
from .pentaircloud import PentairCloudHub, PentairDevice, PentairPumpProgram

_LOGGER = logging.getLogger(__name__)

# Poll every 30 seconds to update state
SCAN_INTERVAL = timedelta(seconds=30)

PRESET_MODES = {
    "off": 0,
    "low": 30,
    "medium": 50,
    "high": 75,
    "max": 100
}

# Note: Actual program mappings come from config_entry.data
# The old hardcoded SPEED_TO_PROGRAM and PROGRAM_TO_SPEED have been removed
# as they assumed fixed program IDs which may not match user's setup

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pentair pump fan entities."""
    # Try both keys for compatibility
    hub = hass.data[DOMAIN][config_entry.entry_id].get("hub") or hass.data[DOMAIN][config_entry.entry_id].get("pentair_cloud_hub")
    coordinator = hass.data[DOMAIN][config_entry.entry_id].get("coordinator")
    
    # Get the program mappings from config
    program_mappings = {
        "low": config_entry.data.get("speed_low", 3),
        "medium": config_entry.data.get("speed_medium", 2),
        "high": config_entry.data.get("speed_high", 4),
        "max": config_entry.data.get("speed_max", 1),
    }
    
    _LOGGER.info(f"Using program mappings from config: {program_mappings}")
    
    entities = []
    for device in hub.get_devices():
        # Create fan entity for each pump device with config mappings
        fan_entity = PentairPumpFan(hub, device, coordinator, hass, program_mappings)
        entities.append(fan_entity)
        
        # Store reference for heater integration
        hass.data[DOMAIN][config_entry.entry_id]["pump_fan"] = fan_entity
        
        _LOGGER.info(f"Created pump fan entity for {device.nickname}")
    
    async_add_entities(entities, True)


class PentairPumpFan(FanEntity):
    """Pentair pump fan entity with heater safety."""
    
    def __init__(self, hub: PentairCloudHub, device: PentairDevice, coordinator, hass: HomeAssistant, program_mappings: dict):
        """Initialize the fan."""
        self._hub = hub
        self._device = device
        self._coordinator = coordinator
        self.hass = hass
        self._program_mappings = program_mappings  # Store the actual program mappings from config
        self._attr_unique_id = f"pentair_pump_{device.pentair_device_id}"
        self._attr_name = f"{device.nickname} Pump"
        
        # Create reverse mapping for state updates
        self._program_to_speed = {
            program_mappings["low"]: 30,
            program_mappings["medium"]: 50,
            program_mappings["high"]: 75,
            program_mappings["max"]: 100,
        }
        
        _LOGGER.info(f"Fan entity initialized with program mappings: {self._program_mappings}")
        _LOGGER.info(f"Program to speed mapping: {self._program_to_speed}")
        
        # State tracking
        self._attr_is_on = False
        self._attr_percentage = 0
        self._attr_preset_mode = "off"
        
        # Debounce tracking
        self._pending_speed_change = None
        self._last_speed_change = time.time()
        self._speed_change_task = None
        
        # Heater safety tracking
        self._heater_on = False
        self._minimum_speed_override = False
        
        # Update state from device
        self._update_state_from_device()
        
        # Store unsub callback for cleanup
        self._unsub_timer = None
    
    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._attr_unique_id
    
    @property
    def name(self) -> str:
        """Return the name of the fan."""
        return self._attr_name
    
    @property
    def is_on(self) -> bool:
        """Return true if the fan is on."""
        return self._attr_is_on
    
    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        if self._attr_is_on:
            return "mdi:pump"
        return "mdi:pump-off"
    
    @property
    def percentage(self) -> Optional[int]:
        """Return current speed percentage (0-100)."""
        return self._attr_percentage
    
    @property
    def speed_count(self) -> int:
        """Return number of speeds."""
        return 4  # Low, Medium, High, Max
    
    @property
    def preset_modes(self) -> List[str]:
        """Return available preset modes."""
        return list(PRESET_MODES.keys())
    
    @property
    def preset_mode(self) -> Optional[str]:
        """Return current preset mode."""
        return self._attr_preset_mode
    
    @property
    def supported_features(self) -> int:
        """Return supported features."""
        # As of HA 2024.8, TURN_ON and TURN_OFF must be explicitly declared
        return (
            FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.PRESET_MODE 
            | FanEntityFeature.SET_SPEED
        )
    
    @property
    def device_info(self):
        """Return device info to associate with the Pool Pump device."""
        return {
            "identifiers": {
                (DOMAIN, f"pentair_{self._device.pentair_device_id}")
            },
            "name": self._device.nickname,
            "model": self._device.nickname,
            "sw_version": "1.0",
            "manufacturer": "Pentair",
        }
    
    def _check_heater_safety(self, requested_speed: int) -> int:
        """
        Enforce heater safety rules.
        Returns adjusted speed if heater requires minimum flow.
        """
        if self._heater_on:
            if requested_speed < 50 and requested_speed > 0:
                _LOGGER.warning(
                    f"Heater is ON - enforcing minimum 50% pump speed for safety (requested: {requested_speed}%)"
                )
                self._minimum_speed_override = True
                return 50  # Force minimum 50% when heater is on
            elif requested_speed == 0:
                _LOGGER.error(
                    "SAFETY: Cannot turn off pump while heater is running! "
                    "Please turn off heater first."
                )
                # Return current speed to prevent shutdown
                return self._attr_percentage if self._attr_percentage > 0 else 50
        
        self._minimum_speed_override = False
        return requested_speed
    
    async def async_set_percentage(self, percentage: int) -> None:
        """Set pump speed with debouncing and heater safety."""
        _LOGGER.info(f"Setting pump speed to {percentage}%")
        
        # Ensure percentage is within valid range
        percentage = max(0, min(100, int(percentage)))
        
        # Apply heater safety rules
        safe_speed = self._check_heater_safety(percentage)
        
        if safe_speed != percentage:
            # Notify user if speed was adjusted for safety
            await self._notify_safety_override(percentage, safe_speed)
            if safe_speed == self._attr_percentage:
                # Speed unchanged due to safety, don't proceed
                return
        
        # Cancel any pending speed change
        if self._speed_change_task and not self._speed_change_task.done():
            self._speed_change_task.cancel()
        
        # Store pending speed change
        self._pending_speed_change = safe_speed
        self._last_speed_change = time.time()
        
        # Create debounced task
        self._speed_change_task = asyncio.create_task(
            self._debounced_speed_change(safe_speed)
        )
    
    async def _debounced_speed_change(self, speed: int) -> None:
        """Execute speed change after debounce delay."""
        try:
            # Wait for slider to settle (reduced to 0.5 seconds for better responsiveness)
            await asyncio.sleep(0.5)
            
            # Only execute if this is still the latest request
            if self._pending_speed_change == speed:
                await self._execute_speed_change(speed)
        except asyncio.CancelledError:
            _LOGGER.debug(f"Speed change to {speed}% was cancelled")
    
    async def _execute_speed_change(self, speed: int) -> None:
        """Execute the actual speed change."""
        _LOGGER.info(f"Executing pump speed change to {speed}%")
        
        try:
            # Map speed percentage to appropriate program using actual config mappings
            if speed == 0:
                target_program_id = None
                actual_speed = 0
            elif speed <= 30:
                target_program_id = self._program_mappings["low"]
                actual_speed = 30  # Actual speed is 30%
            elif speed <= 50:
                target_program_id = self._program_mappings["medium"]
                actual_speed = 50  # Actual speed is 50%
            elif speed <= 75:
                target_program_id = self._program_mappings["high"]
                actual_speed = 75  # Actual speed is 75%
            else:
                target_program_id = self._program_mappings["max"]
                actual_speed = 100  # Actual speed is 100%
            
            _LOGGER.info(f"Mapped {speed}% to program {target_program_id} with actual speed {actual_speed}%")
            
            # Only stop pump programs (from our mapped programs), not relay programs
            for program in self._device.programs:
                if program.running and program.id in self._program_to_speed:
                    _LOGGER.debug(f"Stopping pump program {program.id} ({program.name})")
                    success = await self.hass.async_add_executor_job(
                        self._hub.stop_program,
                        self._device.pentair_device_id,
                        program.id
                    )
                    if not success:
                        _LOGGER.error(f"Failed to stop program {program.id}")
                    # Small delay between stop and start
                    await asyncio.sleep(0.5)
            
            if target_program_id is not None:
                # Start the appropriate program
                _LOGGER.info(f"Starting program {target_program_id} for {actual_speed}% speed")
                success = await self.hass.async_add_executor_job(
                    self._hub.start_program,
                    self._device.pentair_device_id,
                    target_program_id
                )
                
                if success:
                    # Set the actual speed, not the requested speed
                    self._attr_percentage = actual_speed
                    self._attr_is_on = True
                    self._update_preset_mode(actual_speed)
                    _LOGGER.info(f"Successfully set pump to {actual_speed}%")
                else:
                    _LOGGER.error(f"Failed to start program {target_program_id}")
                    # Don't update state if command failed
                    return
            else:
                # Speed is 0, pump is off
                self._attr_percentage = 0
                self._attr_is_on = False
                self._attr_preset_mode = "off"
                _LOGGER.info("Pump turned off")
            
            # Force immediate status update
            await self.hass.async_add_executor_job(
                self._hub.update_pentair_devices_status
            )
            
            # Wait a moment for the status to propagate
            await asyncio.sleep(1)
            
            # Re-read state from device to ensure accuracy
            self._update_state_from_device()
            
            # Update HA state
            self.async_write_ha_state()
            
        except Exception as e:
            _LOGGER.error(f"Error executing speed change: {e}")
    
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set pump to preset mode."""
        speed = PRESET_MODES.get(preset_mode, 0)
        await self.async_set_percentage(speed)
    
    async def async_turn_on(self, percentage: Optional[int] = None, preset_mode: Optional[str] = None, **kwargs) -> None:
        """Turn on pump."""
        _LOGGER.info(f"Turning on pump with percentage={percentage}, preset_mode={preset_mode}")
        
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            # Ensure we use a valid speed
            if percentage > 0:
                await self.async_set_percentage(percentage)
            else:
                # If percentage is 0 or unset, default to medium
                await self.async_set_percentage(50)
        else:
            # Default to medium speed
            await self.async_set_percentage(50)
    
    async def async_turn_off(self, **kwargs) -> None:
        """Turn off pump with heater safety check."""
        _LOGGER.info("Turning off pool pump")
        
        if self._heater_on:
            _LOGGER.error(
                "SAFETY: Cannot turn off pump while heater is running! "
                "Turn off heater first."
            )
            
            # Create persistent notification
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Pool Pump Safety Alert",
                    "message": "Cannot turn off pool pump while heater is active. "
                               "Please turn off the heater first for safety.",
                    "notification_id": "pentair_pump_safety_block"
                }
            )
            
            raise HomeAssistantError(
                "Pool pump cannot be turned off while heater is active. "
                "Please turn off the heater first for safety."
            )
        
        # Stop all pump programs directly
        try:
            any_failed = False
            for program in self._device.programs:
                if program.running and program.id in self._program_to_speed:
                    _LOGGER.debug(f"Stopping pump program {program.id}")
                    success = await self.hass.async_add_executor_job(
                        self._hub.stop_program,
                        self._device.pentair_device_id,
                        program.id
                    )
                    if not success:
                        _LOGGER.error(f"Failed to stop pump program {program.id}")
                        any_failed = True
            
            if any_failed:
                _LOGGER.error("Some programs failed to stop - pump may still be running")
                # Don't update state if we failed to stop
                return
            
            # Update state only if all stops succeeded
            self._attr_percentage = 0
            self._attr_is_on = False
            self._attr_preset_mode = "off"
            
            # Force status update
            await self.hass.async_add_executor_job(
                self._hub.update_pentair_devices_status
            )
            
            self.async_write_ha_state()
            
        except Exception as e:
            _LOGGER.error(f"Error turning off pump: {e}")
    
    def _update_preset_mode(self, speed: int) -> None:
        """Update preset mode based on speed."""
        if speed >= 100:
            self._attr_preset_mode = "max"
        elif speed >= 75:
            self._attr_preset_mode = "high"
        elif speed >= 50:
            self._attr_preset_mode = "medium"
        elif speed >= 30:
            self._attr_preset_mode = "low"
        else:
            self._attr_preset_mode = "off"
    
    def _update_state_from_device(self) -> None:
        """Update entity state from device programs."""
        # Check which program is running using the actual mapped programs
        pump_running = False
        
        if DEBUG_INFO:
            running_programs = [p.id for p in self._device.programs if p.running]
            if running_programs:
                _LOGGER.debug(f"Running programs: {running_programs}")
        
        for program in self._device.programs:
            if program.running:
                if program.id in self._program_to_speed:
                    # This is a pump speed program
                    speed = self._program_to_speed[program.id]
                    self._attr_percentage = speed
                    self._attr_is_on = True
                    self._update_preset_mode(speed)
                    pump_running = True
                    if DEBUG_INFO:
                        _LOGGER.debug(f"Pump running program {program.id} ({program.name}) at {speed}%")
                    break  # Only one pump program should be active
                else:
                    if DEBUG_INFO:
                        _LOGGER.debug(f"Program {program.id} ({program.name}) is running but is not a pump speed program")
        
        if not pump_running:
            # No pump speed programs running
            self._attr_percentage = 0
            self._attr_is_on = False
            self._attr_preset_mode = "off"
            if DEBUG_INFO:
                _LOGGER.debug("No pump speed programs running - pump is OFF")
    
    async def _notify_safety_override(self, requested: int, actual: int) -> None:
        """Notify user when speed is adjusted for safety."""
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Pool Pump Safety Override",
                "message": f"Pool pump speed adjusted for heater safety.\n"
                          f"Requested: {requested}%\n"
                          f"Set to: {actual}% (minimum for heater operation)\n"
                          f"Turn off heater to use lower speeds.",
                "notification_id": "pentair_pump_safety"
            }
        )
    
    def update_heater_state(self, heater_on: bool) -> None:
        """Update heater state for safety checks."""
        _LOGGER.info(f"Heater state updated: {'ON' if heater_on else 'OFF'}")
        self._heater_on = heater_on
        
        # If heater just turned on and pump is below 50%, force increase
        if heater_on and 0 < self._attr_percentage < 50:
            _LOGGER.info("Heater turned on - increasing pump speed to minimum 50%")
            asyncio.create_task(self.async_set_percentage(50))
    
    async def async_added_to_hass(self) -> None:
        """When entity is added to hass, start polling."""
        await super().async_added_to_hass()
        
        # Schedule periodic updates every 30 seconds
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._async_scheduled_update,
            SCAN_INTERVAL
        )
        _LOGGER.info(f"Started polling for {self._attr_name} every {SCAN_INTERVAL.total_seconds()} seconds")
    
    async def async_will_remove_from_hass(self) -> None:
        """When entity is removed from hass, stop polling."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        await super().async_will_remove_from_hass()
    
    async def _async_scheduled_update(self, now=None) -> None:
        """Update entity state on schedule."""
        try:
            if DEBUG_INFO:
                _LOGGER.debug(f"Scheduled update for {self._attr_name}")
            
            # Update device status from API
            await self.hass.async_add_executor_job(
                self._hub.update_pentair_devices_status
            )
            
            # Update our state from the device
            self._update_state_from_device()
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"Error during scheduled update: {e}")