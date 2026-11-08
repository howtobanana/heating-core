"""Präsenz-Entprellung und Fenster-Zeiten aus Zuständen und Zeitpunkten (ohne Home Assistant).

Blueprint-Verhalten: Ein Raum gilt als belegt, wenn ein Präsenzsensor mindestens die
Aktivierungszeit „an“ ist; als frei erst, wenn alle Sensoren die Nachlaufzeit „aus“ sind.
Unbekannte/unerreichbare Sensoren ändern nichts (der letzte Zustand bleibt).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reading:
    state: str  # "on", "off", "unavailable", "unknown"
    since: float  # Zeitpunkt der letzten Zustandsänderung (Sekunden)


def presence(
    readings: list[Reading],
    *,
    now: float,
    activation_s: float,
    deactivation_s: float,
    previous: bool,
) -> bool:
    """Ist der Raum belegt?"""
    if not readings:
        return previous
    if any(r.state == "on" and now - r.since >= activation_s for r in readings):
        return True
    if all(r.state == "off" for r in readings) and all(
        now - r.since >= deactivation_s for r in readings
    ):
        return False
    return previous


@dataclass(frozen=True)
class WindowStatus:
    open_too_long: bool
    closed_recently: bool


def window(
    reading: Reading | None, *, now: float, open_delay_s: float, settle_s: float
) -> WindowStatus:
    """Fenster offen länger als die Verzögerung bzw. erst kürzlich geschlossen."""
    if reading is None:
        return WindowStatus(False, False)
    if reading.state == "on":
        return WindowStatus(now - reading.since >= open_delay_s, False)
    if reading.state == "off":
        return WindowStatus(False, settle_s > 0 and now - reading.since < settle_s)
    return WindowStatus(False, False)
