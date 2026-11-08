"""Benachrichtigungen wie im Vaillant-Blueprint (HEATING-15).

- Problem-Meldung in HA: erscheint immer bei Problemen und verschwindet von selbst, sobald alles passt.
- Push aufs Handy (Mobile-App-Geräte aus den Optionen): bei Schreibvorgängen am Heizkreis und neuen
  Problemen; während des Ruhezeit-Zeitplans still. Den „Leitstand Expert“ ersetzt die Seite „Heizung“.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify

from .const import OPT_NOTIFY_DEVICES, OPT_PUSH_ENABLED, OPT_QUIET_SCHEDULE

_LOGGER = logging.getLogger(__name__)

PROBLEM_TEXT = {
    "master_unavailable": "🔴 Heizkreis/Kessel nicht erreichbar",
    "temperature_unknown": "🟠 Ist-Temperatur fehlt",
    "room_unavailable": "🟠 Thermostat nicht erreichbar",
    "room_write_failed": "🟠 Thermostat hat den Sollwert nicht übernommen – Funk und Batterie prüfen",
    "sensor_missing": "🟠 Temperatursensor fehlt",
    "source_temperature_unknown": "🟠 Kesseltemperatur unbekannt",
    "forced_min": "🔴 NOT-AUS aktiv – Heizkreis auf Minimum",
    "budget": "🟡 Schreib-Budget erschöpft",
}


def collect_problems(data: dict) -> list[str]:
    """Alle Probleme der Anlage als lesbare Zeilen (gleiche Quelle wie binary_sensor Problem)."""
    out: list[str] = []
    for c in (data or {}).get("circuits", {}).values():
        if c.get("problem"):
            out.append(f"{PROBLEM_TEXT.get(c['problem'], c['problem'])}: {c.get('name')}")
        if c.get("state") == "forced_min" and not c.get("window_open"):
            out.append(f"{PROBLEM_TEXT['forced_min']}: {c.get('name')}")
        if c.get("budget_left") == 0:
            out.append(f"{PROBLEM_TEXT['budget']}: {c.get('name')}")
        for r in c.get("rooms", {}).values():
            if r.get("problem"):
                out.append(f"{PROBLEM_TEXT.get(r['problem'], r['problem'])}: {r.get('name')}")
    return out


class Notifier:
    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass, self.entry = hass, entry
        self._shown: list[str] = []
        self._alert_id = f"heating_core_{entry.entry_id}_problem"

    def _opt(self, key, default=None):
        return self.entry.options.get(key, default)

    def _targets(self) -> list[str]:
        """notify.mobile_app_<gerät> wie im Blueprint (Gerätename → Service-Name)."""
        reg = dr.async_get(self.hass)
        names = []
        for dev_id in self._opt(OPT_NOTIFY_DEVICES) or []:
            dev = reg.async_get(dev_id)
            if dev:
                names.append(f"mobile_app_{slugify(dev.name_by_user or dev.name or '')}")
        return names

    def _quiet(self) -> bool:
        sched = self._opt(OPT_QUIET_SCHEDULE)
        st = self.hass.states.get(sched) if sched else None
        return bool(st and st.state == "on")

    async def push(self, title: str, message: str) -> None:
        if not self._opt(OPT_PUSH_ENABLED, True) or self._quiet():
            return
        for service in self._targets():
            try:
                await self.hass.services.async_call(
                    "notify", service,
                    {"title": title, "message": message, "data": {"tag": f"heating_core_{self.entry.entry_id}"}},
                    blocking=True,
                )
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.warning("Push an notify.%s fehlgeschlagen: %s", service, err)

    async def update(self, data: dict, events: list[str], ready: bool) -> None:
        """Nach jedem Lauf: Problem-Meldung pflegen, Schreibvorgänge und neue Probleme pushen."""
        if not ready:  # nach dem HA-Start sind Sensoren kurz weg – keine Fehlalarme
            return
        problems = collect_problems(data)
        title = f"⚠️ Heizung {self.entry.title} – Problem erkannt"
        if problems != self._shown:
            if problems:
                await self.hass.services.async_call(
                    "persistent_notification", "create",
                    {"notification_id": self._alert_id, "title": title, "message": "\n".join(problems)}, blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    "persistent_notification", "dismiss", {"notification_id": self._alert_id}, blocking=True
                )
            new = [p for p in problems if p not in self._shown]
            self._shown = problems
            if new:
                await self.push(title, "\n".join(new))
        if events:
            await self.push(f"🔥 Heizung {self.entry.title}", "\n".join(events))
