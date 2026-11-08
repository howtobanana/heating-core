"""Benachrichtigungen (HEATING-15): Problem-Meldung, TRV-Rücklesen, Push mit Ruhezeit."""

import time
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from tests.test_coordinator import TRV, ZONE, _entry, _setup, states  # noqa: F401 (Fixture)


async def _ready(coordinator, **patches):
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()


async def test_problem_meldung_kommt_und_geht(hass: HomeAssistant, states) -> None:
    coordinator = await _setup(hass, _entry())
    created = async_mock_service(hass, "persistent_notification", "create")
    dismissed = async_mock_service(hass, "persistent_notification", "dismiss")
    hass.states.async_set(TRV, "unavailable")
    await _ready(coordinator)
    assert len(created) == 1 and "Thermostat nicht erreichbar: Büro" in created[0].data["message"]
    await _ready(coordinator)
    assert len(created) == 1  # gleiches Problem -> keine neue Meldung
    hass.states.async_set(TRV, "heat", {"temperature": 19, "current_temperature": 20.5})
    await _ready(coordinator)
    assert len(dismissed) == 1


async def test_trv_antwortet_nicht(hass: HomeAssistant, states) -> None:
    hass.states.async_set(TRV, "heat", {"temperature": 19, "current_temperature": 18.0})  # Raum kalt -> Komfort schreiben
    coordinator = await _setup(hass, _entry())
    async_mock_service(hass, "climate", "set_temperature")  # TRV übernimmt den Wert nie
    async_mock_service(hass, "persistent_notification", "create")
    coordinator.control.write_enabled = True
    await _ready(coordinator)
    written = dict(coordinator.control.trv_writes)
    assert TRV in written
    with patch("custom_components.heating_core.coordinator.time.time", return_value=time.time() + 400):
        await _ready(coordinator)
    assert coordinator.data["circuits"]["kreis1"]["rooms"]["raum1"]["problem"] == "room_write_failed"


async def test_push_bei_schreiben_und_ruhezeit(hass: HomeAssistant, states) -> None:
    phone_entry = MockConfigEntry(domain="mobile_app", title="iPhone")
    phone_entry.add_to_hass(hass)
    phone = dr.async_get(hass).async_get_or_create(config_entry_id=phone_entry.entry_id, identifiers={("mobile_app", "x")}, name="iPhone Fabian")
    hass.states.async_set("schedule.ruhe", "off")
    entry = _entry(notify_devices=[phone.id], quiet_schedule="schedule.ruhe", push_enabled=True)
    coordinator = await _setup(hass, entry)
    pushes = async_mock_service(hass, "notify", "mobile_app_iphone_fabian")
    async_mock_service(hass, "climate", "set_temperature")
    async_mock_service(hass, "persistent_notification", "create")
    coordinator.control.write_enabled = True
    await _ready(coordinator)
    assert pushes and "Kreis: 19,0 → 22,0 °C" in pushes[-1].data["message"]
    # Ruhezeit: still
    pushes.clear()
    hass.states.async_set("schedule.ruhe", "on")
    hass.states.async_set("climate.trv_buero", "unavailable")
    await _ready(coordinator)
    assert pushes == []
