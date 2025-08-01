"""Config flow for PentairCloud integration."""
from __future__ import annotations

import logging
import asyncio
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# TODO adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)

# Default schema - will be replaced with dynamic program list
DEFAULT_PROGRAMS_SCHEMA = vol.Schema(
    {
        vol.Required("speed_low", default="Program 3"): str,
        vol.Required("speed_medium", default="Program 2"): str,
        vol.Required("speed_high", default="Program 4"): str,
        vol.Required("speed_max", default="Program 1"): str,
        vol.Required("relay_lights", default="Program 5"): str,
        vol.Required("relay_heater", default="Program 6"): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # Import here to avoid blocking the event loop
    from .pentaircloud_modified import PentairCloudHub
    
    # TODO validate the data can be used to set up a connection.

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    hub = PentairCloudHub(_LOGGER)
    if not await hass.async_add_executor_job(
        hub.authenticate, data["username"], data["password"]
    ):
        raise InvalidAuth

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    return {"title": "PentairCloud"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PentairCloud."""

    VERSION = 2  # Increment version for new options

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}
        self._hub = None
        self._devices = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
            # Store credentials and hub for next step
            self._data = user_input
            from .pentaircloud_modified import PentairCloudHub
            self._hub = PentairCloudHub(_LOGGER)
            await self.hass.async_add_executor_job(
                self._hub.authenticate, user_input["username"], user_input["password"]
            )
            await self.hass.async_add_executor_job(self._hub.populate_AWS_and_data_fields)
            self._devices = await self.hass.async_add_executor_job(self._hub.get_devices)
            # Move to program mapping configuration
            return await self.async_step_programs()
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_programs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle program mapping configuration."""
        if user_input is not None:
            # Convert program names to IDs
            program_map = self._get_program_map()
            mapped_data = {
                "speed_low": program_map.get(user_input["speed_low"], 3),
                "speed_medium": program_map.get(user_input["speed_medium"], 2),
                "speed_high": program_map.get(user_input["speed_high"], 4),
                "speed_max": program_map.get(user_input["speed_max"], 1),
                "relay_lights": program_map.get(user_input["relay_lights"], 5),
                "relay_heater": program_map.get(user_input["relay_heater"], 6),
            }
            # Add temperature sensor if selected
            if user_input.get("temperature_sensor"):
                mapped_data["temperature_sensor"] = user_input["temperature_sensor"]
                
            self._data.update(mapped_data)
            return self.async_create_entry(title="PentairCloud", data=self._data)

        # Build dynamic schema with actual program names
        schema = self._build_programs_schema()
        
        return self.async_show_form(
            step_id="programs",
            data_schema=schema,
            description_placeholders={
                "info": "Select which programs control each function"
            }
        )
    
    def _get_program_map(self) -> dict[str, int]:
        """Get mapping of program names to IDs (manual programs only)."""
        program_map = {}
        if self._devices:
            device = self._devices[0]
            for program in device.programs:
                # Only include manual programs (type 2)
                if program.program_type == 2:
                    program_map[program.name] = program.id
        return program_map
    
    def _build_programs_schema(self) -> vol.Schema:
        """Build schema with actual program names (manual programs only)."""
        if not self._devices:
            return DEFAULT_PROGRAMS_SCHEMA
            
        device = self._devices[0]
        # Only include manual programs (type 2)
        program_names = [p.name for p in device.programs if p.program_type == 2]
        
        if not program_names:
            return DEFAULT_PROGRAMS_SCHEMA
            
        return vol.Schema(
            {
                vol.Required("speed_low", default=program_names[2] if len(program_names) > 2 else program_names[0]): vol.In(program_names),
                vol.Required("speed_medium", default=program_names[1] if len(program_names) > 1 else program_names[0]): vol.In(program_names),
                vol.Required("speed_high", default=program_names[3] if len(program_names) > 3 else program_names[0]): vol.In(program_names),
                vol.Required("speed_max", default=program_names[0]): vol.In(program_names),
                vol.Required("relay_lights", default=program_names[4] if len(program_names) > 4 else program_names[0]): vol.In(program_names),
                vol.Required("relay_heater", default=program_names[5] if len(program_names) > 5 else program_names[0]): vol.In(program_names),
                vol.Optional("temperature_sensor"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="temperature"
                    )
                ),
            }
        )

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for PentairCloud."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        # Don't store config_entry - access it via self.config_entry property
        self._program_map = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Convert program names back to IDs
            mapped_data = {
                "speed_low": self._program_map.get(user_input["speed_low"], 3),
                "speed_medium": self._program_map.get(user_input["speed_medium"], 2),
                "speed_high": self._program_map.get(user_input["speed_high"], 4),
                "speed_max": self._program_map.get(user_input["speed_max"], 1),
                "relay_lights": self._program_map.get(user_input["relay_lights"], 5),
                "relay_heater": self._program_map.get(user_input["relay_heater"], 6),
            }
            # Add temperature sensor if selected
            if "temperature_sensor" in user_input:
                mapped_data["temperature_sensor"] = user_input["temperature_sensor"]
                
            # Update config entry with new program mappings
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **mapped_data}
            )
            return self.async_create_entry(title="", data={})

        # Get hub and devices to show program names
        from .pentaircloud_modified import PentairCloudHub
        hub = PentairCloudHub(_LOGGER)
        await self.hass.async_add_executor_job(
            hub.authenticate, 
            self.config_entry.data["username"], 
            self.config_entry.data["password"]
        )
        await self.hass.async_add_executor_job(hub.populate_AWS_and_data_fields)
        devices = await self.hass.async_add_executor_job(hub.get_devices)
        
        if not devices:
            return self.async_abort(reason="no_devices")
            
        device = devices[0]
        # Only include manual programs (type 2)
        manual_programs = [p for p in device.programs if p.program_type == 2]
        program_names = [p.name for p in manual_programs]
        program_map = {p.name: p.id for p in manual_programs}
        
        # Reverse map current IDs to names
        current_data = self.config_entry.data
        reverse_map = {v: k for k, v in program_map.items()}
        
        schema = vol.Schema(
            {
                vol.Required(
                    "speed_low", 
                    default=reverse_map.get(current_data.get("speed_low", 3), program_names[0])
                ): vol.In(program_names),
                vol.Required(
                    "speed_medium", 
                    default=reverse_map.get(current_data.get("speed_medium", 2), program_names[0])
                ): vol.In(program_names),
                vol.Required(
                    "speed_high", 
                    default=reverse_map.get(current_data.get("speed_high", 4), program_names[0])
                ): vol.In(program_names),
                vol.Required(
                    "speed_max", 
                    default=reverse_map.get(current_data.get("speed_max", 1), program_names[0])
                ): vol.In(program_names),
                vol.Required(
                    "relay_lights", 
                    default=reverse_map.get(current_data.get("relay_lights", 5), program_names[0])
                ): vol.In(program_names),
                vol.Required(
                    "relay_heater", 
                    default=reverse_map.get(current_data.get("relay_heater", 6), program_names[0])
                ): vol.In(program_names),
                vol.Optional(
                    "temperature_sensor",
                    default=current_data.get("temperature_sensor")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="temperature"
                    )
                ),
            }
        )
        
        # Store program map for conversion
        self._program_map = program_map

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "info": "Select which programs control each function"
            }
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
