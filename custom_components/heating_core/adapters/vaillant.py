"""Vaillant (Integration mypyllant, Zone als climate-Entität) – HEATING-11.

Wie der Vaillant-Blueprint:
- Handbetrieb (heat_cool): Sollwert direkt über climate.set_temperature.
- Zeitprogramm (auto): set_temperature legt ein Quick-Veto an; läuft es in weniger als 30 min ab,
  wird es erneuert (renew_due), damit die Therme nicht ins Zeitprogramm zurückfällt.
- Sommer: Therme aus (hvac off, Warmwasser läuft weiter), danach die gewünschte Betriebsart wieder.
- Cloud-API: Schreib-Budget je Stunde und bis zu 30 min, bis der neue Wert zurückgemeldet wird.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .base import AdapterLimits, CircuitState
from .climate import _float

RENEW_BEFORE = timedelta(minutes=30)
QUICK_VETO_UNSET_YEAR = 1970  # mypyllant meldet 1970-01-01, wenn kein Quick-Veto läuft


def quick_veto_renew_due(hvac_mode: str, end, now) -> bool:
    """Quick-Veto erneuern? Nur im Zeitprogramm und nur, wenn eines läuft und bald endet."""
    if hvac_mode != "auto" or end is None:
        return False
    if isinstance(end, str):
        end = dt_util.parse_datetime(end)
    if end is None or end.year <= QUICK_VETO_UNSET_YEAR:
        return False
    return end - now < RENEW_BEFORE


class VaillantAdapter:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def read(self, master_entity: str) -> CircuitState:
        st = self.hass.states.get(master_entity)
        if st is None or st.state in ("unavailable", "unknown"):
            return CircuitState(None, None, False)
        a = st.attributes
        return CircuitState(
            _float(a.get("temperature")),
            _float(a.get("current_temperature")),
            True,
            renew_due=quick_veto_renew_due(st.state, a.get("quick_veto_end_date_time"), dt_util.now()),
            heating_off=st.state == "off",
        )

    def limits(self, master_entity: str) -> AdapterLimits:
        st = self.hass.states.get(master_entity)
        a = st.attributes if st else {}
        return AdapterLimits(
            min_temp=_float(a.get("min_temp")) or 7.0,
            max_temp=_float(a.get("max_temp")) or 30.0,
            confirm_delay_s=30 * 60,  # Cloud meldet den neuen Wert teils erst nach 30 min
        )

    async def write_setpoint(self, master_entity: str, value: float) -> None:
        await self.hass.services.async_call(
            "climate", "set_temperature", {"entity_id": master_entity, "temperature": value}, blocking=True
        )

    async def summer(self, master_entity: str, summer: bool, hvac_mode: str | None) -> None:
        """Sommer: Therme aus; Sommer vorbei: gewünschte Betriebsart (Formular) wieder setzen."""
        st = self.hass.states.get(master_entity)
        if st is None or st.state in ("unavailable", "unknown"):
            return
        if summer and st.state != "off":
            await self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": master_entity, "hvac_mode": "off"}, blocking=True)
        elif not summer and st.state == "off" and hvac_mode:
            await self.hass.services.async_call("climate", "set_hvac_mode", {"entity_id": master_entity, "hvac_mode": hvac_mode}, blocking=True)
