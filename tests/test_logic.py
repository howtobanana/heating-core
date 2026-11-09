"""Rechenlogik: je Regel aus dem Blueprint ein Fall, dazu die echten Fälle aus HA Wien."""

from custom_components.heating_core.logic import (
    Globals,
    MasterInput,
    RoomInput,
    follower_target,
    master_target,
    room_target,
)

# Werte wie in HA Wien (08.11.2026)
G = Globals(eco=19, away_temp=17, min_trv=8, hysteresis=0.5)


def room(**kw):
    base = dict(comfort=21, current_temp=19.5, current_setpoint=19)
    base.update(kw)
    return RoomInput(**base)


def master(**kw):
    base = dict(comfort=22, current_temp=20, set_now=19)
    base.update(kw)
    return MasterInput(**base)


# --- Räume ---------------------------------------------------------------


def test_raum_ohne_bedarf_eco():
    r = room_target(G, room())
    assert (r.target, r.mode, r.active) == (19, "eco", False)


def test_raum_praesenz_heizt_auf_komfort():
    r = room_target(G, room(presence_on=True))
    assert (r.target, r.mode, r.needs_heat) == (21, "presence", True)


def test_raum_deadband_haelt_komfort_bis_ziel_erreicht():
    # zuletzt Komfort geschrieben, noch nicht warm -> bleibt Komfort
    r = room_target(G, room(presence_on=True, current_setpoint=21, current_temp=20.8))
    assert r.target == 21
    # Ziel erreicht -> zurück auf Eco (Ventil zu)
    r = room_target(G, room(presence_on=True, current_setpoint=21, current_temp=21))
    assert r.target == 19


def test_raum_deadband_startet_erst_unter_hysterese():
    # zuletzt Eco, nur knapp unter Ziel -> bleibt Eco (kein Pendeln)
    r = room_target(G, room(presence_on=True, current_setpoint=19, current_temp=20.7))
    assert r.target == 19


def test_raum_ohne_quelle_ist_manuell_aktiv():
    r = room_target(G, room(has_demand_source=False))
    assert (r.mode, r.active) == ("manual", True)


def test_raum_fenster_offen_minimum():
    r = room_target(G, room(presence_on=True, window_open_too_long=True))
    assert (r.target, r.mode) == (8, "window")


def test_raum_abwesend_schlaegt_falsche_praesenz():
    # VAILLANT-2: Radar meldet Präsenz, obwohl niemand da ist -> Abwesend gewinnt
    r = room_target(Globals(**{**G.__dict__, "away": True}), room(presence_on=True))
    assert r.target == 17


def test_raum_gast_hebt_abwesend_auf():
    g = Globals(**{**G.__dict__, "away": True, "guest": True})
    assert room_target(g, room(presence_on=True)).target == 21


def test_raum_preheat_schlaegt_abwesend():
    g = Globals(**{**G.__dict__, "away": True})
    assert room_target(g, room(pre_heat_on=True)).target == 21


def test_raum_sommer_minimum():
    g = Globals(**{**G.__dict__, "summer": True})
    r = room_target(g, room(presence_on=True))
    assert (r.target, r.mode, r.needs_heat) == (8, "summer", False)


def test_raum_fenster_settling_ohne_bedarf_bei_abwesend():
    g = Globals(**{**G.__dict__, "away": True})
    assert room_target(g, room(window_closed_recently=True)).target == 17


def test_follower_offset_und_fenster():
    assert follower_target(G, 21, -2, False) == 19
    assert follower_target(G, 9, -2, False) == 8  # nie unter TRV-Minimum
    assert follower_target(G, 21, -2, True) == 8


# --- Master --------------------------------------------------------------


def test_master_eco_ohne_bedarf():
    res = master_target(G, master(), [])
    assert (res.target, res.state) == (19, "eco")


def test_master_praesenz_komfort():
    res = master_target(G, master(presence_on=True), [])
    assert res.target == 22


def test_master_abwesend():
    g = Globals(**{**G.__dict__, "away": True})
    res = master_target(g, master(presence_on=True, set_now=17), [])
    assert (res.target, res.state) == (17, "away")


def test_master_raum_mit_bedarf_hebt_master():
    r_in = room(presence_on=True, current_temp=19)
    r_res = room_target(G, r_in)
    res = master_target(G, master(), [(r_in, r_res)])
    assert res.target == 21


def test_master_raum_ohne_waermebedarf_hebt_nicht():
    r_in = room(presence_on=True, current_temp=21.5, current_setpoint=19)
    r_res = room_target(G, r_in)
    assert not r_res.needs_heat
    assert master_target(G, master(), [(r_in, r_res)]).target == 19


def test_master_abwesend_ignoriert_raeume():
    g = Globals(**{**G.__dict__, "away": True})
    r_in = room(pre_heat_on=True, current_temp=15)
    r_res = room_target(g, r_in)
    assert master_target(g, master(set_now=17), [(r_in, r_res)]).target == 17


def test_master_fenster_forced_min():
    res = master_target(G, master(presence_on=True, window_open_too_long=True), [])
    assert (res.target, res.state, res.forced_min) == (8, "forced_min", True)


def test_master_temperatursturz_bei_offenem_fenster():
    res = master_target(G, master(any_window_open=True, current_temp=16.5), [])
    assert res.forced_min and res.target == 8


def test_master_kompensation_nicht_bei_abwesenheit():
    # VAILLANT-4: Zuschlag hob den Abwesend-Sollwert um bis zu 3 °C
    g = Globals(**{**G.__dict__, "away": True})
    m = master(weather_enabled=True, outdoor_temp=-12, weather_zones=(3, 1, 0), set_now=17)
    res = master_target(g, m, [])
    assert (res.weather_add, res.target) == (0, 17)


def test_master_kompensation_im_komfort():
    m = master(presence_on=True, weather_enabled=True, outdoor_temp=-3, weather_zones=(3, 1, 0), set_now=22)
    res = master_target(G, m, [])
    assert (res.weather_add, res.target) == (1, 23)


def test_master_feuchte_senkt():
    m = master(presence_on=True, humidity_enabled=True, humidity=70, set_now=22)
    res = master_target(G, m, [])
    assert (res.humidity_drop, res.target) == (0.5, 21.5)


def test_master_boost_bei_grossem_abstand():
    m = master(presence_on=True, boost_enabled=True, current_temp=19.5, set_now=22)
    res = master_target(G, m, [])
    assert res.boost_active and res.target == 24


def test_master_kein_boost_bei_abwesend():
    g = Globals(**{**G.__dict__, "away": True})
    m = master(presence_on=True, boost_enabled=True, current_temp=15, set_now=17)
    assert not master_target(g, m, []).boost_active


def test_master_grenzen_der_anlage():
    m = master(presence_on=True, comfort=40, max_temp=30, set_now=30, current_temp=20)
    assert master_target(G, m, []).target == 30


def test_master_sommer():
    g = Globals(**{**G.__dict__, "summer": True})
    assert master_target(g, master(), []).state == "summer"


def test_heizkurve_haelt_sollwert_statt_zu_takten():
    """Ökofen (modulating): warmer Raum fällt nicht auf Eco zurück, 22,8 bleibt 22,8."""
    from custom_components.heating_core.logic import MasterInput, master_target
    g = G
    m = MasterInput(comfort=22.8, current_temp=23.5, set_now=22.8, schedule_on=True, modulating=True)
    assert master_target(g, m, []).target == 22.8
    m2 = MasterInput(comfort=22.8, current_temp=23.5, set_now=22.8, schedule_on=True)
    assert master_target(g, m2, []).target == g.eco  # Therme ohne Heizkurve: Zweipunkt wie bisher


def test_raum_zeigt_abwesend():
    """Wien 09.11.: Abwesend an -> Raum heißt „away“ (nicht Komfort/Eco), Ziel = Abwesend-Temperatur."""
    g = Globals(**{**G.__dict__, "away": True})
    r = room_target(g, room(schedule_on=True))
    assert (r.mode, r.target) == ("away", g.away_temp)


def test_raum_hebt_traegen_kreis_erst_ab_differenz():
    # Perg 09.11.2026: Büro OG (Komfort 24,5) hob HK1 von 22,8 auf 24,5 °C (HEATING-19)
    m = MasterInput(comfort=22.8, current_temp=23.0, set_now=22.8, schedule_on=True, modulating=True, room_demand_delta=2.0)
    r_in = RoomInput(comfort=24.5, current_temp=23.1, current_setpoint=24.5, schedule_on=True)
    r_res = room_target(G, r_in)
    assert r_res.needs_heat
    assert master_target(G, m, [(r_in, r_res)]).target == 22.8  # 1,4 °C zu kalt: nur der TRV heizt
    cold = RoomInput(comfort=24.5, current_temp=22.0, current_setpoint=24.5, schedule_on=True)
    assert master_target(G, m, [(cold, room_target(G, cold))]).target == 24.5  # 2,5 °C zu kalt: Raum fordert an
