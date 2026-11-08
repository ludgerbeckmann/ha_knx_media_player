"""KNX Media Player: Media Player über KNX-Gruppenadressen steuern."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import KnxMediaPlayerController

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

type KnxMediaPlayerConfigEntry = ConfigEntry[KnxMediaPlayerController]


async def async_setup_entry(hass: HomeAssistant, entry: KnxMediaPlayerConfigEntry) -> bool:
    controller = KnxMediaPlayerController(hass, entry)
    await controller.async_start()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KnxMediaPlayerConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: KnxMediaPlayerConfigEntry) -> None:
    await KnxMediaPlayerController(hass, entry).async_remove_data()


async def _async_reload(hass: HomeAssistant, entry: KnxMediaPlayerConfigEntry) -> None:
    """Einstellungen geändert: Eintrag neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)
