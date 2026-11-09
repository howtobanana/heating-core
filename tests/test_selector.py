"""HEATING-26: Entitäts-Auswahl ohne Geräteklasse darf nicht leer filtern."""

from custom_components.heating_core.config_flow import _entity


def test_ohne_geraeteklasse_kein_filter():
    cfg = _entity("binary_sensor").serialize()["selector"]["entity"]
    assert not any(f.get("device_class") == [] for f in cfg.get("filter", [])), cfg
    assert "device_class" not in cfg or cfg["device_class"], cfg
