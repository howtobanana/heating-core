"""Regler: Komfort je Heizkreis/Raum, Eco und Abwesend der Anlage (bleiben über Neustarts erhalten)."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULTS, F_COMFORT, OPT_AWAY_TEMP, OPT_ECO, SUB_CIRCUIT, SUB_ROOM
from .entity import HeatingEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([GlobalTemp(coordinator, "eco"), GlobalTemp(coordinator, "away_temp")])
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUB_CIRCUIT or (sub.subentry_type == SUB_ROOM and sub.data.get("role") != "follower"):
            if sub.data.get("kind") == "floor_external":
                continue  # externer Fußbodenkreis hat keinen eigenen Sollwert, nur seine Zonen
            async_add_entities([Comfort(coordinator, sid, sub.title, float(sub.data.get(F_COMFORT, 21.0))),
                                Setback(coordinator, sid, sub.title)], config_subentry_id=sid)


class _Temp(HeatingEntity, RestoreNumber):
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5
    _attr_mode = NumberMode.SLIDER

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._store(float(last.native_value))

    def _store(self, value: float) -> None:
        raise NotImplementedError

    async def async_set_native_value(self, value: float) -> None:
        self._store(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class Comfort(_Temp):
    _attr_translation_key = "comfort"
    _attr_native_min_value = 16.0
    _attr_native_max_value = 26.0

    def __init__(self, coordinator, sid: str, title: str, default: float) -> None:
        super().__init__(coordinator, f"{sid}_comfort", sid, title)
        self._sid, self._default = sid, default

    def _store(self, value: float) -> None:
        self.coordinator.control.comfort[self._sid] = value

    @property
    def native_value(self) -> float:
        return self.coordinator.control.comfort.get(self._sid, self._default)


class Setback(_Temp):
    """Absenkung je Kreis/Raum; ohne eigenen Wert gilt die des Heizkreises bzw. das Eco der Anlage."""

    _attr_translation_key = "setback"
    _attr_native_min_value = 10.0
    _attr_native_max_value = 23.0

    def __init__(self, coordinator, sid: str, title: str) -> None:
        super().__init__(coordinator, f"{sid}_setback", sid, title)
        self._sid = sid

    async def async_added_to_hass(self) -> None:
        # nur einen selbst gesetzten Wert wiederherstellen – sonst ginge das Erben vom Heizkreis verloren
        await super(_Temp, self).async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.attributes.get("eigen") and last.state not in ("unknown", "unavailable"):
            self._store(float(last.state))

    @property
    def extra_state_attributes(self):
        return {"eigen": self._sid in self.coordinator.control.setback}

    def _store(self, value: float) -> None:
        self.coordinator.control.setback[self._sid] = value

    @property
    def native_value(self) -> float:
        return self.coordinator.setback(self._sid, self.coordinator.globals().eco)


class GlobalTemp(_Temp):
    _attr_native_min_value = 10.0
    _attr_native_max_value = 23.0

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key

    def _store(self, value: float) -> None:
        setattr(self.coordinator.control, self._key, value)

    @property
    def native_value(self) -> float:
        value = getattr(self.coordinator.control, self._key)
        if value is not None:
            return value
        opt = OPT_ECO if self._key == "eco" else OPT_AWAY_TEMP
        return float(self.coordinator.entry.options.get(opt, DEFAULTS[opt]))
