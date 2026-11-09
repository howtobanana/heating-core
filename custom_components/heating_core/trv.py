"""Thermostat (TRV) mit Raumfühler abgleichen und gehorchen lassen (HEATING-16, Plan Fabian 09.11.2026).

- Raumfühler eingetragen: er liefert den echten Wert. TRVs mit externem Temperatur-Eingang bekommen ihn
  direkt; sonst wird die Kalibrierung (Offset) so gesetzt, dass der TRV die Raumtemperatur zeigt.
- Ohne Raumfühler bleibt die Kalibrierung, wie sie am TRV eingestellt ist.
- Eigener Eco-Modus und eigenes Programm des TRV regeln gegen Heating Core: Eco aus, Preset „manual“.
"""

from __future__ import annotations

import math

CAL_THRESHOLD = 0.5  # Kalibrierung in ganzen Grad: darunter rundet der Abgleich auf 0
CAL_INTERVAL_S = 30 * 60  # TRV braucht Zeit, bis Messwert und Ventil sich eingestellt haben
EXT_THRESHOLD = 0.2  # externer Eingang nimmt Zehntel
EXT_INTERVAL_S = 5 * 60

# Begleit-Entitäten am selben Gerät, erkannt am Ende der entity_id (Zigbee2MQTT/ZHA-Namen)
CAL_SUFFIXES = ("_local_temperature_calibration", "_temperature_calibration")
EXT_SUFFIXES = ("_external_temperature_input", "_external_measured_room_sensor", "_external_temperature")
ECO_SUFFIXES = ("_eco_mode",)


def step_round(value: float, step: float | None) -> float:
    """Sollwert auf die Schrittweite des TRV (Moes BRT-100: ganze Grad), halbe Schritte nach oben."""
    if not step or step <= 0:
        return value
    return round(math.floor(value / step + 0.5) * step, 1)


def new_calibration(room: float, trv_shown: float, cal_now: float, lo: float = -9, hi: float = 9, step: float = 1) -> float | None:
    """Kalibrierung, mit der der TRV die Raumtemperatur zeigt; None, wenn die Abweichung zu klein ist.

    Der TRV zeigt seinen Fühler + Kalibrierung: roh = trv_shown − cal_now, neu = room − roh."""
    if abs(trv_shown - room) <= CAL_THRESHOLD:
        return None
    raw = trv_shown - cal_now
    cal = max(lo, min(hi, step_round(room - raw, step)))
    return None if cal == cal_now else cal


def pick(entity_ids: list[str], suffixes: tuple[str, ...]) -> str | None:
    return next((e for e in entity_ids for s in suffixes if e.endswith(s)), None)
