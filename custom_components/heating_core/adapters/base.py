"""Schnittstelle, die jeder Hersteller-Adapter erfüllt (Konzept Abschnitt 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CircuitState:
    setpoint: float | None  # von der Anlage gemeldeter Sollwert
    current: float | None  # Ist-Temperatur laut Anlage
    available: bool
    renew_due: bool = False  # z. B. Vaillant-Quick-Veto läuft bald ab
    heating_off: bool = False  # Anlage hat den Kreis selbst abgeschaltet (z. B. Heizgrenze)


@dataclass(frozen=True)
class AdapterLimits:
    min_temp: float = 7.0
    max_temp: float = 30.0
    confirm_delay_s: float = 30 * 60


class HeatingAdapter(Protocol):
    def read(self, master_entity: str) -> CircuitState: ...

    def limits(self, master_entity: str) -> AdapterLimits: ...

    async def write_setpoint(self, master_entity: str, value: float) -> None: ...
