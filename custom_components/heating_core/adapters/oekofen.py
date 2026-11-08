"""Ökofen Pellematic (Integration oekofen-pellematic-compact).

Gesteuert wird nur über den Offset `number.<kreis>_remote_override` (Entscheidung Fabian,
08.11.2026); Heiz- und Absenktemperatur der Pellematic bleiben unangetastet. Fällt HA aus,
wirkt der zuletzt gesetzte Offset weiter; die Kessellogik bleibt aktiv.

Annahme (im Schattenbetrieb in Perg zu prüfen): `sensor.<kreis>_l_roomtemp_set` ist der
wirksame Sollwert inklusive Offset. Basis ohne Offset = gemeldeter Sollwert − aktueller Offset.
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


def offset_for(target: float, reported_setpoint: float, current_offset: float) -> float:
    """Offset, damit der wirksame Sollwert `target` wird (auf 0,1 K, begrenzt auf ±3 K)."""
    base = reported_setpoint - current_offset
    return round(max(-MAX_OFFSET_K, min(MAX_OFFSET_K, target - base)), 1)


class OekofenAdapter:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _num(self, entity_id: str) -> float | None:
        st = self.hass.states.get(entity_id)
        return _float(st.state) if st else None

    def read(self, master_entity: str) -> CircuitState:
        st = self.hass.states.get(master_entity)
        if st is None or st.state in ("unavailable", "unknown"):
            return CircuitState(None, None, False)
        base = circuit_base(master_entity)
        setpoint = self._num(f"sensor.{base}_l_roomtemp_set")
        if setpoint is None:
            setpoint = _float(st.attributes.get("temperature"))
        current = self._num(f"sensor.{base}_l_roomtemp_act")
        if current is None:
            current = _float(st.attributes.get("current_temperature"))
        return CircuitState(setpoint, current, True)

    def limits(self, master_entity: str) -> AdapterLimits:
        st = self.hass.states.get(master_entity)
        attrs = st.attributes if st else {}
        # Pelletkessel: träge, Bestätigung kommt mit dem nächsten Abruf der Pellematic
        return AdapterLimits(
            min_temp=_float(attrs.get("min_temp")) or 7.0,
            max_temp=_float(attrs.get("max_temp")) or 35.0,
            confirm_delay_s=10 * 60,
        )

    def offset(self, master_entity: str, target: float) -> float | None:
        state = self.read(master_entity)
        current = self._num(f"number.{circuit_base(master_entity)}_remote_override")
        if not state.available or state.setpoint is None or current is None:
            return None
        return offset_for(target, state.setpoint, current)

    async def write_setpoint(self, master_entity: str, value: float) -> None:
        offset = self.offset(master_entity, value)
        if offset is None:
            raise ValueError(f"Offset für {master_entity} nicht berechenbar")
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": f"number.{circuit_base(master_entity)}_remote_override", "value": offset},
            blocking=True,
        )
