"""Benachrichtigungen wie im Vaillant-Blueprint (HEATING-15).

- Problem-Meldung in HA: erscheint immer bei Problemen und verschwindet von selbst, sobald alles passt.
- Push aufs Handy (Mobile-App-Geräte aus den Optionen): bei Schreibvorgängen am Heizkreis und neuen
  Problemen; während des Ruhezeit-Zeitplans still.
- Leitstand Expert (Option, Standard aus): alle Details jedes Laufs als HA-Meldung, überschreibt sich.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util, slugify

from .const import DEFAULTS, OPT_BRIEFING_TIME, OPT_EXPERT, OPT_NOTIFY_DEVICES, OPT_PUSH_ENABLED, OPT_QUIET_SCHEDULE
from .diagnose import briefing

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
    "room_sensor_blocks": "🟠 Raumfühler der Pellematic schaltet den Kreis ab, obwohl Räume Wärme brauchen – an der Pellematic beim Heizkreis Raumfühler aus bzw. Raumeinfluss 0 (Anleitung: Einstellungen an der Pellematic)",
}


# Diagnose der Ökofen-Integration (HEATING-21); ok/learning sind keine Probleme
DIAGNOSIS_TEXT = {
    "fault": "🔴 Kessel: Störung",
    "warning": "🟠 Kessel: Warnung",
    "maintenance_due": "🟡 Kessel: Wartung fällig",
    "cleaning_due": "🟡 Kessel: Reinigung fällig",
    "cleaning_soon": "🟡 Kessel: Reinigung bald fällig",
    "inefficient": "🟡 Kessel: läuft ineffizient",
    "notice": "🟡 Kessel: Hinweis",
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
    boiler = (data or {}).get("boiler") or {}
    if boiler.get("diagnosis") in DIAGNOSIS_TEXT:
        out.append(DIAGNOSIS_TEXT[boiler["diagnosis"]] + (f": {boiler['diagnosis_text']}" if boiler.get("diagnosis_text") else ""))
    out += [f"🟠 Kessel meldet: {m}" for m in boiler.get("messages_active") or []]
    out += (data or {}).get("health") or []  # System-Diagnose (HEATING-41)
    return out


def _n(v) -> str:
    return "–" if v is None else f"{float(v):.1f}".replace(".", ",")


def expert_text(data: dict, events: list[str]) -> str:
    """Leitstand Expert: je Kreis Soll/Anlage/Entscheidung/Budget, je Raum Soll/Ist/TRV/Modus."""
    g = (data or {}).get("globals")
    lines = []
    if g is not None:
        lines.append(f"Abwesend {'✅' if g.away_effective else '⬜'} · Sommer {'✅' if g.summer else '⬜'} · Abwesend-Temp {_n(g.away_temp)} °C")
    for c in (data or {}).get("circuits", {}).values():
        lines.append("")
        lines.append(f"🌡️ {c.get('name')}: Soll {_n(c.get('target'))} · Anlage {_n(c.get('set_now'))} · Ist {_n(c.get('current'))} °C")
        lines.append(f"   Modus {c.get('mode')} · Entscheidung {c.get('decision')} · Budget {c.get('budget_left')}"
                     + (f" · würde schalten: {', '.join(c['would_switch'])}" if c.get("would_switch") else ""))
        for r in c.get("rooms", {}).values():
            lines.append(f"   ▸ {r.get('name')}: Soll {_n(r.get('target'))} · Ist {_n(r.get('current'))} · TRV {_n(r.get('setpoint'))} · {r.get('mode')}"
                         + (f" · ⚠️ {r['problem']}" if r.get("problem") else ""))
    if events:
        lines += ["", "✍️ " + " | ".join(events)]
    return "\n".join(lines)


class Notifier:
    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass, self.entry = hass, entry
        self._shown: list[str] = []
        self._alert_id = f"heating_core_{entry.entry_id}_problem"
        self._briefed = None  # Datum des letzten Briefings

    def _opt(self, key, default=None):
        return self.entry.options.get(key, DEFAULTS.get(key, default))

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

    async def push(self, title: str, message: str, tag: str = "") -> None:
        if not self._opt(OPT_PUSH_ENABLED, True) or self._quiet():
            return
        for service in self._targets():
            try:
                await self.hass.services.async_call(
                    "notify", service,
                    {"title": title, "message": message, "data": {"tag": f"heating_core_{self.entry.entry_id}{tag}"}},
                    blocking=True,
                )
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.warning("Push an notify.%s fehlgeschlagen: %s", service, err)

    async def _briefing(self, data: dict, problems: list[str]) -> None:
        """Tägliches System-Briefing zur eingestellten Zeit; im Sommer Pause wie im Blueprint (HEATING-41)."""
        at = self._opt(OPT_BRIEFING_TIME)
        g = (data or {}).get("globals")
        if not at or (g is not None and g.summer):
            return
        now = dt_util.now()
        start = now.replace(**dict(zip(("hour", "minute", "second"), map(int, str(at).split(":")[:3]))), microsecond=0)
        # shortcut: Fenster 30 min, damit ein Neustart am Abend nicht nachträglich briefed; Neustart im Fenster kann doppeln
        if self._briefed == now.date() or not 0 <= (now - start).total_seconds() < 1800:
            return
        self._briefed = now.date()
        await self.push(f"📊 Heizung {self.entry.title} – Briefing", briefing(self.hass, data, problems, self._opt), "_briefing")

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
        await self._briefing(data, problems)
        if self._opt(OPT_EXPERT, False):
            await self.hass.services.async_call(
                "persistent_notification", "create",
                {"notification_id": f"heating_core_{self.entry.entry_id}_expert",
                 "title": f"🔍 Heizung {self.entry.title} – Expert ({dt_util.now():%H:%M:%S})",
                 "message": expert_text(data, events)}, blocking=True,
            )
