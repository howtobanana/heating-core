"""Regler: Komfort je Heizkreis/Raum, Eco und Abwesend der Anlage (bleiben über Neustarts erhalten)."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULTS, F_COMFORT, OPT_ACTIVATION_MIN, OPT_AWAY_TEMP, OPT_DEACTIVATION_MIN, OPT_ECO, SUB_CIRCUIT, SUB_ROOM
from .entity import HeatingEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([GlobalTemp(coordinator, "eco"), GlobalTemp(coordinator, "away_temp"),
                        PresenceDelay(coordinator, "presence_on_min", OPT_ACTIVATION_MIN, 60),
                        PresenceDelay(coordinator, "presence_off_min", OPT_DEACTIVATION_MIN, 240)])
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUB_CIRCUIT:
            # Absenkung gibt es je Heizkreis (Fabian, 08.11.2026), Räume erben sie; Abwesend bleibt global
            new = [Setback(coordinator, sid, sub.title)]
            if sub.data.get("kind") != "floor_external":  # externer Fußbodenkreis: Komfort nur in den Zonen
                new.append(Comfort(coordinator, sid, sub.title, float(sub.data.get(F_COMFORT, 21.0))))
            async_add_entities(new, config_subentry_id=sid)
        elif sub.subentry_type == SUB_ROOM and sub.data.get("role") != "follower":
            async_add_entities([Comfort(coordinator, sid, sub.title, float(sub.data.get(F_COMFORT, 21.0)))], config_subentry_id=sid)


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
        self.coordinator.user_input()
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


class PresenceDelay(_Temp):
    """Glättung der Präsenz für alle Räume: an nach / aus nach (Minuten). Die geglättete Präsenz steht je Raum
    als binary_sensor.<raum>_presence bereit und ersetzt die Präsenz-Helfer des Blueprints."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_step = 1.0
    _attr_native_min_value = 0.0
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key: str, opt: str, maximum: float) -> None:
        super().__init__(coordinator, key)
        self._key, self._opt = key, opt
        self._attr_translation_key = key
        self._attr_native_max_value = maximum

    def _store(self, value: float) -> None:
        setattr(self.coordinator.control, self._key, value)

    @property
    def native_value(self) -> float:
        return self.coordinator.presence_delay(self._opt)
