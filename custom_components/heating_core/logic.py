"""Reine Rechenlogik von Heating Core (ohne Home Assistant, dadurch direkt testbar).

Übernommen aus dem Vaillant-Blueprint `vaillant_heizungs-steuerung.yaml` (Stand 8568255),
einschließlich der Korrekturen aus VAILLANT-2 bis -5. Herstellerunabhängig: Adapter
bekommen nur das Ergebnis (Sollwert je Kreis/Raum).
"""

from __future__ import annotations

from dataclasses import dataclass


def round_half(value: float) -> float:
    """Auf 0,5 °C runden (wie die Thermen/TRVs)."""
    return round(value * 2) / 2


@dataclass(frozen=True)
class Globals:
    """Anlagenweite Werte."""

    eco: float
    away_temp: float
    min_trv: float
    hysteresis: float = 0.6
    away: bool = False
    guest: bool = False
    summer: bool = False

    @property
    def away_effective(self) -> bool:
        """Gast-Modus hebt Abwesend auf."""
        return self.away and not self.guest


@dataclass(frozen=True)
class RoomInput:
    """Isolierter Raum mit eigenem TRV."""

    comfort: float
    current_temp: float
    current_setpoint: float
    schedule_on: bool = False
    presence_on: bool = False
    pre_heat_on: bool = False
    has_demand_source: bool = True  # Zeitplan, Präsenz-Helfer oder -Sensor eingerichtet
    window_open_too_long: bool = False
    window_closed_recently: bool = False


@dataclass(frozen=True)
class RoomResult:
    target: float
    mode: str
    active: bool
    needs_heat: bool


def room_base(g: Globals, r: RoomInput) -> tuple[float, bool]:
    """Zieltemperatur des Raums ohne Ein/Aus-Regelung (für Fußboden-Zonen) und ob Bedarf besteht."""
    pre_heat = r.pre_heat_on and not g.summer
    # ohne Zeitplan/Präsenz: Absenkung, nicht dauernd Komfort (Fabian, 09.11.2026)
    active = r.schedule_on or r.presence_on or pre_heat
    if g.summer or r.window_open_too_long:
        return g.min_trv, active
    if g.away_effective and not pre_heat:
        return g.away_temp, active
    return (r.comfort if active else g.eco), active


def room_target(g: Globals, r: RoomInput) -> RoomResult:
    """Sollwert eines isolierten Raums."""
    pre_heat = r.pre_heat_on and not g.summer
    manual = False  # ohne Zeitplan/Präsenz: Absenkung, nicht dauernd Komfort (Fabian, 09.11.2026)
    active = r.schedule_on or r.presence_on or pre_heat

    if g.away_effective and not pre_heat:
        base = g.away_temp
    elif active:
        base = r.comfort
    else:
        base = g.eco

    if r.window_open_too_long:
        raw = g.min_trv
    elif active and base > g.eco:
        # Bang-Bang mit Deadband: Zustand über den zuletzt geschriebenen Sollwert halten.
        was_comfort = r.current_setpoint >= base - 0.5
        if was_comfort:
            raw = g.eco if r.current_temp >= base else base
        else:
            raw = base if r.current_temp < base - g.hysteresis else g.eco
    elif r.window_closed_recently:
        raw = base if active else (g.away_temp if g.away_effective else g.eco)
    else:
        raw = base

    if g.summer:
        raw = g.min_trv
    target = max(g.min_trv, raw)

    if g.summer:
        mode = "summer"
    elif r.window_open_too_long:
        mode = "window"
    elif g.away_effective and not pre_heat:
        mode = "away"  # wie beim Heizkreis: Abwesend geht vor Zeitplan/Präsenz/Komfort
    elif r.schedule_on:
        mode = "schedule"
    elif r.presence_on:
        mode = "presence"
    elif pre_heat:
        mode = "pre_heat"
    elif manual:
        mode = "manual"
    else:
        mode = "eco"

    needs_heat = active and target > r.current_temp + g.hysteresis and not g.summer
    return RoomResult(target=target, mode=mode, active=active, needs_heat=needs_heat)


def follower_target(
    g: Globals, master_target: float, offset: float, window_open_too_long: bool
) -> float:
    """Follower-Raum folgt dem Master-Sollwert mit Offset."""
    if g.summer or window_open_too_long:
        return g.min_trv
    return max(g.min_trv, master_target + offset)


@dataclass(frozen=True)
class MasterInput:
    """Führender Raum des Heizkreises (Therme/Kessel-Sollwert)."""

    comfort: float
    current_temp: float
    set_now: float  # aktuell an der Anlage gesetzter Sollwert
    schedule_on: bool = False
    presence_on: bool = False
    pre_heat_on: bool = False
    has_demand_source: bool = True
    window_open_too_long: bool = False
    any_window_open: bool = False
    smart_drop_threshold: float = 2.0
    presence_priority: bool = False
    min_temp: float = 7.0
    max_temp: float = 30.0
    # Boost
    boost_enabled: bool = False
    boost_amount: float = 2.0
    boost_threshold: float = 1.0
    # Gebäude-Kompensation
    weather_enabled: bool = False
    weather_sensor_value: float | None = None  # Plan A: Aufschlag direkt in °C
    outdoor_temp: float | None = None  # Plan B: Zonen
    weather_zones: tuple[float, float, float] = (0.0, 0.0, 0.0)  # <=-10, <=0, <10 °C
    # Feuchte-Kompensation
    humidity_enabled: bool = False
    humidity: float | None = None
    humidity_drop: float = 0.5
    # Anlage mit eigener Heizkurve (Ökofen): Sollwert halten statt Zweipunkt, auf 0,1 K genau
    modulating: bool = False
    # Räume heben den Kreis nur, wenn sie so weit unter ihrem Komfort liegen (0 = immer, HEATING-19)
    room_demand_delta: float = 0.0


@dataclass(frozen=True)
class MasterResult:
    target: float
    target_before_mods: float  # master_target_final des Blueprints (Basis für Follower)
    state: str  # summer, forced_min, away, heating, eco
    forced_min: bool
    boost_active: bool
    weather_add: float
    humidity_drop: float


def _weather_add(m: MasterInput, g: Globals) -> float:
    if not m.weather_enabled or g.summer:
        return 0.0
    if m.weather_sensor_value is not None:
        return m.weather_sensor_value
    if m.outdoor_temp is None:
        return 0.0
    q = round_half(m.outdoor_temp)
    if q <= -10.0:
        return m.weather_zones[0]
    if q <= 0.0:
        return m.weather_zones[1]
    if q < 10.0:
        return m.weather_zones[2]
    return 0.0


def master_target(
    g: Globals, m: MasterInput, rooms: list[tuple[RoomInput, RoomResult]]
) -> MasterResult:
    """Sollwert für den Wärmeerzeuger eines Heizkreises."""
    away = g.away_effective
    pre_heat = m.pre_heat_on and not g.summer
    manual = False  # ohne Zeitplan/Präsenz: Absenkung, nicht dauernd Komfort (Fabian, 09.11.2026)
    presence = m.presence_on
    demand = m.comfort if (m.schedule_on or presence or manual or pre_heat) else g.eco
    target_temp = g.away_temp if (away and not pre_heat) else demand

    rapid_drop = (
        m.any_window_open
        and not m.window_open_too_long
        and m.current_temp < g.eco - m.smart_drop_threshold
    )
    forced_min = rapid_drop or m.window_open_too_long
    target_final = g.min_trv if forced_min else target_temp
    floor = g.min_trv if away else g.eco

    room_demands = [res.target for r, res in rooms if res.active and res.needs_heat
                    and (m.room_demand_delta <= 0 or r.comfort - r.current_temp >= m.room_demand_delta)]
    if forced_min:
        base_required = floor
    elif away or (m.presence_priority and presence) or not room_demands:
        base_required = target_final
    else:
        base_required = max(target_final, max(room_demands))
    base_required = max(base_required, floor)

    # Gebäude-Kompensation: nicht bei Abwesenheit (VAILLANT-4), nur über dem Boden.
    weather = 0.0
    if m.weather_enabled and not forced_min and not away and base_required > floor + 0.1:
        weather = round_half(min(max(_weather_add(m, g), 0.0), 5.0))

    hum_drop = 0.0
    if m.humidity_enabled and m.humidity is not None and m.humidity > 60:
        raw_drop = (m.humidity - 60) / 10.0 * m.humidity_drop
        hum_drop = min(max(round_half(raw_drop), 0.0), 2.0)

    # Boost
    boost_allowed = (
        m.boost_enabled
        and m.boost_amount > 0
        and not forced_min
        and not away
        and not m.window_open_too_long
        and not g.summer
    )
    any_needs = False
    all_deactivate = True
    if boost_allowed:
        if m.schedule_on or presence or manual:
            delta = target_final - m.current_temp
            any_needs = delta >= m.boost_threshold
            all_deactivate = delta < 0.5
        for r, res in rooms:
            r_delta = r.comfort - r.current_temp
            if res.active and not r.window_open_too_long and r_delta >= m.boost_threshold:
                any_needs = True
            if res.active and r_delta >= m.boost_threshold / 2:
                all_deactivate = False
    boost_active = boost_allowed and any_needs and not all_deactivate

    # Deadband am Master
    if forced_min:
        pure = g.min_trv
    else:
        base_raw = max(base_required - hum_drop, floor)
        eco_result = max(g.eco, floor)
        if base_raw <= g.eco or m.modulating:
            pure = base_raw
        elif m.set_now >= base_raw - 0.5:
            pure = eco_result if m.current_temp >= base_raw else base_raw
        else:
            pure = base_raw if m.current_temp < base_raw - g.hysteresis else eco_result
    pure = max(min(pure, m.max_temp), m.min_temp)

    final = pure + (m.boost_amount if boost_active else 0.0) + weather
    final = max(min(final, m.max_temp), m.min_temp)
    final = round(final, 1) if m.modulating else round_half(final)

    if g.summer:
        state = "summer"
    elif forced_min:
        state = "forced_min"
    elif away:
        state = "away"
    elif final > m.set_now + g.hysteresis or boost_active:
        state = "heating"
    else:
        state = "eco"

    return MasterResult(
        target=final,
        target_before_mods=target_final,
        state=state,
        forced_min=forced_min,
        boost_active=boost_active,
        weather_add=weather,
        humidity_drop=hum_drop,
    )
