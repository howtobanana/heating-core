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
    F_HUMIDITY,
    F_HVAC_MODE,
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
    OPT_PRE_HEAT_LEAD,
    OPT_ROOM_DEMAND_DELTA,
    OPT_GUEST_ENTITY,
    OPT_HUMIDITY_DROP,
    OPT_HUMIDITY_ENABLED,
    OPT_HYSTERESIS,
    OPT_MIN_TRV,
    OPT_OUTDOOR_SENSOR,
    OPT_PRE_HEAT_TIMEOUT_MIN,
    OPT_NOTIFY_DEVICES,
    OPT_PUSH_ENABLED,
    OPT_QUIET_SCHEDULE,
    OPT_EXPERT,
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
    # device_class nur mitgeben, wenn gesetzt: None wird sonst zu [] und das Frontend zeigt gar nichts (HEATING-26)
    extra = {"device_class": device_class} if device_class else {}
    return sel.EntitySelector(sel.EntitySelectorConfig(domain=domain, multiple=multiple, **extra))


def _opt(key: str, data: dict) -> Any:
    """Optionales Feld: Default nur setzen, wenn ein Wert vorhanden ist."""
    return vol.Optional(key, description={"suggested_value": data.get(key)})


class HeatingCoreConfigFlow(ConfigFlow, domain=DOMAIN):
    """Eine Anlage je HA-Instanz (Fabian, 09.11.2026; manifest single_config_entry); Heizkreise und Räume darunter beliebig."""

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
                # Benachrichtigungen (HEATING-15): Push an Mobile-App-Geräte, still im Ruhezeit-Zeitplan
                vol.Required(OPT_PUSH_ENABLED, default=o[OPT_PUSH_ENABLED]): bool,
                vol.Optional(OPT_NOTIFY_DEVICES, default=o[OPT_NOTIFY_DEVICES]): sel.DeviceSelector(
                    sel.DeviceSelectorConfig(integration="mobile_app", multiple=True)
                ),
                _opt(OPT_QUIET_SCHEDULE, o): _entity("schedule"),
                vol.Required(OPT_EXPERT, default=o[OPT_EXPERT]): bool,
            }
        )
        if self.config_entry.data.get(CONF_MANUFACTURER) == "oekofen":
            # träger Kessel: Räume heben den Kreis erst ab dieser Differenz zum Komfort (HEATING-19)
            schema = schema.extend({
                vol.Required(OPT_ROOM_DEMAND_DELTA, default=o[OPT_ROOM_DEMAND_DELTA]): _temp(0, 5, 0.5),
                vol.Required(OPT_PRE_HEAT_LEAD, default=o[OPT_PRE_HEAT_LEAD]): _num(0, 3, 0.5, "h"),
            })
        return self.async_show_form(step_id="init", data_schema=schema)


def _common(d: dict, schedule: bool = True, window: bool = True, temp: bool = True) -> dict:
    """Gemeinsame optionale Felder: Präsenz, Zeitplan, Fenster, Temperatursensor."""
    out = {}
    if schedule:
        out[_opt(F_PRESENCE, d)] = _entity("binary_sensor", multiple=True)
        out[_opt(F_SCHEDULE, d)] = _entity("schedule")
    if window:
        out[_opt(F_WINDOW, d)] = _entity("binary_sensor")
    if temp:
        out[_opt(F_TEMP, d)] = _entity("sensor", device_class="temperature")
    return out


def _req(key: str, d: dict) -> vol.Required:
    return vol.Required(key, default=d[key]) if d.get(key) else vol.Required(key)


class _BaseSubFlow(ConfigSubentryFlow):
    """Zwei Schritte (Fabian, 09.11.2026): erst Name und Art/Rolle, dann nur die Felder, die dazu passen.
    Komfort stellt man am Regler bzw. im Dashboard ein, nicht im Formular."""

    _reconf: bool = False
    _base: dict

    def _base_schema(self, d: dict) -> vol.Schema:
        raise NotImplementedError

    def _detail_schema(self, d: dict) -> vol.Schema:
        raise NotImplementedError

    def _errors(self, data: dict) -> dict[str, str]:
        return {}

    def _old(self) -> dict:
        return {**self._get_reconfigure_subentry().data, CONF_NAME: self._get_reconfigure_subentry().title} if self._reconf else {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._base = user_input
            return await self.async_step_details()
        return self.async_show_form(step_id="user", data_schema=self._base_schema({}))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._reconf = True
        if user_input is not None:
            self._base = user_input
            return await self.async_step_details()
        return self.async_show_form(step_id="reconfigure", data_schema=self._base_schema(self._old()))

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        old = self._old()
        errors: dict[str, str] = {}
        if user_input is not None:
            # nur Base + Details übernehmen: geleerte Felder sollen wirklich weg sein; Komfort-Startwert bleibt
            data = {k: old[k] for k in (F_COMFORT,) if k in old} | self._base | user_input
            errors = self._errors(data)
            if not errors:
                title = data.pop(CONF_NAME)
                if self._reconf:
                    return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data)
                return self.async_create_entry(title=title, data=data)
        d = {**old, **self._base, **(user_input or {})}
        return self.async_show_form(step_id="details", data_schema=self._detail_schema(d), errors=errors)


class CircuitFlow(_BaseSubFlow):
    """Heizkreis mit Master (Therme-Zone, Ökofen-Heizkreis …) oder Fußboden extern mit eigener Pumpe."""

    def _base_schema(self, d: dict) -> vol.Schema:
        return vol.Schema({
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): str,
            vol.Required(F_KIND, default=d.get(F_KIND, "radiator")): sel.SelectSelector(
                sel.SelectSelectorConfig(options=["radiator", "floor", KIND_FLOOR_EXTERNAL], translation_key=F_KIND)
            ),
        })

    def _detail_schema(self, d: dict) -> vol.Schema:
        if d.get(F_KIND) == KIND_FLOOR_EXTERNAL:
            return vol.Schema({
                _req(F_PUMP, d): _entity(["switch", "input_boolean"]),
                _req(F_SOURCE_TEMP, d): _entity("sensor"),
                vol.Required(F_SOURCE_ON, default=d.get(F_SOURCE_ON, 50.0)): _num(20, 90, 1, "°C"),
                vol.Required(F_SOURCE_OFF, default=d.get(F_SOURCE_OFF, 45.0)): _num(20, 90, 1, "°C"),
                vol.Required(F_VALVE_DELAY, default=d.get(F_VALVE_DELAY, 180)): _num(0, 900, 10, "s"),
                **_common(d, window=False, temp=False),  # Zeitplan/Präsenz erben die Zonen
            })
        fields = {
            _req(F_MASTER, d): _entity("climate"),
            **_common(d),
            _opt(F_HUMIDITY, d): _entity("sensor", device_class="humidity"),
        }
        if self._get_entry().data.get(CONF_MANUFACTURER) == "vaillant":
            # Betriebsart, die nach dem Sommer wieder gesetzt wird (Blueprint: master_hvac_mode)
            fields[vol.Required(F_HVAC_MODE, default=d.get(F_HVAC_MODE, "heat_cool"))] = sel.SelectSelector(
                sel.SelectSelectorConfig(options=["heat_cool", "auto"], translation_key=F_HVAC_MODE)
            )
        return vol.Schema(fields)

    def _errors(self, data: dict) -> dict[str, str]:
        if data.get(F_KIND) == KIND_FLOOR_EXTERNAL and float(data[F_SOURCE_OFF]) >= float(data[F_SOURCE_ON]):
            return {"base": "source_hysteresis"}
        return {}


class RoomFlow(_BaseSubFlow):
    """Raum mit eigenem TRV (isoliert), Follower des Heizkreises oder Fußboden-Zone."""

    def _base_schema(self, d: dict) -> vol.Schema:
        circuits = [
            sel.SelectOptionDict(value=sid, label=sub.title)
            for sid, sub in self._get_entry().subentries.items()
            if sub.subentry_type == SUB_CIRCUIT
        ]
        return vol.Schema({
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): str,
            _req(F_CIRCUIT, d): sel.SelectSelector(sel.SelectSelectorConfig(options=circuits)),
            vol.Required(F_ROLE, default=d.get(F_ROLE, "isolated")): sel.SelectSelector(
                sel.SelectSelectorConfig(options=["isolated", "follower", ROLE_FLOOR_ZONE], translation_key=F_ROLE)
            ),
        })

    def _detail_schema(self, d: dict) -> vol.Schema:
        role = d.get(F_ROLE)
        if role == ROLE_FLOOR_ZONE:
            return vol.Schema({_req(F_VALVES, d): _entity(["switch", "input_boolean"], multiple=True), **_common(d)})
        if role == "follower":
            return vol.Schema({
                _req(F_CLIMATE, d): _entity("climate"),
                vol.Required(F_OFFSET, default=d.get(F_OFFSET, -2.0)): _temp(-3, 2),
                **_common(d, schedule=False, temp=False),
            })
        return vol.Schema({_req(F_CLIMATE, d): _entity("climate"), **_common(d)})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not any(s.subentry_type == SUB_CIRCUIT for s in self._get_entry().subentries.values()):
            return self.async_abort(reason="no_circuit")
        return await super().async_step_user(user_input)
