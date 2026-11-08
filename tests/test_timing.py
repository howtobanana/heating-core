"""Präsenz-Entprellung und Fenster-Zeiten."""

from custom_components.heating_core.timing import Reading, presence, window

NOW = 10_000.0
P = dict(now=NOW, activation_s=5 * 60, deactivation_s=30 * 60)


def test_kurzes_durchqueren_zaehlt_nicht():
    assert not presence([Reading("on", NOW - 60)], previous=False, **P)


def test_belegt_nach_aktivierungszeit():
    assert presence([Reading("on", NOW - 6 * 60)], previous=False, **P)


def test_ein_sensor_reicht():
    readings = [Reading("off", NOW - 3600), Reading("on", NOW - 600)]
    assert presence(readings, previous=False, **P)


def test_nachlauf_haelt_belegt():
    assert presence([Reading("off", NOW - 10 * 60)], previous=True, **P)


def test_frei_nach_nachlauf():
    assert not presence([Reading("off", NOW - 31 * 60)], previous=True, **P)


def test_unerreichbarer_sensor_aendert_nichts():
    readings = [Reading("off", NOW - 3600), Reading("unavailable", NOW - 3600)]
    assert presence(readings, previous=True, **P)


def test_ohne_sensoren_bleibt_zustand():
    assert presence([], previous=True, **P) is True


def test_fenster_offen_erst_nach_verzoegerung():
    assert not window(Reading("on", NOW - 10), now=NOW, open_delay_s=30, settle_s=180).open_too_long
    assert window(Reading("on", NOW - 31), now=NOW, open_delay_s=30, settle_s=180).open_too_long


def test_fenster_settling_nach_schliessen():
    w = window(Reading("off", NOW - 60), now=NOW, open_delay_s=30, settle_s=180)
    assert w.closed_recently and not w.open_too_long
    assert not window(Reading("off", NOW - 200), now=NOW, open_delay_s=30, settle_s=180).closed_recently


def test_kein_fenster():
    w = window(None, now=NOW, open_delay_s=30, settle_s=180)
    assert not w.open_too_long and not w.closed_recently
