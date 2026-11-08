"""Gemeinsame Basis der Entitäten: ein Gerät je Anlage, je Heizkreis und je Raum."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeatingCoordinator


class HeatingEntity(CoordinatorEntity[HeatingCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HeatingCoordinator,
        key: str,
        subentry_id: str | None = None,
        subentry_title: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        if subentry_id is None:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=entry.title,
                manufacturer="Heating Core",
                model=entry.data.get("manufacturer", "").capitalize(),
            )
        else:
            # HA: ein Gerät gehört genau einem Subentry -> eigenes Gerät je Heizkreis/Raum
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry.entry_id}_{subentry_id}")},
                name=subentry_title,
                manufacturer="Heating Core",
            )
