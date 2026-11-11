"""Perg: Ökofen-Offset und externer Fußbodenkreis über den Valve-Koordinator."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.heating_core.adapters.oekofen import choose_mode, circuit_base, offset_for
from custom_components.heating_core.const import DOMAIN

HK1 = "climate.pellematic_heating_circuit_1_climate"
KESSEL = "sensor.pellematic_pellematic_1_l_temp_act"
WOHN_TEMP = "sensor.pellematic_heating_circuit_1_l_roomtemp_act"
L1, L2, L3, L4 = (f"switch.coordinator_fussbodenheizung_l{i}" for i in range(1, 5))


def test_kreis_basis():
    assert circuit_base(HK1) == "pellematic_heating_circuit_1"


def test_offset_rechnung():
    # Basis ist die Heiz- bzw. Absenktemperatur der Pellematic, nie l_roomtemp_set (HEATING-13)
    assert offset_for(22.0, 22.8) == -1.0  # ganze Kelvin, die Pellematic schneidet ab (HEATING-18)
    assert offset_for(24.5, 22.8) == 2.0
    assert offset_for(30.0, 20.0) == 3.0  # begrenzt auf ±3 K
    assert choose_mode(22.0, 22.8, 20.0) == "2_heizen"
    assert choose_mode(15.5, 20.0, 15.5) == "3_absenken"
    assert choose_mode(16.0, 20.0, 15.5) == "3_absenken"


def test_komfort_nie_ueber_absenken():
    # Perg UG 09.11.2026: Komfort 17 °C wurde zu „absenken“ 15,5 + 1 K -> Kreis über Heizgrenze aus (HEATING-18)
    assert choose_mode(17.0, 20.0, 15.5) == "2_heizen"
    assert offset_for(17.0, 20.0) == -3.0


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="Perg", unique_id="perg",
        data={"name": "Perg", "manufacturer": "oekofen"},
        options={"eco_temp": 19.0, "away_temp": 17.0, "min_trv_temp": 8.0, "presence_activation_min": 0},
        subentries_data=[
            ConfigSubentryData(data={"kind": "floor_external", "comfort": 22.0, "pump_switch": L1, "schedule": "schedule.immer",
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
    hass.states.async_set("schedule.immer", "on")  # ohne Zeitplan gilt Absenkung (Fabian 09.11.2026)
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
    hass.states.async_set("number.pellematic_heating_circuit_2_temp_heat", "20")
    hass.states.async_set("number.pellematic_heating_circuit_2_temp_setback", "15.5")
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


async def test_thermostat_je_zone(hass: HomeAssistant, perg) -> None:
    hass.states.async_set(L3, "on")  # Zone erst offen, wenn alle ihre Ventile offen sind
    await _setup(hass, _entry())
    # externer Fußbodenkreis hat keinen eigenen Sollwert -> kein Thermostat, seine Zonen schon
    assert hass.states.get("climate.hk3_fussboden") is None
    wohn = hass.states.get("climate.wohnzimmer_ug")
    assert (wohn.state, wohn.attributes["current_temperature"], wohn.attributes["temperature"]) == ("heat", 20.0, 22.0)
    assert wohn.attributes["hvac_action"] == "heating"  
    await hass.services.async_call("climate", "set_temperature", {"entity_id": "climate.wohnzimmer_ug", "temperature": 23.5}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("climate.wohnzimmer_ug").attributes["temperature"] == 23.5
    assert hass.states.get("number.wohnzimmer_ug_comfort").state == "23.5"  # gleicher Regler


HK1_B = "pellematic_heating_circuit_1"


def _hk1_states(hass, mode="1_auto", text="Heizbetrieb aktiv|Raumtemperatur erreicht"):
    """Werte aus HA Perg vom 08.11.2026, 20:45: l_roomtemp_set fällt auf 8 °C."""
    hass.states.async_set("schedule.immer", "on")
    hass.states.async_set(HK1, "auto", {"temperature": 8.0, "current_temperature": 21.0, "min_temp": 7, "max_temp": 35})
    hass.states.async_set(f"sensor.{HK1_B}_l_roomtemp_set", "8")
    hass.states.async_set(f"sensor.{HK1_B}_l_roomtemp_act", "21.0")
    hass.states.async_set(f"sensor.{HK1_B}_l_statetext", text)
    hass.states.async_set(f"number.{HK1_B}_temp_heat", "22.8")
    hass.states.async_set(f"number.{HK1_B}_temp_setback", "20")
    hass.states.async_set(f"number.{HK1_B}_remote_override", "0")
    hass.states.async_set(f"select.{HK1_B}_mode_auto", mode)


def _hk1_entry(schedule="schedule.immer") -> MockConfigEntry:
    data = {"kind": "radiator", "master_climate": HK1, "comfort": 22.0}
    if schedule:
        data["schedule"] = schedule
    return MockConfigEntry(
        domain=DOMAIN, title="P", unique_id="p", data={"name": "P", "manufacturer": "oekofen"},
        options={"eco_temp": 19.0, "presence_activation_min": 0, "boost_enabled": False},
        subentries_data=[
            ConfigSubentryData(data=data, subentry_id="hk1", subentry_type="circuit", title="HK1", unique_id=None),
            ConfigSubentryData(data={"circuit": "hk1", "role": "isolated", "climate": "climate.trv", "comfort": 21.0},
                               subentry_id="buero", subentry_type="room", title="Buero", unique_id=None),
        ],
    )


async def test_basis_ist_heiztemperatur_nicht_8_grad(hass: HomeAssistant) -> None:
    _hk1_states(hass)
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 20.0})
    coordinator = await _setup(hass, _hk1_entry())
    hk1 = coordinator.data["circuits"]["hk1"]
    assert hk1["set_now"] == 22.8  # nicht 8 °C


async def test_schreiben_uebernimmt_und_gibt_zurueck(hass: HomeAssistant) -> None:
    _hk1_states(hass)
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 20.0})
    hass.states.async_set("schedule.hk1", "off")
    coordinator = await _setup(hass, _hk1_entry(schedule="schedule.hk1"))
    sel = async_mock_service(hass, "select", "select_option")
    num = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "climate", "set_temperature")
    coordinator.control.setback["hk1"] = 20.0  # Absenkung wie die Pellematic
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()
    # Zeitplan aus -> Absenkung 20 °C -> Pellematic auf „absenken“, Offset 0 (bleibt unverändert)
    assert [c.data["option"] for c in sel] == ["3_absenken"]
    assert [c.data for c in num if c.data["entity_id"].endswith("remote_override")] == []
    # Schreiben aus: zurück auf auto
    hass.states.async_set(f"select.{HK1_B}_mode_auto", "3_absenken")
    hass.states.async_set(f"number.{HK1_B}_remote_override", "-0.5")
    sel.clear(); num.clear()
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.p_control_active"}, blocking=True)
    assert [c.data["option"] for c in sel] == ["1_auto"]
    assert [c.data["value"] for c in num] == [0]


async def test_raum_erbt_zeitplan_und_absenkung_vom_kreis(hass: HomeAssistant) -> None:
    _hk1_states(hass)
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 20.0})
    hass.states.async_set("schedule.hk1", "off")
    coordinator = await _setup(hass, _hk1_entry(schedule="schedule.hk1"))
    coordinator.control.setback["hk1"] = 18.0
    await coordinator.async_refresh()
    buero = coordinator.data["circuits"]["hk1"]["rooms"]["buero"]
    assert (buero["mode"], buero["target"]) == ("eco", 18.0)  # Plan des Kreises aus -> Absenkung des Kreises
    hass.states.async_set("schedule.hk1", "on")
    await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["rooms"]["buero"]["mode"] == "schedule"


async def test_eigene_absenkung_sperrt_rueckweg_nicht(hass: HomeAssistant) -> None:
    """Perg 08.11.2026 21:21: Abwesend kurz an -> absenken −3 -> Pellematic „aus“ (Heizgrenze).
    Danach muss Heating Core wieder auf Komfort zurückschreiben, statt „Kreis aus“ zu melden."""
    _hk1_states(hass, mode="3_absenken", text="Absenkbetrieb aktiv|Außentemp über Heizgrenze absenken")
    hass.states.async_set(f"number.{HK1_B}_remote_override", "-3")
    hass.states.async_set(HK1, "off", {"temperature": 8.0, "current_temperature": 21.0, "min_temp": 7, "max_temp": 35})
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 20.0})
    hass.states.async_set("schedule.hk1", "on")
    coordinator = await _setup(hass, _hk1_entry(schedule="schedule.hk1"))
    sel = async_mock_service(hass, "select", "select_option")
    num = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "climate", "set_temperature")
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["decision"] != "circuit_off"
    assert {c.data["option"] for c in sel} == {"2_heizen"}
    assert [c.data["value"] for c in num if c.data["entity_id"].endswith("remote_override")] == [-1.0]  # 22,0 − 22,8, auf ganze Kelvin


async def test_falsche_betriebsart_auch_in_hysterese(hass: HomeAssistant) -> None:
    """Perg UG 09.11.2026: „absenken“ + 1 für Ziel 17 °C liegt in der Hysterese (hier genau 17),
    die Absenk-Heizgrenze hält den Kreis trotzdem aus -> auf „heizen“ −3 umstellen (HEATING-18)."""
    _hk1_states(hass, mode="3_absenken", text="Absenkbetrieb aktiv|Außentemp über Heizgrenze absenken")
    hass.states.async_set(f"number.{HK1_B}_temp_heat", "20")
    hass.states.async_set(f"number.{HK1_B}_temp_setback", "16")
    hass.states.async_set(f"number.{HK1_B}_remote_override", "1")
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 22.0})
    hass.states.async_set("schedule.hk1", "on")
    entry = _hk1_entry(schedule="schedule.hk1")
    coordinator = await _setup(hass, entry)
    sel = async_mock_service(hass, "select", "select_option")
    num = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "climate", "set_temperature")
    coordinator.control.comfort["hk1"] = 17.0
    coordinator.control.setback["hk1"] = 16.0  # wie die Pellematic, sonst hebt Eco 19 °C das Ziel
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["would_write"] is False  # ohne Betriebsart-Prüfung bliebe es so
    assert {c.data["option"] for c in sel} == {"2_heizen"}
    assert [c.data["value"] for c in num if c.data["entity_id"].endswith("remote_override")] == [-3.0]


async def test_traeger_kessel_kurze_absenkung(hass: HomeAssistant) -> None:
    """HEATING-19: Absenkphase unter 3 h überspringen, 1 h früher Komfort."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util

    _hk1_states(hass, mode="2_heizen")
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 22.0})
    in_2h = (dt_util.now() + timedelta(hours=2)).isoformat()
    hass.states.async_set("schedule.hk1", "off", {"next_event": in_2h})  # schon vor dem Start aus (wie nach HA-Neustart)
    coordinator = await _setup(hass, _hk1_entry(schedule="schedule.hk1"))
    coordinator.control.setback["hk1"] = 18.0
    await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["target"] == 18.0  # HEATING-39: Länge unbekannt -> Absenkung
    hass.states.async_set("schedule.hk1", "on")
    hass.states.async_set("schedule.hk1", "off", {"next_event": in_2h})  # Wechsel selbst gesehen
    await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["target"] == 22.0  # 2-h-Lücke: bleibt auf Komfort
    assert coordinator.data["circuits"]["hk1"]["plan_hint"] == "skip"  # Seite erklärt es (HEATING-30)
    in_30m = (dt_util.now() + timedelta(minutes=30)).isoformat()
    hass.states.async_set("schedule.hk1", "off", {"next_event": in_30m})
    await coordinator.async_refresh()
    hk1 = coordinator.data["circuits"]["hk1"]
    assert (hk1["target"], hk1["plan_hint"], hk1["mode"]) == (22.0, "lead", "pre_heat")  # Vorlauf 1 h
    in_5h = (dt_util.now() + timedelta(hours=5)).isoformat()
    hass.states.async_set("schedule.hk1", "off", {"next_event": in_5h})
    await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["target"] == 18.0  # lange Absenkung bleibt
    assert "plan_hint" not in coordinator.data["circuits"]["hk1"]


async def test_zeitplan_zuordnen_per_websocket(hass: HomeAssistant, hass_ws_client) -> None:
    """HEATING-20: Der Editor legt einen HA-Zeitplan an und ordnet ihn über heating_core/assign_schedule zu."""
    _hk1_states(hass, mode="2_heizen")
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 22.0})
    entry = _hk1_entry()
    await _setup(hass, entry)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "heating_core/assign_schedule", "entity_id": "sensor.buero_setpoint", "schedule": "schedule.heizplan_buero"})
    res = await client.receive_json()
    assert res["success"], res
    assert entry.subentries["buero"].data["schedule"] == "schedule.heizplan_buero"
    await client.send_json({"id": 2, "type": "heating_core/assign_schedule", "entity_id": "sensor.buero_setpoint", "schedule": "light.x"})
    assert not (await client.receive_json())["success"]


async def test_kesseldaten_und_meldungen(hass: HomeAssistant) -> None:
    """HEATING-21: Kesseldaten der Ökofen-Integration, Diagnose als Problem, neue Meldung als Ereignis,
    keine Gebäude-Kompensation obendrauf (die Heizkurve der Pellematic kompensiert selbst)."""
    from custom_components.heating_core.notify import collect_problems

    _hk1_states(hass, mode="2_heizen")
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 22.0})
    hass.states.async_set("sensor.pellematic_l_ambient", "4.1")
    hass.states.async_set("sensor.pellematic_pe1_burner_starts_per_day", "5.1")
    hass.states.async_set("sensor.pellematic_pe1_burner_runtime_per_start", "161")
    hass.states.async_set("sensor.pellematic_diagnosis", "ok", {"summary": None})
    hass.states.async_set("sensor.pellematic_last_message", "PE 1 Pellets Warnung", {"time": "2026-11-09T12:57:37", "active": []})
    hass.states.async_set("select.pellematic_hot_water_1_use_boiler_heat", "0_aus")
    hass.states.async_set("sensor.aussen", "-12")
    hass.states.async_set("sensor.pellematic_pellematic_1_l_statetext", "Leistungsbrand")
    hass.states.async_set("sensor.pellematic_pellematic_1_l_modulation", "94")
    hass.states.async_set("binary_sensor.heizraum_pellematic_heating_circuit_1_l_pump", "off")
    entry = _hk1_entry()
    coordinator = await _setup(hass, entry)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "weather_enabled": True, "outdoor_sensor": "sensor.aussen", "weather_zone1": 3.0})
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    k = coordinator.data["boiler"]
    assert (k["outdoor"], k["starts_per_day"], k["runtime_per_start"]) == (4.1, 5.1, 161.0)
    assert (k["burner_text"], k["modulation"]) == ("Leistungsbrand", 94.0)  # HEATING-24
    assert coordinator.data["circuits"]["hk1"]["pump_on"] is False  # Pumpe aus -> Seite zeigt keinen Fluss
    assert k["dhw_boiler_heat"] == "select.pellematic_hot_water_1_use_boiler_heat"
    assert coordinator.data["circuits"]["hk1"]["target"] == 22.0  # kein +3 °C Wetter-Aufschlag
    assert collect_problems(coordinator.data) == []
    hass.states.async_set("sensor.pellematic_diagnosis", "cleaning_due", {"summary": "Brennkammer reinigen"})
    hass.states.async_set("sensor.pellematic_last_message", "PE 1 Saugturbine", {"time": "2026-11-09T18:00:00", "active": [{"text": "PE 1 Saugturbine"}]})
    await coordinator.async_refresh()
    assert collect_problems(coordinator.data) == ["🟡 Kessel: Reinigung fällig: Brennkammer reinigen", "🟠 Kessel meldet: PE 1 Saugturbine"]
    assert "Kessel meldet: PE 1 Saugturbine" in coordinator._events


async def test_heizkreis_ausschalten_und_wieder_an(hass: HomeAssistant) -> None:
    """HEATING-27: Kreis aus -> Pellematic „aus“, TRV auf Minimum; wieder an -> normale Regelung ohne Haltezeit."""
    _hk1_states(hass, mode="2_heizen")
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 20.0})
    coordinator = await _setup(hass, _hk1_entry())
    sel = async_mock_service(hass, "select", "select_option")
    async_mock_service(hass, "number", "set_value")
    temp = async_mock_service(hass, "climate", "set_temperature")
    coordinator.control.write_enabled = True
    with patch("custom_components.heating_core.coordinator.STARTUP_GUARD_S", 0):
        coordinator._started = 0
        await coordinator.set_disabled("hk1", True)
        await coordinator.async_refresh()
        hk1 = coordinator.data["circuits"]["hk1"]
        assert hk1["mode"] == "disabled"
        assert {c.data["option"] for c in sel} == {"0_aus"}  # Mock ändert den Zustand nicht, daher evtl. zweimal
        assert {c.data["temperature"] for c in temp} == {12.0}  # TRV-Minimum (Frostschutz)
        assert "hk1" in (await coordinator._store.async_load())["disabled"]  # übersteht Neustarts
        hass.states.async_set(f"select.{HK1_B}_mode_auto", "0_aus")
        sel.clear()
        await coordinator.set_disabled("hk1", False)
        await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["mode"] != "disabled"
    assert {c.data["option"] for c in sel} == {"2_heizen"}


async def test_raumfuehler_der_pellematic_sperrt_kreis(hass: HomeAssistant) -> None:
    """HEATING-29: „Raumtemperatur erreicht“, aber ein Raum braucht Wärme -> Hinweis, an der Pellematic umzustellen."""
    from custom_components.heating_core.notify import collect_problems

    _hk1_states(hass, mode="2_heizen", text="Heizbetrieb aktiv|Raumtemperatur erreicht")
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 15.0})  # Raum kalt
    coordinator = await _setup(hass, _hk1_entry())
    await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"]["problem"] == "room_sensor_blocks"
    assert any("Raumfühler der Pellematic" in p for p in collect_problems(coordinator.data))
    from homeassistant.helpers import issue_registry as ir
    issue = ir.async_get(hass).async_get_issue("heating_core", "room_sensor_blocks_hk1")
    assert issue and issue.is_fixable and issue.translation_placeholders == {"circuit": "HK1"}  # Einstellungen → Reparaturen
    hass.states.async_set("climate.trv", "heat", {"temperature": 21, "current_temperature": 22.0})  # Raum warm genug
    await coordinator.async_refresh()
    assert coordinator.data["circuits"]["hk1"].get("problem") is None
