"""Heating Core: herstellerunabhängige Heizungssteuerung (Gerüst, HEATING-2)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Anlage einrichten. Logik und Entitäten folgen mit HEATING-4."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Anlage entladen."""
    return True
