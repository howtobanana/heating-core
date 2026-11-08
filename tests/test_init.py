"""Start ohne Frontend (Testgerüst): Integration läuft, Seite wird übersprungen."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_core.const import DOMAIN


async def test_start_ohne_frontend(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="T", unique_id="t", data={"name": "T", "manufacturer": "vaillant"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.data.get(f"{DOMAIN}_panel")
