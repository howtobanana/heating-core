"""Einrichtung über die Oberfläche."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_core.const import CONF_MANUFACTURER, DOMAIN

USER_INPUT = {"name": "Wien", CONF_MANUFACTURER: "vaillant"}


async def test_anlage_anlegen(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wien"
    assert result["data"] == USER_INPUT


async def test_nur_eine_anlage_pro_ha(hass: HomeAssistant) -> None:
    """Fabian, 09.11.2026: nur eine Anlage je HA-Instanz – auch mit anderem Namen keine zweite."""
    MockConfigEntry(domain=DOMAIN, unique_id="wien", data=USER_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_einrichten_und_entladen(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="wien", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.NOT_LOADED


async def test_optionen_boost_aus(hass: HomeAssistant) -> None:
    """Optionen lassen sich öffnen und speichern (Boost aus, Fabian 08.11.2026)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.heating_core.const import DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, title="P", unique_id="p", data={"name": "P", "manufacturer": "oekofen"},
                            options={"hysteresis": 0.8, "away_temp": 15.0})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert "Pellematic" in result["description_placeholders"]["hint"]  # Tipp je Hersteller
    defaults = {k.schema: k.default() for k in result["data_schema"].schema if callable(getattr(k, "default", None))}
    assert "weather_enabled" not in defaults and "weather_zone1" not in defaults
    assert not {"outdoor_sensor", "summer_entity", "summer_mean_sensor", "summer_limit"} & {str(k) for k in result["data_schema"].schema}  # Ökofen: Heizkurve kompensiert selbst
    # nur Festes im Formular: Regler-Werte und das Vaillant-Budget nicht (Fabian, 11.11.2026)
    keys = {str(k) for k in result["data_schema"].schema}
    assert not keys & {"eco_temp", "away_temp", "hysteresis", "budget_per_hour", "presence_activation_min",
                       "presence_deactivation_min", "window_delay_s", "window_settle_s", "pre_heat_timeout_min"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**defaults, "boost_enabled": False})
    assert result["type"] == "create_entry"
    assert entry.options["boost_enabled"] is False
    assert entry.options["hysteresis"] == 0.8 and entry.options["away_temp"] == 15.0  # bleiben erhalten


async def test_raum_zwei_schritte_und_feld_leeren(hass: HomeAssistant) -> None:
    """Raum: erst Name/Heizkreis/Rolle, dann nur passende Felder; geleerter Sensor ist danach weg."""
    from homeassistant.config_entries import ConfigSubentryData
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.heating_core.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN, title="P", unique_id="p", data={"name": "P", "manufacturer": "oekofen"},
        subentries_data=[ConfigSubentryData(data={"kind": "radiator", "master_climate": "climate.hk1"},
                                            subentry_id="hk1", subentry_type="circuit", title="HK1", unique_id=None)],
    )
    entry.add_to_hass(hass)
    r = await hass.config_entries.subentries.async_init((entry.entry_id, "room"), context={"source": "user"})
    assert set(str(k) for k in r["data_schema"].schema) == {"name", "circuit", "role"}
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {"name": "Büro", "circuit": "hk1", "role": "isolated"})
    assert r["step_id"] == "details"
    keys = set(str(k) for k in r["data_schema"].schema)
    assert "climate" in keys and "valves" not in keys and "offset" not in keys and "comfort" not in keys
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {"climate": "climate.trv", "temp_sensor": "sensor.t"})
    assert r["type"] == "create_entry"
    sub = next(s for s in entry.subentries.values() if s.title == "Büro")
    assert sub.data["temp_sensor"] == "sensor.t"
    # Neu konfigurieren: Sensor leeren
    r = await entry.start_subentry_reconfigure_flow(hass, sub.subentry_id)
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {"name": "Büro", "circuit": "hk1", "role": "isolated"})
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {"climate": "climate.trv"})
    assert r["reason"] == "reconfigure_successful"
    assert "temp_sensor" not in entry.subentries[sub.subentry_id].data
