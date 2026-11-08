"""Sensor: Zeitpunkt des letzten ausgeführten KNX-Befehls."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import KnxMediaPlayerConfigEntry
from .entity import KnxMediaPlayerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KnxMediaPlayerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([KnxLastCommandSensor(entry.runtime_data)])


class KnxLastCommandSensor(KnxMediaPlayerEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:knx"

    def __init__(self, controller) -> None:
        super().__init__(controller, "last_command")

    @property
    def native_value(self) -> datetime | None:
        last = self._controller.last_command
        return dt_util.parse_datetime(last["time"]) if last and last.get("time") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        last = self._controller.last_command
        if not last:
            return None
        return {key: value for key, value in last.items() if key != "time"}
