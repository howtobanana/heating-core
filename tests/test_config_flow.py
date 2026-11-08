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


async def test_gleiche_anlage_nur_einmal(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="wien", data=USER_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "name": " WIEN "}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


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

    entry = MockConfigEntry(domain=DOMAIN, title="P", unique_id="p", data={"name": "P", "manufacturer": "oekofen"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    defaults = {k.schema: k.default() for k in result["data_schema"].schema if callable(getattr(k, "default", None))}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**defaults, "boost_enabled": False})
    assert result["type"] == "create_entry"
    assert entry.options["boost_enabled"] is False


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
