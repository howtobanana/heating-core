"""Hersteller-Adapter: setzen den berechneten Kreis-Sollwert an der Anlage um."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .base import HeatingAdapter
from .climate import ClimateAdapter
from .oekofen import OekofenAdapter
from .vaillant import VaillantAdapter


def get_adapter(hass: HomeAssistant, manufacturer: str) -> HeatingAdapter:
    """Adapter zum Hersteller."""
    if manufacturer == "oekofen":
        return OekofenAdapter(hass)
    if manufacturer == "vaillant":
        return VaillantAdapter(hass)
    return ClimateAdapter(hass)
