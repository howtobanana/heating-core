"""Hersteller-Adapter: setzen den berechneten Kreis-Sollwert an der Anlage um."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .base import HeatingAdapter
from .climate import ClimateAdapter


def get_adapter(hass: HomeAssistant, manufacturer: str) -> HeatingAdapter:
    """Adapter zum Hersteller. Vaillant (HEATING-11) und Ökofen (HEATING-8) folgen;
    bis dahin schreibt der allgemeine Klima-Adapter über climate.set_temperature."""
    return ClimateAdapter(hass)
