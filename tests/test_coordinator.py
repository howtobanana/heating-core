"""Integration mit Heizkreis und Raum: Schattenbetrieb, Schreiben, Abwesend."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.heating_core.const import DOMAIN

ZONE = "climate.zone"
TRV = "climate.trv_buero"
PRESENCE = "binary_sensor.praesenz_wohnzimmer"
AWAY = "input_boolean.abwesend"


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        unique_id="test",
        data={"name": "Test", "manufacturer": "vaillant"},
        options={"eco_temp": 19.0, "away_temp": 17.0, "min_trv_temp": 8.0, "hysteresis": 0.5,
                 "presence_activation_min": 0, "boost_enabled": False, "away_entities": [AWAY], **options},
        subentries_data=[
            ConfigSubentryData(data={"kind": "radiator", "master_climate": ZONE, "comfort": 22.0,
                                     "presence_sensors": [PRESENCE]},
                               subentry_id="kreis1", subentry_type="circuit", title="Kreis", unique_id=None),
            ConfigSubentryData(data={"circuit": "kreis1", "role": "isolated", "climate": TRV, "comfort": 21.0,
                                     "offset": -2.0, "schedule": IMMER},
                               subentry_id="raum1", subentry_type="room", title="Büro", unique_id=None),
        ],
    )


IMMER = "schedule.immer"


@pytest.fixture
def states(hass: HomeAssistant):
    hass.states.async_set(IMMER, "on")  # ohne Zeitplan gilt Absenkung (Fabian 09.11.2026) – Tests brauchen Komfort
    hass.states.async_set(ZONE, "heat_cool", {"temperature": 19, "current_temperature": 20, "min_temp": 7, "max_temp": 30})
    hass.states.async_set(TRV, "heat", {"temperature": 19, "current_temperature": 20.5})
    hass.states.async_set(PRESENCE, "on")
    hass.states.async_set(AWAY, "off")


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry.runtime_data


def _sensor(hass, name_part):
    return next(s for s in hass.states.async_all("sensor") if name_part in s.entity_id)


async def test_schattenbetrieb_rechnet_schreibt_nicht(hass: HomeAssistant, states) -> None:
    coordinator = await _setup(hass, _entry())
    kreis = _sensor(hass, "kreis")
    assert float(kreis.state) == 22.0  # Präsenz -> Komfort
    assert kreis.attributes["wuerde_schreiben"] is True
    calls = async_mock_service(hass, "climate", "set_temperature")
    await coordinator.async_refresh()
    assert calls == []
    assert hass.states.get("switch.test_writing_enabled").state == "off"


async def test_schreiben_aktiv_schreibt_master(hass: HomeAssistant, states) -> None:
    coordinator = await _setup(hass, _entry())
    # Platzhalter erst nach dem Start: die eigenen Thermostate laden den echten climate-Dienst
    calls = async_mock_service(hass, "climate", "set_temperature")
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.test_writing_enabled"}, blocking=True)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    targets = {c.data["entity_id"]: c.data["temperature"] for c in calls}
    assert targets[ZONE] == 22.0


async def test_abwesend_senkt(hass: HomeAssistant, states) -> None:
    hass.states.async_set(AWAY, "on")
    await _setup(hass, _entry())
    assert float(_sensor(hass, "kreis").state) == 17.0
    assert float(_sensor(hass, "buro").state) == 17.0


async def test_master_ohne_temperatur_schreibt_nicht(hass: HomeAssistant, states) -> None:
    hass.states.async_set(ZONE, "heat_cool", {"temperature": 19})
    await _setup(hass, _entry())
    kreis = _sensor(hass, "kreis")
    assert kreis.attributes["problem"] == "temperature_unknown"


async def test_modus_und_praesenz_sichtbar(hass: HomeAssistant, states) -> None:
    await _setup(hass, _entry())
    assert hass.states.get("sensor.kreis_mode").state == "presence"
    assert hass.states.get("binary_sensor.kreis_presence").state == "on"
    assert hass.states.get("binary_sensor.test_problem").state == "off"


async def test_vorheizen_ohne_praesenz(hass: HomeAssistant, states) -> None:
    hass.states.async_set(PRESENCE, "off")
    coordinator = await _setup(hass, _entry())
    assert float(_sensor(hass, "kreis_setpoint").state) == 19.0
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.kreis_pre_heat"}, blocking=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(_sensor(hass, "kreis_setpoint").state) == 22.0
    assert hass.states.get("sensor.kreis_mode").state == "pre_heat"


async def test_problem_melder(hass: HomeAssistant, states) -> None:
    hass.states.async_set(ZONE, "heat_cool", {"temperature": 19})
    await _setup(hass, _entry())
    problem = hass.states.get("binary_sensor.test_problem")
    assert problem.state == "on"
    assert "temperature_unknown" in problem.attributes["probleme"][0]


async def test_komfort_regler_wirkt_sofort(hass: HomeAssistant, states) -> None:
    coordinator = await _setup(hass, _entry())
    assert float(hass.states.get("number.kreis_comfort").state) == 22.0
    await hass.services.async_call("number", "set_value", {"entity_id": "number.kreis_comfort", "value": 23.5}, blocking=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(_sensor(hass, "kreis_setpoint").state) == 23.5


async def test_eco_regler(hass: HomeAssistant, states) -> None:
    hass.states.async_set(PRESENCE, "off")
    coordinator = await _setup(hass, _entry())
    await hass.services.async_call("number", "set_value", {"entity_id": "number.test_eco", "value": 18.0}, blocking=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(_sensor(hass, "kreis_setpoint").state) == 18.0


async def test_trv_wird_auch_ohne_master_geschrieben(hass: HomeAssistant, states) -> None:
    """HEATING-17: Master (Cloud) offline -> Raum mit offenem Fenster bekommt trotzdem das Minimum."""
    window = "binary_sensor.fenster_buero"
    hass.states.async_set(window, "on")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test", unique_id="test", data={"name": "Test", "manufacturer": "vaillant"},
        options={"eco_temp": 19.0, "min_trv_temp": 8.0, "window_delay_s": 10, "presence_activation_min": 0, "boost_enabled": False},
        subentries_data=[
            ConfigSubentryData(data={"kind": "radiator", "master_climate": ZONE, "comfort": 22.0, "schedule": IMMER},
                               subentry_id="kreis1", subentry_type="circuit", title="Kreis", unique_id=None),
            ConfigSubentryData(data={"circuit": "kreis1", "role": "isolated", "climate": TRV, "comfort": 21.0, "window": window},
                               subentry_id="raum1", subentry_type="room", title="Büro", unique_id=None),
        ],
    )
    coordinator = await _setup(hass, entry)
    hass.states.async_set(ZONE, "unavailable")
    calls = async_mock_service(hass, "climate", "set_temperature")
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0), \
         patch("custom_components.heating_core.coordinator.time.time", return_value=__import__("time").time() + 600):
        coordinator._started = 0
        await coordinator.async_refresh()
    assert coordinator.data["circuits"]["kreis1"]["problem"] == "master_unavailable"
    assert [c.data for c in calls] == [{"entity_id": TRV, "temperature": 8.0}]


async def test_trv_fehler_stoppt_andere_raeume_nicht(hass: HomeAssistant, states) -> None:
    from homeassistant.exceptions import HomeAssistantError

    trv2 = "climate.trv_kueche"
    hass.states.async_set(trv2, "heat", {"temperature": 15, "current_temperature": 18})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test", unique_id="test", data={"name": "Test", "manufacturer": "vaillant"},
        options={"eco_temp": 19.0, "min_trv_temp": 8.0, "presence_activation_min": 0, "boost_enabled": False},
        subentries_data=[
            ConfigSubentryData(data={"kind": "radiator", "master_climate": ZONE, "comfort": 22.0, "schedule": IMMER},
                               subentry_id="kreis1", subentry_type="circuit", title="Kreis", unique_id=None),
            ConfigSubentryData(data={"circuit": "kreis1", "role": "isolated", "climate": TRV, "comfort": 25.0},
                               subentry_id="raum1", subentry_type="room", title="Büro", unique_id=None),
            ConfigSubentryData(data={"circuit": "kreis1", "role": "isolated", "climate": trv2, "comfort": 25.0},
                               subentry_id="raum2", subentry_type="room", title="Küche", unique_id=None),
        ],
    )
    coordinator = await _setup(hass, entry)
    written = []

    async def handler(call):
        if call.data["entity_id"] in (TRV, [TRV]):
            raise HomeAssistantError("Funk weg")
        written.append(call.data["entity_id"])

    hass.services.async_register("climate", "set_temperature", handler)
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()
    rooms = coordinator.data["circuits"]["kreis1"]["rooms"]
    assert rooms["raum1"]["problem"] == "room_write_failed"
    assert trv2 in written or [trv2] in written


async def test_sommer_automatisch_aus_72h_mittel(hass: HomeAssistant, states) -> None:
    """HEATING-32: Sommer-Schalter folgt dem 72-h-Mittel (Heizgrenze 17 ±1,5), aber nur bei aktivem Schreiben."""
    hass.states.async_set("input_boolean.sommer", "off")
    hass.states.async_set("sensor.aussen_72h", "19.0")
    entry = _entry(summer_entity="input_boolean.sommer", summer_mean_sensor="sensor.aussen_72h", summer_limit=17.0)
    coordinator = await _setup(hass, entry)
    on = async_mock_service(hass, "input_boolean", "turn_on")
    await coordinator.async_refresh()
    assert not on  # Schattenbetrieb: der Blueprint schaltet
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        hass.states.async_set("sensor.aussen_72h", "18.0")  # im Band: nichts
        await coordinator.async_refresh()
        assert not on
        hass.states.async_set("sensor.aussen_72h", "18.5")
        await coordinator.async_refresh()
    assert [c.data["entity_id"] for c in on] == ["input_boolean.sommer"]
