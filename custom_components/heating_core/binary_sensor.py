"""Präsenz (entprellt) je Heizkreis/Raum und Problem-Melder je Anlage."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUB_CIRCUIT, SUB_ROOM
from .entity import HeatingEntity
from .sensor import _find


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([Problem(coordinator)])
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUB_CIRCUIT or (sub.subentry_type == SUB_ROOM and sub.data.get("role") != "follower"):
            if sub.data.get("presence_sensors"):
                async_add_entities([Presence(coordinator, sid, sub.title, sub.subentry_type == SUB_CIRCUIT)], config_subentry_id=sid)


class Presence(HeatingEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "presence"

    def __init__(self, coordinator, sid: str, title: str, circuit: bool) -> None:
        super().__init__(coordinator, f"{sid}_presence", sid, title)
        self._sid, self._circuit = sid, circuit

    @property
    def is_on(self):
        return _find(self.coordinator, self._sid, self._circuit).get("presence")


class Problem(HeatingEntity, BinarySensorEntity):
    """An, sobald ein Heizkreis oder Raum nicht gerechnet/geschrieben werden kann."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "problem"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "problem")

    def _problems(self) -> list[str]:
        out = []
        for c in ((self.coordinator.data or {}).get("circuits") or {}).values():
            if c.get("problem"):
                out.append(f"{c.get('name')}: {c['problem']}")
            for r in c.get("rooms", {}).values():
                if r.get("problem"):
                    out.append(f"{r.get('name')}: {r['problem']}")
        return out

    @property
    def is_on(self) -> bool:
        return bool(self._problems())

    @property
    def extra_state_attributes(self):
        return {"probleme": self._problems()}
