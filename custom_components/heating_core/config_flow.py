"""Einrichtung über die Oberfläche: Anlage, Optionen, Heizkreise und Räume (Subentries)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import (
    CONF_MANUFACTURER,
    DEFAULTS,
    DOMAIN,
    F_CIRCUIT,
    F_CLIMATE,
    F_COMFORT,
    F_COMFORT_ENTITY,
    F_HUMIDITY,
    F_PUMP,
    F_SOURCE_OFF,
    F_SOURCE_ON,
    F_SOURCE_TEMP,
    F_VALVE_DELAY,
    F_VALVES,
    KIND_FLOOR_EXTERNAL,
    ROLE_FLOOR_ZONE,
    F_KIND,
    F_MASTER,
    F_OFFSET,
    F_PRESENCE,
    F_ROLE,
    F_SCHEDULE,
    F_TEMP,
    F_WINDOW,
    MANUFACTURERS,
    OPT_ACTIVATION_MIN,
    OPT_AWAY_ENTITIES,
    OPT_AWAY_TEMP,
    OPT_BOOST_AMOUNT,
    OPT_BOOST_ENABLED,
    OPT_BOOST_THRESHOLD,
    OPT_BUDGET,
    OPT_DEACTIVATION_MIN,
    OPT_ECO,
    OPT_GUEST_ENTITY,
    OPT_HUMIDITY_DROP,
    OPT_HUMIDITY_ENABLED,
    OPT_HYSTERESIS,
    OPT_MIN_TRV,
    OPT_OUTDOOR_SENSOR,
    OPT_PRE_HEAT_TIMEOUT_MIN,
    OPT_SUMMER_ENTITY,
    OPT_WEATHER_ENABLED,
    OPT_WEATHER_ZONE1,
    OPT_WEATHER_ZONE2,
    OPT_WEATHER_ZONE3,
    OPT_WINDOW_DELAY_S,
    OPT_WINDOW_SETTLE_S,
    SUB_CIRCUIT,
    SUB_ROOM,
)


def _temp(lo: float, hi: float, step: float = 0.5) -> sel.NumberSelector:
    return sel.NumberSelector(sel.NumberSelectorConfig(min=lo, max=hi, step=step, unit_of_measurement="°C", mode=sel.NumberSelectorMode.BOX))


def _num(lo: float, hi: float, step: float = 1, unit: str | None = None) -> sel.NumberSelector:
    extra = {"unit_of_measurement": unit} if unit else {}  # None lehnt HA ab (Optionen öffneten mit 400)
    return sel.NumberSelector(sel.NumberSelectorConfig(min=lo, max=hi, step=step, mode=sel.NumberSelectorMode.BOX, **extra))


def _entity(domain: str | list[str], multiple: bool = False, device_class: str | None = None) -> sel.EntitySelector:
    return sel.EntitySelector(sel.EntitySelectorConfig(domain=domain, multiple=multiple, device_class=device_class))


def _opt(key: str, data: dict) -> Any:
    """Optionales Feld: Default nur setzen, wenn ein Wert vorhanden ist."""
    return vol.Optional(key, description={"suggested_value": data.get(key)})


class HeatingCoreConfigFlow(ConfigFlow, domain=DOMAIN):
    """Eine Anlage (ein Haus, ein Hersteller) je Eintrag."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_NAME].strip().lower())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MANUFACTURER, default="vaillant"): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=MANUFACTURERS, translation_key=CONF_MANUFACTURER)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeatingOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUB_CIRCUIT: CircuitFlow, SUB_ROOM: RoomFlow}


class HeatingOptionsFlow(OptionsFlow):
    """Globale Werte der Anlage."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = {**DEFAULTS, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(OPT_ECO, default=o[OPT_ECO]): _temp(15, 23),
                vol.Required(OPT_AWAY_TEMP, default=o[OPT_AWAY_TEMP]): _temp(10, 20),
                vol.Required(OPT_MIN_TRV, default=o[OPT_MIN_TRV]): _temp(5, 15),
                vol.Required(OPT_HYSTERESIS, default=o[OPT_HYSTERESIS]): _temp(0.1, 2, 0.1),
                vol.Required(OPT_BUDGET, default=o[OPT_BUDGET]): _num(5, 20),
                vol.Required(OPT_ACTIVATION_MIN, default=o[OPT_ACTIVATION_MIN]): _num(0, 30, 1, "min"),
                vol.Required(OPT_DEACTIVATION_MIN, default=o[OPT_DEACTIVATION_MIN]): _num(5, 240, 5, "min"),
                vol.Required(OPT_WINDOW_DELAY_S, default=o[OPT_WINDOW_DELAY_S]): _num(10, 600, 5, "s"),
                vol.Required(OPT_WINDOW_SETTLE_S, default=o[OPT_WINDOW_SETTLE_S]): _num(0, 1800, 10, "s"),
                vol.Required(OPT_PRE_HEAT_TIMEOUT_MIN, default=o[OPT_PRE_HEAT_TIMEOUT_MIN]): _num(15, 480, 15, "min"),
                vol.Optional(OPT_AWAY_ENTITIES, default=o[OPT_AWAY_ENTITIES]): _entity(["input_boolean", "binary_sensor", "switch"], multiple=True),
                _opt(OPT_GUEST_ENTITY, o): _entity(["input_boolean", "binary_sensor", "switch"]),
                _opt(OPT_SUMMER_ENTITY, o): _entity(["input_boolean", "binary_sensor"]),
                _opt(OPT_OUTDOOR_SENSOR, o): _entity("sensor", device_class="temperature"),
                vol.Required(OPT_WEATHER_ENABLED, default=o[OPT_WEATHER_ENABLED]): bool,
                vol.Required(OPT_WEATHER_ZONE1, default=o[OPT_WEATHER_ZONE1]): _temp(0, 5),
                vol.Required(OPT_WEATHER_ZONE2, default=o[OPT_WEATHER_ZONE2]): _temp(0, 5),
                vol.Required(OPT_WEATHER_ZONE3, default=o[OPT_WEATHER_ZONE3]): _temp(0, 5),
                vol.Required(OPT_BOOST_ENABLED, default=o[OPT_BOOST_ENABLED]): bool,
                vol.Required(OPT_BOOST_AMOUNT, default=o[OPT_BOOST_AMOUNT]): _temp(0.5, 3),
                vol.Required(OPT_BOOST_THRESHOLD, default=o[OPT_BOOST_THRESHOLD]): _temp(0.5, 3),
                vol.Required(OPT_HUMIDITY_ENABLED, default=o[OPT_HUMIDITY_ENABLED]): bool,
                vol.Required(OPT_HUMIDITY_DROP, default=o[OPT_HUMIDITY_DROP]): _temp(0.5, 2),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _room_fields(d: dict) -> dict:
    return {
        _opt(F_COMFORT_ENTITY, d): _entity("input_number"),
        _opt(F_PRESENCE, d): _entity("binary_sensor", multiple=True),
        _opt(F_SCHEDULE, d): _entity("schedule"),
        _opt(F_WINDOW, d): _entity("binary_sensor"),
        _opt(F_TEMP, d): _entity("sensor", device_class="temperature"),
    }


class _BaseSubFlow(ConfigSubentryFlow):
    def _schema(self, d: dict) -> vol.Schema:
        raise NotImplementedError

    def _errors(self, data: dict) -> dict[str, str]:
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._errors(user_input)
            if not errors:
                title = user_input.pop(CONF_NAME)
                return self.async_create_entry(title=title, data=user_input)
        return self.async_show_form(step_id="user", data_schema=self._schema(user_input or {}), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._errors(user_input)
            if not errors:
                title = user_input.pop(CONF_NAME)
                return self.async_update_and_abort(self._get_entry(), sub, title=title, data=user_input)
        data = user_input or {**sub.data, CONF_NAME: sub.title}
        return self.async_show_form(step_id="reconfigure", data_schema=self._schema(data), errors=errors)


class CircuitFlow(_BaseSubFlow):
    """Heizkreis mit Master-Raum (Therme-Zone, Ökofen-Heizkreis …)."""

    def _schema(self, d: dict) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): str,
                vol.Required(F_KIND, default=d.get(F_KIND, "radiator")): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=["radiator", "floor", KIND_FLOOR_EXTERNAL], translation_key=F_KIND)
                ),
                _opt(F_MASTER, d): _entity("climate"),
                vol.Required(F_COMFORT, default=d.get(F_COMFORT, 21.0)): _temp(16, 25),
                **_room_fields(d),
                _opt(F_HUMIDITY, d): _entity("sensor", device_class="humidity"),
                # nur „Fußboden extern“: eigene Pumpe, Freigabe über Kesseltemperatur
                _opt(F_PUMP, d): _entity(["switch", "input_boolean"]),
                _opt(F_SOURCE_TEMP, d): _entity("sensor"),
                vol.Required(F_SOURCE_ON, default=d.get(F_SOURCE_ON, 50.0)): _num(20, 90, 1, "°C"),
                vol.Required(F_SOURCE_OFF, default=d.get(F_SOURCE_OFF, 45.0)): _num(20, 90, 1, "°C"),
                vol.Required(F_VALVE_DELAY, default=d.get(F_VALVE_DELAY, 180)): _num(0, 900, 10, "s"),
            }
        )

    def _errors(self, data: dict) -> dict[str, str]:
        if data.get(F_KIND) == KIND_FLOOR_EXTERNAL:
            if not data.get(F_PUMP) or not data.get(F_SOURCE_TEMP):
                return {"base": "floor_needs_pump"}
            if float(data[F_SOURCE_OFF]) >= float(data[F_SOURCE_ON]):
                return {"base": "source_hysteresis"}
        elif not data.get(F_MASTER):
            return {"base": "master_required"}
        return {}


class RoomFlow(_BaseSubFlow):
    """Raum mit eigenem TRV (isoliert) oder Follower des Heizkreises."""

    def _schema(self, d: dict) -> vol.Schema:
        circuits = [
            sel.SelectOptionDict(value=sid, label=sub.title)
            for sid, sub in self._get_entry().subentries.items()
            if sub.subentry_type == SUB_CIRCUIT
        ]
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): str,
                vol.Required(F_CIRCUIT, default=d.get(F_CIRCUIT)) if d.get(F_CIRCUIT) else vol.Required(F_CIRCUIT): sel.SelectSelector(sel.SelectSelectorConfig(options=circuits)),
                vol.Required(F_ROLE, default=d.get(F_ROLE, "isolated")): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=["isolated", "follower", ROLE_FLOOR_ZONE], translation_key=F_ROLE)
                ),
                _opt(F_CLIMATE, d): _entity("climate"),
                _opt(F_VALVES, d): _entity(["switch", "input_boolean"], multiple=True),
                vol.Required(F_COMFORT, default=d.get(F_COMFORT, 21.0)): _temp(16, 25),
                vol.Required(F_OFFSET, default=d.get(F_OFFSET, -2.0)): _temp(-3, 2),
                **_room_fields(d),
            }
        )

    def _errors(self, data: dict) -> dict[str, str]:
        if data.get(F_ROLE) == ROLE_FLOOR_ZONE:
            return {} if data.get(F_VALVES) else {"base": "zone_needs_valves"}
        return {} if data.get(F_CLIMATE) else {"base": "climate_required"}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not any(s.subentry_type == SUB_CIRCUIT for s in self._get_entry().subentries.values()):
            return self.async_abort(reason="no_circuit")
        return await super().async_step_user(user_input)
