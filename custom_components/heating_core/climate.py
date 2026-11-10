"""Thermostat je Heizkreis/Raum für native Dashboard-Karten (Tile, Thermostat), wie in HA Wien.

Soll = Regler „Komfort“ (dieselbe Zahl wie number.*_comfort), Ist = gemessene Temperatur,
hvac_action = heizt / Ruhe / aus nach dem, was die Anlage meldet. Schaltet selbst nichts an der Anlage.
"""

from __future__ import annotations

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import F_COMFORT, SUB_CIRCUIT, SUB_ROOM
from .entity import HeatingEntity

OFF_MODES = {"circuit_off", "summer", "unavailable"}


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    for sid, sub in entry.subentries.items():
        # wie beim Regler „Komfort“: Follower und externer Fußbodenkreis haben keinen eigenen Sollwert
        if sub.subentry_type == SUB_CIRCUIT and sub.data.get("kind") != "floor_external":
            async_add_entities([Thermostat(coordinator, sid, sub.title, float(sub.data.get(F_COMFORT, 21.0)), True)], config_subentry_id=sid)
        elif sub.subentry_type == SUB_ROOM and sub.data.get("role") not in ("follower", "passive"):
            async_add_entities([Thermostat(coordinator, sid, sub.title, float(sub.data.get(F_COMFORT, 21.0)), False)], config_subentry_id=sid)


class Thermostat(HeatingEntity, ClimateEntity):
    _attr_name = None  # Hauptentität des Geräts: climate.<raum>
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 16.0  # gleiche Grenzen wie der Regler „Komfort“
    _attr_max_temp = 26.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator, sid: str, title: str, default: float, circuit: bool) -> None:
        super().__init__(coordinator, f"{sid}_climate", sid, title)
        self._sid, self._default, self._circuit = sid, default, circuit

    def _data(self) -> dict:
        circuits = (self.coordinator.data or {}).get("circuits") or {}
        if self._circuit:
            return circuits.get(self._sid, {})
        for c in circuits.values():
            if self._sid in c.get("rooms", {}):
                return c["rooms"][self._sid]
        return {}

    def _current(self) -> float | None:
        return self._data().get("current")

    def _target(self) -> float:
        return self.coordinator.control.comfort.get(self._sid, self._default)

    # Neuere HA-Versionen wollen native_* und warnen bei den alten Namen (fallen mit 2027.11 weg, HEATING-22);
    # HA 2026.10 kennt native_* noch nicht – daher je nach Version (shortcut: Zweig entfernen, sobald HA ≥ native-Version Pflicht ist)
    if hasattr(ClimateEntity, "native_current_temperature"):
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def native_current_temperature(self) -> float | None:
            return self._current()

        @property
        def native_target_temperature(self) -> float:
            return self._target()
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def current_temperature(self) -> float | None:
            return self._current()

        @property
        def target_temperature(self) -> float:
            return self._target()

    @property
    def hvac_action(self) -> HVACAction:
        d = self._data()
        mode = d.get("mode")
        if mode in OFF_MODES:
            return HVACAction.OFF
        if d.get("valves_open") is not None:  # Fußboden-Zone: heizt, wenn ihre Ventile offen sind
            return HVACAction.HEATING if d["valves_open"] else HVACAction.IDLE
        if d.get("heat_demand") is not None:  # Raum mit TRV
            return HVACAction.HEATING if d["heat_demand"] else HVACAction.IDLE
        cur, target = d.get("current"), d.get("target")
        return HVACAction.HEATING if cur is not None and target is not None and cur < target else HVACAction.IDLE

    @property
    def extra_state_attributes(self):
        d = self._data()
        return {"sollwert_jetzt": d.get("target"), "modus": d.get("mode")}

    async def async_set_temperature(self, **kwargs) -> None:
        if (value := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self.coordinator.control.comfort[self._sid] = float(value)
        self.async_write_ha_state()
        self.coordinator.user_input()
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Nur „Heizen“: Aus schaltet die Anlage selbst (Sommer, Kreis aus), nicht diese Entität."""
