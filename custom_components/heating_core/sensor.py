"""Sensoren: berechneter Sollwert je Heizkreis und je Raum, mit Modus und Grund."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfMass, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MODES, SUB_CIRCUIT, SUB_ROOM
from .entity import HeatingEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    if entry.data.get("manufacturer") == "oekofen":
        async_add_entities([Fuel(coordinator)])
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUB_CIRCUIT:
            async_add_entities([CircuitTarget(coordinator, sid, sub.title), Mode(coordinator, sid, sub.title, True)], config_subentry_id=sid)
        elif sub.subentry_type == SUB_ROOM:
            async_add_entities([RoomTarget(coordinator, sid, sub.title), Mode(coordinator, sid, sub.title, False)], config_subentry_id=sid)


class _Target(HeatingEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, sid: str, title: str) -> None:
        super().__init__(coordinator, f"{sid}_target", sid, title)
        self._sid = sid
        self._attr_translation_key = "target"


class CircuitTarget(_Target):
    def _data(self) -> dict:
        return ((self.coordinator.data or {}).get("circuits") or {}).get(self._sid, {})

    @property
    def native_value(self):
        return self._data().get("target")

    @property
    def extra_state_attributes(self):
        d = self._data()
        return {
            "zustand": d.get("state"),
            "anlage_sollwert": d.get("set_now"),
            "entscheidung": d.get("decision"),
            "wuerde_schreiben": d.get("would_write"),
            "problem": d.get("problem"),
            "schreib_budget_rest": d.get("budget_left"),
            "kessel_temperatur": d.get("source_temp"),
            "kessel_freigabe": d.get("source_ok"),
            "pumpe_soll": d.get("pump_wanted"),
            "pumpe_ist": d.get("pump_on"),
            "wuerde_schalten": d.get("would_switch"),
            "ist_temperatur": d.get("current"),
            "anlage": self.coordinator.entry.title,
        }


class RoomTarget(_Target):
    def _circuit(self) -> dict:
        for circuit in ((self.coordinator.data or {}).get("circuits") or {}).values():
            if self._sid in circuit.get("rooms", {}):
                return circuit
        return {}

    def _data(self) -> dict:
        return self._circuit().get("rooms", {}).get(self._sid, {})

    @property
    def native_value(self):
        return self._data().get("target")

    @property
    def extra_state_attributes(self):
        d = self._data()
        return {"modus": d.get("mode"), "trv_sollwert": d.get("setpoint"), "ist_temperatur": d.get("current"),
                "waermebedarf": d.get("heat_demand"), "problem": d.get("problem"),
                "ventile_offen": d.get("valves_open"), "ventile_soll": d.get("valves_wanted"),
                "heizkreis": self._circuit().get("name")}


def _find(coordinator, sid: str, circuit: bool) -> dict:
    circuits = (coordinator.data or {}).get("circuits") or {}
    if circuit:
        return circuits.get(sid, {})
    for c in circuits.values():
        if sid in c.get("rooms", {}):
            return c["rooms"][sid]
    return {}


class Mode(HeatingEntity, SensorEntity):
    """Warum der Sollwert so ist: Eco, Präsenz, Zeitplan, Abwesend, Fenster …"""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = MODES
    _attr_translation_key = "mode"

    def __init__(self, coordinator, sid: str, title: str, circuit: bool) -> None:
        super().__init__(coordinator, f"{sid}_mode", sid, title)
        self._sid, self._circuit = sid, circuit

    @property
    def native_value(self):
        d = _find(self.coordinator, self._sid, self._circuit)
        return d.get("mode") if d.get("mode") in MODES else None


class Fuel(HeatingEntity, SensorEntity):
    """Pelletlager der Anlage (Ökofen), für die Seite „Heizung“."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_translation_key = "fuel"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "fuel")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("fuel_kg")
