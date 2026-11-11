"""Heating Core: herstellerunabhängige Heizungssteuerung."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .adapters import get_adapter
from .const import CONF_MANUFACTURER, DOMAIN, F_MASTER
from .coordinator import HeatingCoordinator
from .websocket import async_setup as async_setup_ws

PANEL_URL = "heizung"
STATIC_URL = "/heating_core_static"

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

type HeatingConfigEntry = ConfigEntry[HeatingCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    await _register_panel(hass)
    async_setup_ws(hass)
    coordinator = HeatingCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_load()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_refresh()
    coordinator.start_listening()
    entry.async_on_unload(coordinator.stop_listening)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: HeatingConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    others = [e for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.entry_id != entry.entry_id]
    if ok and not others and hass.data.pop(f"{DOMAIN}_panel", False):
        frontend.async_remove_panel(hass, PANEL_URL)
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> None:
    """Integration entfernt: Anlage zurück an ihre eigene Steuerung (Ökofen: auto, Offset 0)."""
    release = getattr(get_adapter(hass, entry.data.get(CONF_MANUFACTURER, "")), "release", None)
    if release:
        for sub in entry.subentries.values():
            if sub.data.get(F_MASTER):
                await release(sub.data[F_MASTER])


async def _register_panel(hass: HomeAssistant) -> None:
    """Eigene Seite „Heizung“ in der Seitenleiste (einmal, für alle Anlagen)."""
    if hass.data.get(f"{DOMAIN}_panel") or "frontend" not in hass.config.components:
        return  # ohne Frontend (z. B. in Tests) keine Seite
    if not hass.data.get(f"{DOMAIN}_static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), cache_headers=False)]
        )
        hass.data[f"{DOMAIN}_static"] = True
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="heating-core-panel",
        sidebar_title="Heizung",
        sidebar_icon="mdi:radiator",
        module_url=f"{STATIC_URL}/heating-core-panel.js?v=0.17.3",
        require_admin=False,
    )
    hass.data[f"{DOMAIN}_panel"] = True
