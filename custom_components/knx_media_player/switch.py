"""Schalter: KNX-Steuerung dieses Media Players ein- oder ausschalten."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KnxMediaPlayerConfigEntry
from .entity import KnxMediaPlayerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KnxMediaPlayerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([KnxActiveSwitch(entry.runtime_data)])


class KnxActiveSwitch(KnxMediaPlayerEntity, SwitchEntity):
    _attr_icon = "mdi:knx"

    def __init__(self, controller) -> None:
        super().__init__(controller, "active")

    @property
    def is_on(self) -> bool:
        return self._controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_enabled(False)
