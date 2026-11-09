"""Websocket-Befehle für die Seite „Heizung“ (HEATING-20)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, F_SCHEDULE


@callback
def async_setup(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_ws"):
        return
    websocket_api.async_register_command(hass, ws_assign_schedule)
    hass.data[f"{DOMAIN}_ws"] = True


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/assign_schedule", vol.Required("entity_id"): str, vol.Required("schedule"): str}
)
@websocket_api.require_admin
@callback
def ws_assign_schedule(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Zeitplan einem Kreis/Raum zuordnen; die Entität (z. B. Sollwert-Sensor) bestimmt den Kreis/Raum."""
    reg = er.async_get(hass).async_get(msg["entity_id"])
    if not msg["schedule"].startswith("schedule.") or reg is None or reg.platform != DOMAIN or not reg.config_subentry_id:
        connection.send_error(msg["id"], "not_found", "Kreis/Raum oder Zeitplan unbekannt")
        return
    entry = hass.config_entries.async_get_entry(reg.config_entry_id)
    sub = entry.subentries.get(reg.config_subentry_id) if entry else None
    if sub is None:
        connection.send_error(msg["id"], "not_found", "Kreis/Raum unbekannt")
        return
    hass.config_entries.async_update_subentry(entry, sub, data={**sub.data, F_SCHEDULE: msg["schedule"]})
    connection.send_result(msg["id"], {"subentry_id": sub.subentry_id})
