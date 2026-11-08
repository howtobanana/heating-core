"""Perg: Ökofen-Offset und externer Fußbodenkreis über den Valve-Koordinator."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.heating_core.adapters.oekofen import circuit_base, offset_for
from custom_components.heating_core.const import DOMAIN

HK1 = "climate.pellematic_heating_circuit_1_climate"
KESSEL = "sensor.pellematic_pellematic_1_l_temp_act"
WOHN_TEMP = "sensor.pellematic_heating_circuit_1_l_roomtemp_act"
L1, L2, L3, L4 = (f"switch.coordinator_fussbodenheizung_l{i}" for i in range(1, 5))


def test_kreis_basis():
    assert circuit_base(HK1) == "pellematic_heating_circuit_1"


def test_offset_rechnung():
    # Pellematic meldet 23,6 °C bei Offset 0; Ziel 22 °C -> Offset −1,6 K
    assert offset_for(22.0, 23.6, 0.0) == -1.6
    # gemeldeter Wert enthält bereits +1 K Offset
    assert offset_for(22.0, 23.0, 1.0) == 0.0
    # begrenzt auf ±3 K
    assert offset_for(30.0, 20.0, 0.0) == 3.0


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="Perg", unique_id="perg",
        data={"name": "Perg", "manufacturer": "oekofen"},
        options={"eco_temp": 19.0, "away_temp": 17.0, "min_trv_temp": 8.0, "presence_activation_min": 0},
        subentries_data=[
            ConfigSubentryData(data={"kind": "floor_external", "comfort": 22.0, "pump_switch": L1,
                                     "source_temp_sensor": KESSEL, "source_on": 50.0, "source_off": 45.0,
                                     "valve_delay_s": 0},
                               subentry_id="hk3", subentry_type="circuit", title="HK3 Fussboden", unique_id=None),
            ConfigSubentryData(data={"circuit": "hk3", "role": "floor_zone", "valves": [L2, L3], "comfort": 22.0,
                                     "temp_sensor": WOHN_TEMP},
                               subentry_id="wohn", subentry_type="room", title="Wohnzimmer UG", unique_id=None),
            ConfigSubentryData(data={"circuit": "hk3", "role": "floor_zone", "valves": [L4], "comfort": 22.0},
                               subentry_id="bad", subentry_type="room", title="Bad OG", unique_id=None),
        ],
    )


@pytest.fixture
def perg(hass: HomeAssistant):
    hass.states.async_set(KESSEL, "70.7")
    hass.states.async_set(WOHN_TEMP, "20.0")
    hass.states.async_set(L1, "off")
    hass.states.async_set(L2, "on")  # wie am 08.11.: 2 an, 3 aus
    hass.states.async_set(L3, "off")
    hass.states.async_set(L4, "on")


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry.runtime_data


async def test_schattenbetrieb_schaltet_nichts(hass: HomeAssistant, perg) -> None:
    coordinator = await _setup(hass, _entry())
    # Platzhalter erst nach dem Start: die Integration lädt selbst die echten switch-Dienste
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    await coordinator.async_refresh()
    hk3 = coordinator.data["circuits"]["hk3"]
    assert hk3["source_ok"] is True
    assert hk3["rooms"]["wohn"]["valves_wanted"] is True
    assert hk3["rooms"]["bad"]["problem"] == "sensor_missing"
    assert f"{L3} → an" in hk3["would_switch"]
    assert on == [] and off == []


async def test_aktiv_gleichlauf_und_bad_unberuehrt(hass: HomeAssistant, perg) -> None:
    coordinator = await _setup(hass, _entry())
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()
    switched_on = [c.data["entity_id"] for c in on]
    switched_off = [c.data["entity_id"] for c in off]
    assert L3 in switched_on  # Kanal 3 zieht mit Kanal 2 gleich
    assert L4 not in switched_on + switched_off  # Bad ohne Sensor wird nicht angefasst
    assert L1 not in switched_on  # Pumpe erst, wenn alle Ventile der Zone offen sind


async def test_kessel_kalt_keine_pumpe(hass: HomeAssistant, perg) -> None:
    hass.states.async_set(KESSEL, "40")
    hass.states.async_set(L3, "on")
    coordinator = await _setup(hass, _entry())
    hk3 = coordinator.data["circuits"]["hk3"]
    assert (hk3["source_ok"], hk3["pump_wanted"], hk3["mode"]) == (False, False, "source_cold")


async def test_kreis_aus_wird_nicht_uebersteuert(hass: HomeAssistant) -> None:
    hk2 = "climate.pellematic_heating_circuit_2_climate"
    hass.states.async_set(hk2, "off", {"temperature": 8.0, "current_temperature": 19.9})
    hass.states.async_set("sensor.pellematic_heating_circuit_2_l_roomtemp_set", "8.0")
    hass.states.async_set("number.pellematic_heating_circuit_2_remote_override", "0")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Perg2", unique_id="perg2",
        data={"name": "Perg2", "manufacturer": "oekofen"},
        options={"eco_temp": 19.0},
        subentries_data=[ConfigSubentryData(data={"kind": "radiator", "master_climate": hk2, "comfort": 20.0},
                                            subentry_id="hk2", subentry_type="circuit", title="HK2", unique_id=None)],
    )
    coordinator = await _setup(hass, entry)
    hk = coordinator.data["circuits"]["hk2"]
    assert (hk["decision"], hk["would_write"], hk["mode"]) == ("circuit_off", False, "circuit_off")
