"""Data update coordinator for Pentair Cloud integration."""
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .pentaircloud_modified import PentairCloudHub

_LOGGER = logging.getLogger(__name__)

# How often to poll the Pentair API for updates
SCAN_INTERVAL = timedelta(seconds=30)


class PentairDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Pentair data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: PentairCloudHub,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.hub = hub

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from Pentair API."""
        try:
            # Update device status from the API
            await self.hass.async_add_executor_job(
                self.hub.update_pentair_devices_status
            )
            
            # Return device data
            devices = self.hub.get_devices()
            data = {}
            for device in devices:
                data[device.pentair_device_id] = {
                    "programs": {
                        p.id: {
                            "running": p.running,
                            "control_value": p.control_value,
                            "name": p.name,
                            "program_type": p.program_type,
                        }
                        for p in device.programs
                    },
                    "nickname": device.nickname,
                }
            
            _LOGGER.debug(f"Updated Pentair data for {len(devices)} devices")
            return data
            
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Pentair API: {err}")