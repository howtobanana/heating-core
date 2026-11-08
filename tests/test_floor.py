"""Fußbodenkreis Perg: Kessel-Freigabe, Gleichlauf, Pumpen-Reihenfolge, fehlender Sensor."""

from custom_components.heating_core.floor import Zone, plan

NOW = 100_000.0
WOHN = "wohnzimmer_ug"
BAD = "bad_og"


def zone(key=WOHN, temp=20.0, target=22.0, open_now=False, open_for=None):
    return Zone(key, temp, target, open_now, None if open_for is None else NOW - open_for)


def test_kalter_raum_oeffnet_ventile_pumpe_wartet():
    p = plan([zone()], now=NOW, source_temp=60)
    assert p.zones[WOHN] is True
    assert p.pump is False  # Ventile noch nicht offen


def test_pumpe_an_wenn_ventile_lange_genug_offen():
    p = plan([zone(open_now=True, open_for=200)], now=NOW, source_temp=60)
    assert p.pump is True


def test_kessel_zu_kalt_keine_pumpe():
    p = plan([zone(open_now=True, open_for=600)], now=NOW, source_temp=48)
    assert (p.source_ok, p.pump) == (False, False)


def test_kessel_hysterese():
    # einmal freigegeben, bleibt bis unter 45 °C
    assert plan([], now=NOW, source_temp=47, source_ok_before=True).source_ok is True
    assert plan([], now=NOW, source_temp=44, source_ok_before=True).source_ok is False
    assert plan([], now=NOW, source_temp=50, source_ok_before=False).source_ok is False


def test_kessel_grenze_einstellbar():
    assert plan([], now=NOW, source_temp=56, source_on=55).source_ok is True


def test_zone_schliesst_erst_bei_soll():
    assert plan([zone(temp=21.8, open_now=True, open_for=600)], now=NOW, source_temp=60).zones[WOHN] is True
    assert plan([zone(temp=22.0, open_now=True, open_for=600)], now=NOW, source_temp=60).zones[WOHN] is False


def test_zone_oeffnet_erst_unter_hysterese():
    assert plan([zone(temp=21.7)], now=NOW, source_temp=60).zones[WOHN] is False
    assert plan([zone(temp=21.4)], now=NOW, source_temp=60).zones[WOHN] is True


def test_abschalten_erst_pumpe_dann_ventile():
    warm = zone(temp=22.5, open_now=True, open_for=3600)
    p = plan([warm], now=NOW, source_temp=60, pump_on=True)
    assert (p.pump, p.zones[WOHN]) == (False, True)  # Pumpe aus, Ventile noch offen
    p = plan([warm], now=NOW, source_temp=60, pump_on=False)
    assert p.zones[WOHN] is False  # danach Ventile zu


def test_bad_ohne_sensor_wird_nicht_geschaltet():
    p = plan([zone(), Zone(BAD, None, 22.0, False, None)], now=NOW, source_temp=60)
    assert p.zones[BAD] is None
    assert p.problems == {BAD: "sensor_missing"}


def test_pumpe_laeuft_fuer_andere_zone_weiter():
    warm = zone(temp=22.5, open_now=True, open_for=3600)
    kalt = Zone(BAD, 19.0, 22.0, True, NOW - 3600)
    p = plan([warm, kalt], now=NOW, source_temp=60, pump_on=True)
    assert p.pump is True
    assert (p.zones[WOHN], p.zones[BAD]) == (False, True)
