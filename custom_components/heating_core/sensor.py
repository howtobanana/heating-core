"""Sensoren: berechneter Sollwert je Heizkreis und je Raum, mit Modus und Grund."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUB_CIRCUIT, SUB_ROOM
from .entity import HeatingEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUB_CIRCUIT:
            async_add_entities([CircuitTarget(coordinator, sid, sub.title)], config_subentry_id=sid)
        elif sub.subentry_type == SUB_ROOM:
            async_add_entities([RoomTarget(coordinator, sid, sub.title)], config_subentry_id=sid)


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
            "modus": d.get("state"),
            "anlage_sollwert": d.get("set_now"),
            "entscheidung": d.get("decision"),
            "wuerde_schreiben": d.get("would_write"),
            "problem": d.get("problem"),
        }


class RoomTarget(_Target):
    def _data(self) -> dict:
        for circuit in ((self.coordinator.data or {}).get("circuits") or {}).values():
            if self._sid in circuit.get("rooms", {}):
                return circuit["rooms"][self._sid]
        return {}

    @property
    def native_value(self):
        return self._data().get("target")

    @property
    def extra_state_attributes(self):
        d = self._data()
        return {"modus": d.get("mode"), "trv_sollwert": d.get("setpoint")}
