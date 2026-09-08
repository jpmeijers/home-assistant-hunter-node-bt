"""Config flow for Hunter NODE-BT."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import bleak
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS, establish_connection
import voluptuous as vol

if TYPE_CHECKING:
    from bleak import BleakClient

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_PIN,
    CONF_RUN_TIME,
    DEFAULT_RUN_TIME,
    DOMAIN,
    MAX_RUN_TIME,
    MESSAGE_SERVICE,
    MIN_RUN_TIME,
)
from .protocol import (
    HunterNodeAuthenticationError,
    HunterNodeController,
    HunterNodeError,
)

CONNECT_EXCEPTIONS = (*BLEAK_RETRY_EXCEPTIONS, HunterNodeError)
_LOGGER = logging.getLogger(__name__)


class HunterNodeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Hunter NODE-BT config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HunterNodeOptionsFlow:
        """Return the flow for editable controller options."""
        return HunterNodeOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle automatic Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured(
            updates={CONF_ADDRESS: discovery_info.address}
        )
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered controller and collect its PIN."""
        assert self._discovery is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            return await self._async_create_for_device(
                self._discovery, user_input, errors, "bluetooth_confirm"
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=self._details_schema(),
            description_placeholders=self.context["title_placeholders"],
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose a currently discovered controller."""
        errors: dict[str, str] = {}
        if user_input is not None:
            discovery = self._discovered[user_input[CONF_ADDRESS]]
            await self.async_set_unique_id(discovery.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self._async_create_for_device(
                discovery, user_input, errors, "user"
            )

        configured = self._async_current_ids(include_ignore=False)
        for discovery in async_discovered_service_info(self.hass, connectable=True):
            if (
                discovery.address not in configured
                and MESSAGE_SERVICE in {uuid.lower() for uuid in discovery.service_uuids}
            ):
                self._discovered[discovery.address] = discovery
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            item.address: f"{item.name} ({item.address})"
                            for item in self._discovered.values()
                        }
                    ),
                    **self._details_schema().schema,
                }
            ),
            errors=errors,
        )

    async def _async_create_for_device(
        self,
        discovery: BluetoothServiceInfoBleak,
        user_input: dict[str, Any],
        errors: dict[str, str],
        step_id: str,
    ) -> ConfigFlowResult:
        pin = str(user_input[CONF_PIN])
        if len(pin) != 4 or not pin.isascii() or not pin.isdigit():
            errors[CONF_PIN] = "invalid_pin"
            return self._show_details_form(step_id, user_input, errors)
        async def connect() -> BleakClient:
            return await establish_connection(
                bleak.BleakClient,
                discovery.device,
                discovery.name,
                max_attempts=3,
            )

        controller = HunterNodeController(connect, int(pin))
        try:
            data = await controller.read_data()
        except HunterNodeAuthenticationError:
            errors["base"] = "invalid_auth"
        except CONNECT_EXCEPTIONS:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while setting up Hunter NODE-BT")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=data.name,
                data={
                    CONF_ADDRESS: discovery.address,
                    CONF_PIN: pin,
                },
            )

        return self._show_details_form(step_id, user_input, errors)

    def _show_details_form(
        self,
        step_id: str,
        user_input: dict[str, Any],
        errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Show a setup form again while preserving submitted values."""
        schema = self.add_suggested_values_to_schema(
            self._details_schema(), user_input
        )
        if step_id == "user":
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_ADDRESS, default=user_input[CONF_ADDRESS]
                    ): vol.In(
                        {
                            item.address: f"{item.name} ({item.address})"
                            for item in self._discovered.values()
                        }
                    ),
                    **schema.schema,
                }
            )
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders=(
                self.context.get("title_placeholders")
                if step_id == "bluetooth_confirm"
                else None
            ),
            errors=errors,
        )

    @staticmethod
    def _details_schema() -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_PIN, default="0000"): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                )
            }
        )


class HunterNodeOptionsFlow(OptionsFlow):
    """Edit Hunter NODE-BT behavior after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the default duration used when opening a valve."""
        errors: dict[str, str] = {}
        if user_input is not None:
            run_time = float(user_input[CONF_RUN_TIME])
            if run_time.is_integer():
                return self.async_create_entry(
                    title="", data={CONF_RUN_TIME: int(run_time)}
                )
            errors[CONF_RUN_TIME] = "invalid_run_time"

        current_run_time = self.config_entry.options.get(
            CONF_RUN_TIME,
            self.config_entry.data.get(CONF_RUN_TIME, DEFAULT_RUN_TIME),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self._run_time_schema(current_run_time),
            errors=errors,
        )

    @staticmethod
    def _run_time_schema(default: int) -> vol.Schema:
        """Return the serializable default-duration schema."""
        return vol.Schema(
            {
                vol.Required(CONF_RUN_TIME, default=default): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_RUN_TIME,
                        max=MAX_RUN_TIME,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement=UnitOfTime.SECONDS,
                    )
                )
            }
        )
