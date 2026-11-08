"""Vaillant-Adapter (HEATING-11): Quick-Veto erneuern, Sommer aus/an, Abweichung zum Blueprint."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.heating_core.adapters.vaillant import quick_veto_renew_due
from tests.test_coordinator import AWAY, ZONE, _entry, _setup, states  # noqa: F401 (Fixture)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def test_quick_veto_erneuern():
    assert quick_veto_renew_due("auto", NOW + timedelta(minutes=20), NOW)  # läuft bald ab
    assert not quick_veto_renew_due("auto", NOW + timedelta(hours=2), NOW)
    assert not quick_veto_renew_due("heat_cool", NOW + timedelta(minutes=5), NOW)  # Handbetrieb: kein Quick-Veto
    assert not quick_veto_renew_due("auto", "1970-01-01T01:00:00+01:00", NOW)  # mypyllant: keines aktiv


async def _run(coordinator):
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()


async def test_sommer_therme_aus_und_wieder_an(hass: HomeAssistant, states) -> None:
    summer = "input_boolean.sommer"
    hass.states.async_set(summer, "on")
    coordinator = await _setup(hass, _entry(summer_entity=summer))
    modes = async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    coordinator.control.write_enabled = True
    await _run(coordinator)
    assert [c.data["hvac_mode"] for c in modes] == ["off"]
    # Sommer vorbei, Therme steht auf aus -> Handbetrieb wieder
    hass.states.async_set(ZONE, "off", {"temperature": 19, "current_temperature": 20})
    hass.states.async_set(summer, "off")
    await _run(coordinator)
    assert [c.data["hvac_mode"] for c in modes] == ["off", "heat_cool"]


async def test_von_hand_aus_bleibt_aus(hass: HomeAssistant, states) -> None:
    """Hat jemand die Therme selbst ausgeschaltet (kein Sommer), schaltet Heating Core sie nicht ein."""
    hass.states.async_set(ZONE, "off", {"temperature": 19, "current_temperature": 20})
    coordinator = await _setup(hass, _entry())
    modes = async_mock_service(hass, "climate", "set_hvac_mode")
    coordinator.control.write_enabled = True
    await _run(coordinator)
    assert modes == []
    assert coordinator.data["circuits"]["kreis1"]["decision"] == "circuit_off"


async def test_abweichung_zum_blueprint(hass: HomeAssistant, states) -> None:
    await _setup(hass, _entry())
    # Präsenz -> Komfort 22, Blueprint/Anlage hat 19 gesetzt
    assert float(hass.states.get("sensor.kreis_deviation_from_system").state) == 3.0
