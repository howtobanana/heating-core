"""Einrichtung über die Oberfläche."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .const import CONF_MANUFACTURER, DOMAIN, MANUFACTURERS


class HeatingCoreConfigFlow(ConfigFlow, domain=DOMAIN):
    """Eine Anlage (ein Haus, ein Hersteller) je Eintrag."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_NAME].strip().lower())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MANUFACTURER, default="vaillant"): SelectSelector(
                    SelectSelectorConfig(
                        options=MANUFACTURERS, translation_key=CONF_MANUFACTURER
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
