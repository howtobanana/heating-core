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


async def test_leitstand_expert_optional(hass: HomeAssistant, states) -> None:
    coordinator = await _setup(hass, _entry(leitstand_expert=True))
    created = async_mock_service(hass, "persistent_notification", "create")
    await _ready(coordinator)
    expert = [c.data for c in created if c.data["notification_id"].endswith("_expert")]
    assert expert and "Kreis: Soll" in expert[0]["message"] and "Büro" in expert[0]["message"]


async def test_system_diagnose_batterie_offline_stoerung_druck(hass: HomeAssistant, states) -> None:
    """HEATING-41: Diagnose meldet nur – Batterie über das Gerät des TRV, Fühler offline erst nach 15 min."""
    from homeassistant.helpers import entity_registry as er

    dev_entry = MockConfigEntry(domain="zha", title="ZHA")
    dev_entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=dev_entry.entry_id, identifiers={("zha", "trv")}, name="TRV Büro")
    reg = er.async_get(hass)
    trv_state = hass.states.get(TRV)
    hass.states.async_remove(TRV)  # sonst vergibt die Registry climate.trv_buero_2
    assert reg.async_get_or_create("climate", "zha", "trv", device_id=dev.id, suggested_object_id="trv_buero").entity_id == TRV
    hass.states.async_set(TRV, trv_state.state, trv_state.attributes)
    reg.async_get_or_create("sensor", "zha", "trv_bat", device_id=dev.id, suggested_object_id="trv_buero_batterie",
                            original_device_class="battery")
    hass.states.async_set("sensor.trv_buero_batterie", "12", {"friendly_name": "TRV Büro Batterie"})
    hass.states.async_set("binary_sensor.stoerung", "on", {"diagnostic_trouble_codes": "F.22"})
    hass.states.async_set("sensor.druck", "1.1")
    entry = _entry(error_entity="binary_sensor.stoerung", pressure_sensor="sensor.druck", pressure_min=1.0)
    coordinator = await _setup(hass, entry)
    created = async_mock_service(hass, "persistent_notification", "create")
    await _ready(coordinator)
    health = coordinator.data["health"]
    assert "🔋 Batterie schwach (unter 20 %): TRV Büro Batterie" in health
    assert "🚨 Heizung meldet Störung: F.22" in health
    assert "🟠 Wasserdruck unter 1,2 bar – bald nachfüllen" in health
    assert "F.22" in created[-1].data["message"]
    hass.states.async_set("sensor.druck", "0.9")
    hass.states.async_set("binary_sensor.stoerung", "off")
    await _ready(coordinator)
    assert coordinator.data["health"] == ["🔋 Batterie schwach (unter 20 %): TRV Büro Batterie",
                                          "🚨 Wasserdruck unter 1,0 bar – sofort nachfüllen"]


async def test_fuehler_offline_erst_nach_15_min(hass: HomeAssistant, states) -> None:
    from custom_components.heating_core.diagnose import health

    hass.states.async_set("sensor.fuehler", "unavailable", {"friendly_name": "Fühler Büro"})
    opt = {"battery_min": 20, "pressure_min": 1.0}.get
    assert health(hass, {"sensor.fuehler"}, opt, time.time()) == []
    assert health(hass, {"sensor.fuehler"}, opt, time.time() + 16 * 60) == ["📡 Seit über 15 min nicht erreichbar: Fühler Büro"]


async def test_briefing_einmal_am_tag_nicht_im_sommer(hass: HomeAssistant, states) -> None:
    from datetime import datetime

    from homeassistant.util import dt as dt_util

    phone_entry = MockConfigEntry(domain="mobile_app", title="iPhone")
    phone_entry.add_to_hass(hass)
    phone = dr.async_get(hass).async_get_or_create(config_entry_id=phone_entry.entry_id, identifiers={("mobile_app", "x")}, name="iPhone Fabian")
    hass.states.async_set("sensor.druck", "1.52")
    hass.states.async_set("input_boolean.sommer", "off")
    entry = _entry(notify_devices=[phone.id], briefing_time="19:00:00", pressure_sensor="sensor.druck", summer_entity="input_boolean.sommer")
    coordinator = await _setup(hass, entry)
    pushes = async_mock_service(hass, "notify", "mobile_app_iphone_fabian")
    async_mock_service(hass, "persistent_notification", "create")
    tz = dt_util.get_default_time_zone()

    def at(h, m, day=11):
        return patch("custom_components.heating_core.notify.dt_util.now", return_value=datetime(2026, 11, day, h, m, tzinfo=tz))

    with at(18, 55):
        await _ready(coordinator)
    assert not [p for p in pushes if "Briefing" in p.data["title"]]
    with at(19, 3):
        await _ready(coordinator)
    with at(19, 6):
        await _ready(coordinator)
    brief = [p for p in pushes if "Briefing" in p.data["title"]]
    assert len(brief) == 1 and "💧 Druck: 1,52 bar" in brief[0].data["message"] and "Heizkreise erreichbar" in brief[0].data["message"]
    hass.states.async_set("input_boolean.sommer", "on")
    with at(19, 3, day=12):
        await _ready(coordinator)
    assert len([p for p in pushes if "Briefing" in p.data["title"]]) == 1
