"""Hersteller-Adapter: setzen den berechneten Kreis-Sollwert an der Anlage um."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .base import HeatingAdapter
from .climate import ClimateAdapter
from .oekofen import OekofenAdapter


def get_adapter(hass: HomeAssistant, manufacturer: str) -> HeatingAdapter:
    """Adapter zum Hersteller. Vaillant nutzt bis HEATING-11 den allgemeinen Klima-Adapter."""
    if manufacturer == "oekofen":
        return OekofenAdapter(hass)
    return ClimateAdapter(hass)
