"""TRV-Abgleich mit Raumfühler (HEATING-16)."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.heating_core.trv import new_calibration, step_round
from tests.test_perg import _hk1_entry, _hk1_states, _setup


def test_schrittweite():
    assert step_round(22.5, 1) == 23.0
    assert step_round(22.4, 1) == 22.0
    assert step_round(21.3, 0.5) == 21.5
    assert step_round(21.3, None) == 21.3


def test_kalibrierung():
    # Büro OG: TRV zeigt 21 bei Kalibrierung +2, Raumfühler 19,3 -> Kalibrierung 0
    assert new_calibration(19.3, 21.0, 2.0) == 0.0
    assert new_calibration(21.4, 21.0, 2.0) is None  # unter 0,5 °C: ganze Grad würden es nicht ändern
    assert new_calibration(10.0, 25.0, 0.0) == -9.0  # Grenze des TRV
    assert new_calibration(22.0, 21.0, 1.0) == 2.0


async def test_trv_gehorcht_und_wird_abgeglichen(hass: HomeAssistant) -> None:
    _hk1_states(hass, mode="2_heizen")
    other = MockConfigEntry(domain="mqtt")
    other.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id, identifiers={("mqtt", "trv")})
    reg = er.async_get(hass)
    for domain, oid in (("climate", "trv"), ("number", "trv_local_temperature_calibration"), ("switch", "trv_eco_mode")):
        reg.async_get_or_create(domain, "mqtt", oid, suggested_object_id=oid, device_id=dev.id, config_entry=other)
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 21.0, "target_temp_step": 1,
                                                  "preset_modes": ["programming", "manual"], "preset_mode": "programming"})
    hass.states.async_set("number.trv_local_temperature_calibration", "2", {"min": -9, "max": 9, "step": 1})
    hass.states.async_set("switch.trv_eco_mode", "on")
    hass.states.async_set("sensor.raum", "19.3")
    entry = _hk1_entry()
    coordinator = await _setup(hass, entry)
    sub = entry.subentries["buero"]
    hass.config_entries.async_update_subentry(entry, sub, data={**sub.data, "temp_sensor": "sensor.raum"})
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    num = async_mock_service(hass, "number", "set_value")
    sw = async_mock_service(hass, "switch", "turn_off")
    pre = async_mock_service(hass, "climate", "set_preset_mode")
    temp = async_mock_service(hass, "climate", "set_temperature")
    async_mock_service(hass, "select", "select_option")
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()
    assert [c.data["entity_id"] for c in sw] == ["switch.trv_eco_mode"]
    assert [c.data["preset_mode"] for c in pre] == ["manual"]
    assert [c.data["value"] for c in num if c.data["entity_id"] == "number.trv_local_temperature_calibration"] == [0.0]
    assert all(c.data["temperature"] == int(c.data["temperature"]) for c in temp)  # ganze Grad wie der TRV
    num.clear()
    await coordinator.async_refresh()
    assert [c for c in num if c.data["entity_id"] == "number.trv_local_temperature_calibration"] == []  # höchstens alle 30 min
