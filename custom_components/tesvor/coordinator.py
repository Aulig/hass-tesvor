"""Data update coordinator for Tesvor."""

import logging
from datetime import timedelta, datetime
from typing import Any, Dict, Optional

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .tesvorhome.rest.async_client import TesvorRestError

_LOGGER = logging.getLogger(__name__)


class TesvorCoordinator(DataUpdateCoordinator):
    """Coordinator for Tesvor data updates."""

    def __init__(self, hass: HomeAssistant, vacuum, config_entry: Optional[ConfigEntry] = None):
        """Initialize with shared vacuum instance."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
            config_entry=config_entry,
        )
        self.vacuum = vacuum
        self.vacuum.coordinator = self
        self._device_id: Optional[int] = None
        self._device_name: str = "Tesvor Vacuum"
        self.mac_address: Optional[str] = None
        self._initialized = False
        self._rest_failures = 0
        self._last_rest_success: Optional[datetime] = None

        # References to cloud map entities
        self.cloud_maps_sensor = None
        self.cloud_map_select = None
        self.cloud_map_image = None

        # References to clean history entities
        self.clean_history_sensor = None
        self.clean_history_select = None
        self.clean_history_camera = None

    async def _async_setup(self):
        """Retry incomplete initialization on every scheduled coordinator update."""
        try:
            if not self.vacuum.is_initialized:
                await self.vacuum.initialize()
            self.vacuum.set_hass(self.hass)
            self._device_id = self.vacuum.info.device_id
            self.mac_address = self.vacuum.info.mac
            self._initialized = True
        except (aiohttp.ClientError, TimeoutError, ConnectionError, TesvorRestError) as err:
            self._initialized = False
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cloud_unavailable",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_update_data(self) -> Dict[str, Any]:
        """Poll cloud data without tearing down a working MQTT connection."""
        if not self._initialized or not self.vacuum.is_initialized:
            await self._async_setup()

        sensors = self.vacuum.state.sensors
        previous = self.data if self.data is not None else {}
        data = {
            # MQTT data remains independent of cloud statistics and authentication.
            "battery_level": sensors.battery,
            "status_code": sensors.status_code,
            "status_text": self._get_status_text(sensors),
            "online": self.vacuum.is_connected,
            "current_clean_time": sensors.clean_time_min,
            "current_clean_area": sensors.clean_area_m2,
            "fan_speed": sensors.fan_speed,
            "water_level": sensors.water_level,
            "clean_mode": sensors.clean_mode,
            "malfunction_code": sensors.malfunction_code,
            "consumables": sensors.consumables,
            # Retain real cloud values during outages instead of publishing zeros.
            "software_version": previous.get("software_version", "Unknown"),
            "mac_address": self.mac_address,
            "device_pid": self.vacuum.info.pid,
            "statistics": previous.get("statistics", {}),
            "last_clean": previous.get("last_clean", {}),
            "device_details": dict(previous.get("device_details", {
                "device_name": self.vacuum.info.name,
                "mac_address": self.mac_address,
                "device_id": self.device_id,
                "p_id": self.vacuum.info.pid,
            })),
        }

        try:
            devices = await self.vacuum.rest.get_devices()
            await self.vacuum.load_consumables()
            for device in devices:
                if device["deviceId"] == self.device_id:
                    data["software_version"] = device.get("softwareVersion", "Unknown")
                    data["device_details"].update({
                        "image_url": device.get("imageUrl"),
                        "software_version": device.get("softwareVersion", "Unknown"),
                        "proto_version": device.get("protoVersion"),
                    })
                    break

            total_stats = await self.vacuum.rest.get_clean_sum(self.device_id)
            if total_stats:
                data["statistics"] = {
                    "total_cleanings": total_stats.get("cleanNums", 0),
                    "total_clean_time": round(total_stats.get("cleanLength", 0) / 3600, 1),
                    "total_clean_area": round(total_stats.get("cleanArea", 0) / 10, 1),
                }

            records = await self.vacuum.rest.get_clean_records(self.device_id, 0, 1)
            if records:
                record = records[0]
                clean_time = None
                if clean_time_str := record.get("cleanTime"):
                    try:
                        naive_dt = datetime.strptime(clean_time_str, "%Y-%m-%d %H:%M:%S")
                        clean_time = dt_util.as_utc(naive_dt)
                    except (ValueError, TypeError) as err:
                        _LOGGER.warning("Error parsing time: %s", err)
                data["last_clean"] = {
                    "clean_time": clean_time,
                    "clean_duration": record.get("cleanLength", 0) // 60,
                    "clean_area": record.get("cleanArea", 0) / 10,
                    "finished": record.get("cleanFinishedFlag", False),
                }
        except (aiohttp.ClientError, TimeoutError, ConnectionError, TesvorRestError) as err:
            self._rest_failures += 1
            if self._rest_failures == 1:
                _LOGGER.warning("Cloud unavailable; will retry on the next update: %s", err)
            if not self.vacuum.is_connected:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="cloud_unavailable",
                    translation_placeholders={"error": str(err)},
                ) from err
        else:
            if self._rest_failures > 0:
                _LOGGER.info("Cloud connection recovered")
            self._rest_failures = 0
            self._last_rest_success = datetime.now()

        return data

    @property
    def rest_available(self) -> bool:
        """Whether background cloud requests should run on this update."""
        return self._initialized and self.vacuum.is_initialized and self._rest_failures == 0

    def _get_status_text(self, sensors) -> str:
        """Get combined status text with error details if needed."""
        if sensors.status_code == 13:  # Malfunction
            error_desc = sensors.malfunction_text or "Unknown error"
            return f"Malfunction: {error_desc}"
        return sensors.status_text or "Unknown"

    @property
    def rest_status(self) -> str:
        """REST connection status."""
        if self._rest_failures == 0 and self._last_rest_success:
            return f"OK (last success: {self._last_rest_success.strftime('%H:%M:%S')})"
        elif self._rest_failures > 0:
            return f"Problems ({self._rest_failures})"
        return "Not checked"

    @property
    def device_id(self) -> Optional[int]:
        """Return device ID."""
        return self._device_id

    @property
    def device_name(self) -> str:
        """Get device name."""
        if self.vacuum and self.vacuum.info and self.vacuum.info.name:
            if self.vacuum.info.name != "Unnamed device":
                return self.vacuum.info.name
        return self._device_name

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        device_name = "Tesvor Vacuum"
        if self.vacuum and self.vacuum.info:
            if self.vacuum.info.name and self.vacuum.info.name != "Unnamed device":
                device_name = self.vacuum.info.name

        return {
            "identifiers": {(DOMAIN, str(self._device_id))},
            "name": device_name,
            "manufacturer": "Tesvor",
            "model": device_name,
        }
