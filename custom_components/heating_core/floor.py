"""Fußbodenkreis mit eigener Pumpe und Ventil-Kanälen (Sonderfall Perg, HEATING-8).

Regeln (Fabian, 08.11.2026, plus Hydraulik-Grundregeln):
- Freigabe nur, wenn die Wärmequelle (Kessel) warm genug ist: an über `source_on`
  (Standard 50 °C), aus unter `source_off` (Standard 45 °C), dazwischen bleibt es.
- Je Zone öffnen alle Kanäle gemeinsam (Gleichlauf, z. B. Wohnzimmer UG = Kanal 2+3).
- Zone öffnet unter Soll − Hysterese, schließt bei Soll erreicht; dazwischen bleibt sie.
- Zone ohne Temperatursensor: Kanäle werden nicht angefasst (None), Problem „sensor_missing“.
- Pumpe erst an, wenn die Ventile einer offenen Zone mindestens `valve_delay_s` offen sind.
- Abschalten: erst die Pumpe aus; Ventile schließen erst, wenn die Pumpe aus ist.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    key: str
    temp: float | None
    target: float
    open_now: bool  # alle Kanäle der Zone sind an
    open_since: float | None  # seit wann offen (Sekunden), None wenn zu


@dataclass(frozen=True)
class FloorPlan:
    source_ok: bool
    zones: dict[str, bool | None]  # gewünschter Zustand je Zone, None = nicht anfassen
    pump: bool
    problems: dict[str, str]


def plan(
    zones: list[Zone],
    *,
    now: float,
    source_temp: float | None,
    source_on: float = 50.0,
    source_off: float = 45.0,
    source_ok_before: bool = False,
    pump_on: bool = False,
    valve_delay_s: float = 180.0,
    hysteresis: float = 0.5,
) -> FloorPlan:
    if source_temp is None:
        source_ok = False
    elif source_ok_before:
        source_ok = source_temp >= source_off
    else:
        source_ok = source_temp > source_on

    wanted: dict[str, bool | None] = {}
    problems: dict[str, str] = {}
    for z in zones:
        if z.temp is None:
            wanted[z.key] = None
            problems[z.key] = "sensor_missing"
        elif z.open_now:
            wanted[z.key] = z.temp < z.target
        else:
            wanted[z.key] = z.temp < z.target - hysteresis

    demand = [z for z in zones if wanted[z.key]]
    ready = any(z.open_now and z.open_since is not None and now - z.open_since >= valve_delay_s for z in demand)
    pump = source_ok and bool(demand) and ready

    if pump_on and not pump:
        # Pumpe läuft noch: diesmal nur die Pumpe aus, Ventile bleiben, wie sie sind.
        wanted = {z.key: (z.open_now if wanted[z.key] is False else wanted[z.key]) for z in zones}
    return FloorPlan(source_ok=source_ok, zones=wanted, pump=pump, problems=problems)
