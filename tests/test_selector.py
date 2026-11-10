"""HEATING-26: Entitäts-Auswahl ohne Geräteklasse darf nicht leer filtern."""

from custom_components.heating_core.config_flow import _entity


def test_ohne_geraeteklasse_kein_filter():
    cfg = _entity("binary_sensor").serialize()["selector"]["entity"]
    assert not any(f.get("device_class") == [] for f in cfg.get("filter", [])), cfg
    assert "device_class" not in cfg or cfg["device_class"], cfg


def test_praesenz_auch_input_boolean():
    """HEATING-33: Geofencing in Wien setzt input_boolean.presence_* – als Präsenzquelle wählbar."""
    from custom_components.heating_core.config_flow import _common
    from custom_components.heating_core.const import F_PRESENCE

    sel = next(v for k, v in _common({}).items() if str(k) == F_PRESENCE)
    cfg = sel.serialize()["selector"]["entity"]
    domains = set(cfg.get("domain") or []) | {d for f in cfg.get("filter", []) for d in f.get("domain", [])}
    assert {"binary_sensor", "input_boolean"} <= domains
