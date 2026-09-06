"""Config flow for the App Store Connect integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import AscApi, AscApiError, AscAuthError
from .const import (
    ASC_KEYS_URL,
    CONF_ISSUER_ID,
    CONF_KEY_ID,
    CONF_PRIVATE_KEY,
    CONF_SCAN_INTERVAL,
    CONF_VENDOR_NUMBER,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_VENDOR_NUMBER,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .jwt import JwtError, create_asc_jwt, normalise_pem

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KEY_ID): TextSelector(),
        vol.Required(CONF_ISSUER_ID): TextSelector(),
        vol.Required(CONF_PRIVATE_KEY): TextSelector(
            TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_VENDOR_NUMBER, default=DEFAULT_VENDOR_NUMBER): TextSelector(),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KEY_ID): TextSelector(),
        vol.Required(CONF_ISSUER_ID): TextSelector(),
        vol.Required(CONF_PRIVATE_KEY): TextSelector(
            TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
        ),
    }
)


class AscConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one App Store Connect vendor per config entry."""

    VERSION = 1

    async def _async_validate(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, str] | None:
        """Mint a JWT and list apps so a bad key is caught in the form."""
        key_id = user_input[CONF_KEY_ID].strip()
        issuer_id = user_input[CONF_ISSUER_ID].strip()
        private_key = normalise_pem(user_input[CONF_PRIVATE_KEY])
        vendor_number = user_input[CONF_VENDOR_NUMBER].strip()

        if not key_id:
            errors[CONF_KEY_ID] = "invalid_auth"
            return None
        if not issuer_id:
            errors[CONF_ISSUER_ID] = "invalid_auth"
            return None
        if not vendor_number:
            errors[CONF_VENDOR_NUMBER] = "invalid_vendor"
            return None

        try:
            create_asc_jwt(
                key_id=key_id,
                issuer_id=issuer_id,
                private_key_pem=private_key,
            )
        except JwtError:
            errors[CONF_PRIVATE_KEY] = "invalid_key"
            return None

        api = AscApi(
            async_get_clientsession(self.hass),
            key_id=key_id,
            issuer_id=issuer_id,
            private_key=private_key,
            vendor_number=vendor_number,
        )

        try:
            await api.async_list_apps()
        except AscAuthError:
            errors["base"] = "invalid_auth"
        except AscApiError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error validating the App Store Connect key")
            errors["base"] = "unknown"
        else:
            return {
                CONF_KEY_ID: key_id,
                CONF_ISSUER_ID: issuer_id,
                CONF_PRIVATE_KEY: private_key,
                CONF_VENDOR_NUMBER: vendor_number,
            }

        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the API key and confirm it works."""
        errors: dict[str, str] = {}

        if (
            user_input is not None
            and (validated := await self._async_validate(user_input, errors))
            is not None
        ):
            await self.async_set_unique_id(validated[CONF_VENDOR_NUMBER])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="App Store Connect",
                data=validated,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"keys_url": ASC_KEYS_URL},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start over when the stored key stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Swap in a fresh key without losing the entry's history."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            payload = {
                **user_input,
                CONF_VENDOR_NUMBER: reauth_entry.data[CONF_VENDOR_NUMBER],
            }
            if (validated := await self._async_validate(payload, errors)) is not None:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_KEY_ID: validated[CONF_KEY_ID],
                        CONF_ISSUER_ID: validated[CONF_ISSUER_ID],
                        CONF_PRIVATE_KEY: validated[CONF_PRIVATE_KEY],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"keys_url": ASC_KEYS_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return AscOptionsFlow()


class AscOptionsFlow(OptionsFlow):
    """Tune polling after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=MAX_SCAN_INTERVAL_MINUTES,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="minutes",
                        )
                    ),
                }
            ),
        )
