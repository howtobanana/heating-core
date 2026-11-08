"""Ökofen Pellematic (Integration oekofen-pellematic-compact).

Variante B (Fabian, 08.11.2026): Heating Core macht den Tagesablauf, die Pellematic rechnet
immer mit ihrer eigenen Heizkurve. Geschrieben werden nur Betriebsart und Offset:
- Ziel nahe Heiztemperatur → `select.<kreis>_mode_auto` = heizen, Basis `number.<kreis>_temp_heat`
- Ziel nahe Absenktemperatur → absenken, Basis `number.<kreis>_temp_setback`
- Feinabstimmung über `number.<kreis>_remote_override` (±3 K)
Heiz- und Absenktemperatur der Pellematic bleiben unangetastet. „Schreiben aus“ gibt den Kreis
zurück (auto, Offset 0): dann gilt wieder das eigene Zeitprogramm der Pellematic.

`l_roomtemp_set` taugt nicht als Basis: bei „Raumtemperatur erreicht“ meldet es 8 °C (HEATING-13).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .base import AdapterLimits, CircuitState
from .climate import _float

MAX_OFFSET_K = 3.0


def circuit_base(master_entity: str) -> str:
    """climate.pellematic_heating_circuit_1_climate -> pellematic_heating_circuit_1"""
    name = master_entity.split(".", 1)[1]
    return name[: -len("_climate")] if name.endswith("_climate") else name


MODE_AUTO, MODE_HEAT, MODE_SETBACK = "1_auto", "2_heizen", "3_absenken"


def offset_for(target: float, base: float) -> float:
    """Offset auf die Basis (Heiz- oder Absenktemperatur), auf 0,1 K, begrenzt auf ±3 K."""
    return round(max(-MAX_OFFSET_K, min(MAX_OFFSET_K, target - base)), 1)


def choose_mode(target: float, heat: float, setback: float) -> str:
    """Heizen oder Absenken – je nachdem, welcher Pellematic-Wert näher am Ziel liegt."""
    return MODE_HEAT if abs(target - heat) <= abs(target - setback) else MODE_SETBACK


class OekofenAdapter:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _num(self, entity_id: str) -> float | None:
        st = self.hass.states.get(entity_id)
        return _float(st.state) if st else None

    def fuel(self, master_entity: str) -> tuple[float | None, float | None]:
        """Pelletlager (Stand, Maximum) in kg: climate.pellematic_heating_circuit_1_climate -> sensor.pellematic_pellematic_1_l_storage_fill/_max"""
        prefix = circuit_base(master_entity).split("_heating_circuit")[0]
        base = f"sensor.{prefix}_pellematic_1_l_storage"
        return self._num(f"{base}_fill"), self._num(f"{base}_max")

    def _ids(self, master_entity: str) -> dict[str, str]:
        b = circuit_base(master_entity)
        return {"mode": f"select.{b}_mode_auto", "heat": f"number.{b}_temp_heat", "setback": f"number.{b}_temp_setback",
                "offset": f"number.{b}_remote_override", "text": f"sensor.{b}_l_statetext"}

    def _base(self, ids: dict[str, str]) -> float | None:
        """Heiz- oder Absenktemperatur, je nach Betriebsart (auto: nach aktueller Phase)."""
        mode = (self.hass.states.get(ids["mode"]) or _NONE).state
        text = (self.hass.states.get(ids["text"]) or _NONE).state
        setback = mode == MODE_SETBACK or (mode == MODE_AUTO and text.startswith("Absenk"))
        return self._num(ids["setback"] if setback else ids["heat"])

    def read(self, master_entity: str) -> CircuitState:
        st = self.hass.states.get(master_entity)
        if st is None or st.state in ("unavailable", "unknown"):
            return CircuitState(None, None, False)
        ids = self._ids(master_entity)
        base, offset = self._base(ids), self._num(ids["offset"])
        setpoint = round(base + offset, 1) if base is not None and offset is not None else None
        current = self._num(f"sensor.{circuit_base(master_entity)}_l_roomtemp_act")
        if current is None:
            current = _float(st.attributes.get("current_temperature"))
        # climate „off“ = Pellematic hat den Kreis abgeschaltet (Heizgrenze, Aus) -> nicht übersteuern
        return CircuitState(setpoint, current, setpoint is not None, heating_off=st.state == "off")

    def needs_takeover(self, master_entity: str) -> bool:
        """Läuft der Kreis noch im eigenen Zeitprogramm (auto), obwohl Heating Core steuern soll?"""
        return (self.hass.states.get(self._ids(master_entity)["mode"]) or _NONE).state == MODE_AUTO

    async def release(self, master_entity: str) -> None:
        """Schreiben aus: Kreis zurück ans eigene Zeitprogramm (auto, Offset 0)."""
        ids = self._ids(master_entity)
        if (self.hass.states.get(ids["mode"]) or _NONE).state in (MODE_HEAT, MODE_SETBACK):
            await self.hass.services.async_call("select", "select_option", {"entity_id": ids["mode"], "option": MODE_AUTO}, blocking=True)
        if self._num(ids["offset"]) not in (None, 0.0):
            await self.hass.services.async_call("number", "set_value", {"entity_id": ids["offset"], "value": 0}, blocking=True)

    def limits(self, master_entity: str) -> AdapterLimits:
        st = self.hass.states.get(master_entity)
        attrs = st.attributes if st else {}
        # Pelletkessel: träge, Bestätigung kommt mit dem nächsten Abruf der Pellematic
        return AdapterLimits(
            min_temp=_float(attrs.get("min_temp")) or 7.0,
            max_temp=_float(attrs.get("max_temp")) or 35.0,
            confirm_delay_s=10 * 60,
            modulating=True,  # Pellematic-Heizkurve mit Raumeinfluss regelt, Heating Core hält den Sollwert
        )

    async def write_setpoint(self, master_entity: str, value: float) -> None:
        ids = self._ids(master_entity)
        heat, setback = self._num(ids["heat"]), self._num(ids["setback"])
        if heat is None or setback is None:
            raise ValueError(f"Heiz-/Absenktemperatur für {master_entity} unbekannt")
        mode = choose_mode(value, heat, setback)
        if (self.hass.states.get(ids["mode"]) or _NONE).state != mode:
            await self.hass.services.async_call("select", "select_option", {"entity_id": ids["mode"], "option": mode}, blocking=True)
        offset = offset_for(value, heat if mode == MODE_HEAT else setback)
        if self._num(ids["offset"]) != offset:
            await self.hass.services.async_call("number", "set_value", {"entity_id": ids["offset"], "value": offset}, blocking=True)


class _None:
    state = ""


_NONE = _None()
