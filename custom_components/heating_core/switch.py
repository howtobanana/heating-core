"""Schalter je Anlage: Abwesend, Gast, Schreiben aktiv (Schattenbetrieb = aus)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import HeatingEntity

KEYS = ("away", "guest", "write_enabled")


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(ControlSwitch(entry.runtime_data, key) for key in KEYS)


class ControlSwitch(HeatingEntity, SwitchEntity, RestoreEntity):
    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            setattr(self.coordinator.control, self._key, last.state == "on")

    @property
    def is_on(self) -> bool:
        return getattr(self.coordinator.control, self._key)

    async def _set(self, value: bool) -> None:
        setattr(self.coordinator.control, self._key, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
