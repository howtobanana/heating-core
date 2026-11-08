"""Allgemeiner Adapter: Kreis-Sollwert über climate.set_temperature."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .base import AdapterLimits, CircuitState


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ClimateAdapter:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def read(self, master_entity: str) -> CircuitState:
        st = self.hass.states.get(master_entity)
        if st is None or st.state in ("unavailable", "unknown"):
            return CircuitState(None, None, False)
        return CircuitState(
            _float(st.attributes.get("temperature")),
            _float(st.attributes.get("current_temperature")),
            True,
        )

    def limits(self, master_entity: str) -> AdapterLimits:
        st = self.hass.states.get(master_entity)
        attrs = st.attributes if st else {}
        return AdapterLimits(
            min_temp=_float(attrs.get("min_temp")) or 7.0,
            max_temp=_float(attrs.get("max_temp")) or 30.0,
        )

    async def write_setpoint(self, master_entity: str, value: float) -> None:
        await self.hass.services.async_call(
            "climate", "set_temperature", {"entity_id": master_entity, "temperature": value}, blocking=True
        )
