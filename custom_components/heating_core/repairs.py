"""Reparaturen (Einstellungen → Reparaturen): Anleitung, was an der Anlage umzustellen ist, mit Bestätigung."""

from __future__ import annotations

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict | None) -> RepairsFlow:
    """Raumfühler der Pellematic (HEATING-29): Bestätigen schließt die Meldung; sperrt er weiter, kommt sie wieder."""
    return ConfirmRepairFlow()
