"""Heating Core: herstellerunabhängige Heizungssteuerung."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import HeatingCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

type HeatingConfigEntry = ConfigEntry[HeatingCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    coordinator = HeatingCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_refresh()
    coordinator.start_listening()
    entry.async_on_unload(coordinator.stop_listening)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: HeatingConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
