"""Entscheidung, ob ein Sollwert an die Anlage geschrieben wird (ohne Home Assistant testbar).

Aus dem Vaillant-Blueprint übernommen: Schreib-Budget je 60 min, Anti-Takt-Holds nach
Erhöhen/Absenken mit Bypass bei Ereignissen, Zwangs-Minimum ohne Budget, Startschutz,
Soll-0-Schutz. Dazu VAILLANT-5: derselbe Wert wird nicht erneut geschrieben, solange die
Anlage ihn noch nicht bestätigt hat, und VAILLANT-2: Erneuern (z. B. Quick-Veto) auf Anforderung.
"""

from __future__ import annotations

from dataclasses import dataclass

WINDOW_S = 3600


@dataclass(frozen=True)
class Write:
    ts: float
    value: float
    kind: str  # raise, drop, sync


@dataclass(frozen=True)
class WriteConfig:
    budget_per_hour: int = 10
    hysteresis: float = 0.6
    hold_drop_after_raise_s: float = 20 * 60
    hold_raise_after_drop_s: float = 10 * 60
    confirm_delay_s: float = 30 * 60  # so lange meldet die Anlage einen Write evtl. noch nicht
    significant_drop: float = 1.5
    budget_limited: bool = True  # False: kein Schreib-Budget (z. B. Ökofen)
    min_hold_s: float = 0.0  # träger Kessel: so lange nach jedem Write nichts ändern, außer bei Ereignis (HEATING-19)
    symmetric_hysteresis: bool = False  # Hysterese auch beim Absenken

    @property
    def budget(self) -> int:
        return min(max(self.budget_per_hour, 5), 20)


@dataclass(frozen=True)
class Decision:
    write: bool
    kind: str  # raise, drop, sync, none
    reason: str


def recent(writes: list[Write], now: float) -> list[Write]:
    """Writes der letzten 60 min, älteste zuerst."""
    return [w for w in writes if now - w.ts < WINDOW_S]


def decide(
    *,
    now: float,
    target: float,
    set_now: float | None,
    writes: list[Write],
    cfg: WriteConfig,
    forced_min: bool = False,
    away: bool = False,
    bypass: bool = False,
    renew_due: bool = False,
    startup_done: bool = True,
) -> Decision:
    """Soll `target` jetzt geschrieben werden? `set_now` ist der von der Anlage gemeldete Sollwert."""
    if not startup_done:
        return Decision(False, "none", "startup")
    if set_now is None or set_now <= 0:
        # Anlage meldet keinen gültigen Sollwert (Abfrage-Artefakt): nicht gegenregeln.
        return Decision(False, "none", "no_setpoint")

    last = writes[-1] if writes else None
    if last and abs(last.value - target) < 0.1 and now - last.ts < cfg.confirm_delay_s:
        return Decision(False, "none", "pending_confirmation")

    delta = target - set_now
    kind = "raise" if delta > 0.1 else "drop" if delta < -0.1 else "sync"
    budget_ok = not cfg.budget_limited or len(recent(writes, now)) < cfg.budget

    if forced_min and abs(delta) > 0.5:
        return Decision(True, kind, "forced_min")  # Sicherheit geht vor Budget
    if kind == "sync":
        if renew_due and budget_ok:
            return Decision(True, "sync", "renew")
        return Decision(False, "none", "no_delta")
    if not budget_ok:
        return Decision(False, "none", "budget")

    age = now - last.ts if last else float("inf")
    override = bypass or away or forced_min
    if last and age < cfg.min_hold_s and not override:
        return Decision(False, "none", "hold_min")
    if cfg.symmetric_hysteresis and abs(delta) <= cfg.hysteresis and not override:
        return Decision(False, "none", "within_hysteresis")
    if kind == "drop":
        if -delta >= cfg.significant_drop:
            return Decision(True, "drop", "significant_drop")
        if last and last.kind == "raise" and age < cfg.hold_drop_after_raise_s and not override:
            return Decision(False, "none", "hold_drop")
        return Decision(True, "drop", "drop")

    if delta <= cfg.hysteresis and not override:
        return Decision(False, "none", "within_hysteresis")
    if last and last.kind == "drop" and age < cfg.hold_raise_after_drop_s and not override:
        return Decision(False, "none", "hold_raise")
    return Decision(True, "raise", "raise")
