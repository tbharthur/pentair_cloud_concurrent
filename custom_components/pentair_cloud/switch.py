"""Switch platform for Pentair.

Standalone relay switches are intentionally not created. The heater relay is
owned by the pool thermostat, and the light relay is exposed as a light entity.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pentair relay switches."""
    _LOGGER.info("No standalone Pentair switch entities configured")
    async_add_entities([], update_before_add=False)
