"""Registers the Cal Combiner sidebar panel and its static JS file."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_PANEL_URL_PATH = "cal-combiner"
_STATIC_URL = f"/{DOMAIN}_panel"
_REGISTERED = f"{DOMAIN}_panel_registered"


async def async_register_panel(hass: HomeAssistant) -> None:
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True

    www_dir = Path(__file__).parent / "www"

    try:
        # Newer Home Assistant cores (2024.7+)
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_URL, str(www_dir), False)]
        )
    except ImportError:
        # Older Home Assistant cores
        hass.http.register_static_path(_STATIC_URL, str(www_dir), False)

    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Cal Combiner",
        sidebar_icon="mdi:calendar-sync",
        frontend_url_path=_PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": "cal-combiner-panel",
                "embed_iframe": False,
                "trust_external": False,
                "js_url": f"{_STATIC_URL}/cal-combiner-panel.js?v=1",
            }
        },
        require_admin=True,
    )
