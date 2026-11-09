"""Schreib-Entscheidung: Budget, Holds, Bestätigung, Erneuern, Startschutz."""

from custom_components.heating_core.writes import Write, WriteConfig, decide

CFG = WriteConfig(budget_per_hour=13, hysteresis=0.5)
NOW = 1_000_000.0


def d(**kw):
    base = dict(now=NOW, target=21.0, set_now=19.0, writes=[], cfg=CFG)
    base.update(kw)
    return decide(**base)


def test_erhoehen():
    r = d()
    assert (r.write, r.kind) == (True, "raise")


def test_kein_write_ohne_unterschied():
    assert d(target=19.0).reason == "no_delta"


def test_erhoehen_nur_ueber_hysterese():
    assert d(target=19.5).reason == "within_hysteresis"


def test_absenken_auch_kleine_schritte():
    r = d(target=18.5)
    assert (r.write, r.kind) == (True, "drop")


def test_startschutz():
    assert d(startup_done=False).reason == "startup"


def test_soll_null_wird_ignoriert():
    assert d(set_now=0).reason == "no_setpoint"
    assert d(set_now=None).reason == "no_setpoint"


def test_gleicher_wert_nicht_doppelt_vaillant5():
    # 13:04 geschrieben, Cloud meldet um 13:07 noch den alten Wert -> kein zweiter Write
    writes = [Write(NOW - 180, 17.0, "drop")]
    assert d(target=17.0, set_now=21.0, writes=writes).reason == "pending_confirmation"


def test_gleicher_wert_nach_bestaetigungsfrist_wieder_erlaubt():
    writes = [Write(NOW - 31 * 60, 17.0, "drop")]
    assert d(target=17.0, set_now=21.0, writes=writes).write


def test_budget_erschoepft():
    writes = [Write(NOW - 60 * i - 60, 19.0 + i % 2, "sync") for i in range(13)]
    assert d(writes=writes).reason == "budget"


def test_budget_zaehlt_nur_letzte_stunde():
    writes = [Write(NOW - 3700, 19.0, "sync")] * 13
    assert d(writes=writes).write


def test_forced_min_ohne_budget():
    writes = [Write(NOW - 60 * i - 60, 19.0 + i % 2, "sync") for i in range(13)]
    r = d(target=8.0, writes=writes, forced_min=True)
    assert (r.write, r.reason) == (True, "forced_min")


def test_hold_absenken_nach_erhoehen():
    writes = [Write(NOW - 5 * 60, 21.0, "raise")]
    assert d(target=20.5, set_now=21.0, writes=writes).reason == "hold_drop"


def test_starkes_absenken_trotz_hold():
    writes = [Write(NOW - 5 * 60, 21.0, "raise")]
    assert d(target=19.0, set_now=21.0, writes=writes).reason == "significant_drop"


def test_hold_erhoehen_nach_absenken_und_bypass():
    writes = [Write(NOW - 5 * 60, 19.0, "drop")]
    assert d(writes=writes).reason == "hold_raise"
    assert d(writes=writes, bypass=True).write  # z. B. Präsenz-/Fenster-Ereignis


def test_erneuern_vaillant2():
    # Quick-Veto läuft bald ab: denselben Wert erneut schreiben
    r = d(target=17.0, set_now=17.0, renew_due=True)
    assert (r.write, r.reason) == (True, "renew")


def test_budget_grenzen():
    assert WriteConfig(budget_per_hour=2).budget == 5
    assert WriteConfig(budget_per_hour=50).budget == 20


def test_ohne_budget_bei_oekofen():
    """Ökofen hat kein Schreib-Budget (Fabian, 09.11.2026): auch nach vielen Writes wird geschrieben."""
    from custom_components.heating_core.writes import Write, WriteConfig, decide
    writes = [Write(1000 + i, 20 + i % 2, "drop") for i in range(30)]
    cfg = WriteConfig(budget_limited=False)
    d = decide(now=1100, target=17.0, set_now=20.0, writes=writes, cfg=cfg)
    assert d.write and d.reason != "budget"
    assert decide(now=1100, target=17.0, set_now=20.0, writes=writes, cfg=WriteConfig()).reason == "budget"


# Träger Kessel (Ökofen, HEATING-19): Haltezeit 2 h, Hysterese in beide Richtungen
GENTLE = WriteConfig(hysteresis=1.0, budget_limited=False, min_hold_s=7200, symmetric_hysteresis=True)


def test_traeger_kessel_haelt_zwei_stunden():
    last = [Write(NOW - 3600, 21.0, "raise")]
    assert d(cfg=GENTLE, target=17.0, set_now=21.0, writes=last).reason == "hold_min"
    assert d(cfg=GENTLE, target=17.0, set_now=21.0, writes=[Write(NOW - 7300, 21.0, "raise")]).write


def test_traeger_kessel_ereignis_hebt_haltezeit_auf():
    last = [Write(NOW - 600, 21.0, "raise")]
    assert d(cfg=GENTLE, target=16.0, set_now=21.0, writes=last, bypass=True).write
    assert d(cfg=GENTLE, target=16.0, set_now=21.0, writes=last, away=True).write


def test_traeger_kessel_hysterese_auch_beim_absenken():
    assert d(cfg=GENTLE, target=20.2, set_now=21.0).reason == "within_hysteresis"
    assert d(cfg=GENTLE, target=21.8, set_now=21.0).reason == "within_hysteresis"
    assert d(cfg=GENTLE, target=19.5, set_now=21.0).write
