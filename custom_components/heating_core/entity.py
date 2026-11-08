"""Gemeinsame Basis der Entitäten: ein Gerät je Anlage."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeatingCoordinator


class HeatingEntity(CoordinatorEntity[HeatingCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HeatingCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Heating Core",
            model=entry.data.get("manufacturer", "").capitalize(),
        )
