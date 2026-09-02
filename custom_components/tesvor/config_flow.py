"""Config flow for the Tesvor Home integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_PHONE_CODE,
    DEFAULT_COMMAND_DELAY,
    DEFAULT_PHONE_CODE,
    DEFAULT_RETRY_COUNT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_USERNAME,
    TESVOR_APP,
)
from .data_center_manager import get_data_center_manager
from .tesvorhome.config import Credentials, DeviceConfig, MQTTConfig, RestConfig, TesvorConfig
from .tesvorhome.device.vacuum import TesvorVacuum

_LOGGER = logging.getLogger(__name__)


class TesvorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Tesvor Home config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect credentials and validate them against Tesvor Home."""
        errors: dict[str, str] = {}

        if user_input is not None:
            phone_code = user_input[CONF_PHONE_CODE].lstrip("+")
            manager = get_data_center_manager(self.hass)
            data_center = await self.hass.async_add_executor_job(
                manager.get_data_center_by_phone_code,
                phone_code,
                self.hass.config.language,
            )

            if data_center is None:
                errors["base"] = "no_data_center"
            else:
                config = TesvorConfig(
                    rest=RestConfig(
                        base_url=data_center["rest_url"],
                        app_key=TESVOR_APP["app_key"],
                        app_secret=TESVOR_APP["app_secret"],
                        package_name=TESVOR_APP["package_name"],
                        source=TESVOR_APP["source"],
                        reg_id="",
                        country=data_center["country_code"],
                        phone_code=phone_code,
                        app_version=TESVOR_APP["app_version"],
                        test_flag=TESVOR_APP["test_flag"],
                        user_agent="okhttp/4.9.1",
                    ),
                    mqtt=MQTTConfig(
                        host=data_center["mqtt_host"],
                        port=data_center.get("mqtt_port", MQTT_PORT),
                        username=MQTT_USERNAME,
                        password=MQTT_PASSWORD,
                    ),
                    credentials=Credentials(
                        email=user_input[CONF_EMAIL],
                        password=user_input[CONF_PASSWORD],
                    ),
                    device=DeviceConfig(
                        default_timeout=DEFAULT_TIMEOUT,
                        command_delay=DEFAULT_COMMAND_DELAY,
                        retry_count=DEFAULT_RETRY_COUNT,
                    ),
                )
                vacuum = TesvorVacuum(config)
                vacuum._test_mode = True

                try:
                    await vacuum.initialize()
                except (ConnectionError, OSError, TimeoutError) as err:
                    _LOGGER.error("Could not connect to Tesvor Home: %s", err)
                    errors["base"] = "cannot_connect"
                except Exception as err:
                    _LOGGER.error("Tesvor Home authentication failed: %s", err)
                    errors["base"] = "invalid_auth"
                else:
                    device_mac = vacuum.info.mac if vacuum.info is not None else ""
                    device_id = vacuum.info.device_id if vacuum.info is not None else ""
                    await self.async_set_unique_id(device_mac)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title="Tesvor Vacuum",
                        data={
                            CONF_EMAIL: user_input[CONF_EMAIL],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_PHONE_CODE: phone_code,
                            "device_mac": device_mac,
                            "device_id": device_id,
                            "rest_url": data_center["rest_url"],
                            "mqtt_host": data_center["mqtt_host"],
                            "mqtt_port": data_center.get("mqtt_port", MQTT_PORT),
                            "country_code": data_center["country_code"],
                            "country_name": data_center["country_name"],
                        },
                    )
                finally:
                    await vacuum.disconnect()
                    vacuum._test_mode = False

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PHONE_CODE, default=DEFAULT_PHONE_CODE): str,
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"example_code": "+49 or 49"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return TesvorOptionsFlow(config_entry)


class TesvorOptionsFlow(config_entries.OptionsFlow):
    """Allow changing the Tesvor Home data-center country."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage integration options."""
        current_phone_code = self.config_entry.data.get(
            CONF_PHONE_CODE, DEFAULT_PHONE_CODE
        )

        if user_input is not None:
            phone_code = user_input[CONF_PHONE_CODE].lstrip("+")
            manager = get_data_center_manager(self.hass)
            data_center = await self.hass.async_add_executor_job(
                manager.get_data_center_by_phone_code,
                phone_code,
                self.hass.config.language,
            )

            if data_center is None:
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema(
                        {vol.Required(CONF_PHONE_CODE, default=phone_code): str}
                    ),
                    errors={"base": "no_data_center"},
                )

            new_data = dict(self.config_entry.data)
            new_data.update(
                {
                    CONF_PHONE_CODE: phone_code,
                    "rest_url": data_center["rest_url"],
                    "mqtt_host": data_center["mqtt_host"],
                    "mqtt_port": data_center.get("mqtt_port", MQTT_PORT),
                    "country_code": data_center["country_code"],
                    "country_name": data_center["country_name"],
                }
            )
            new_data.pop("app_type", None)
            new_data.pop("region", None)
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_PHONE_CODE, default=current_phone_code): str}
            ),
            description_placeholders={
                "device_name": "Tesvor Vacuum",
                "device_mac": self.config_entry.data.get("device_mac", "Unknown"),
                "email": self.config_entry.data.get(CONF_EMAIL, ""),
            },
        )
