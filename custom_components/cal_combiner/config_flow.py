"""Config flow for Cal Combiner."""
from __future__ import annotations

import secrets

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CREATE_BINARY,
    CONF_CREATE_SENSOR,
    CONF_ENTRY_TYPE,
    CONF_FILTER,
    CONF_ICON,
    CONF_NAME,
    CONF_PICTURE,
    CONF_SOURCES,
    CONF_TOKEN,
    CONF_TRIGGER_MODE,
    DOMAIN,
    ENTRY_TYPE_ACTIVITY,
    ENTRY_TYPE_MERGE,
    FILTER_FIELDS,
    TRIGGER_MODE_ACTIVE,
    TRIGGER_MODES,
)


def _build_filter_from_flat_input(user_input: dict) -> dict | None:
    include = [w.strip() for w in user_input.get("include", "").split(",") if w.strip()]
    exclude = [w.strip() for w in user_input.get("exclude", "").split(",") if w.strip()]
    if not include and not exclude:
        return None
    return {
        "field": user_input.get("field", "any"),
        "include": include,
        "exclude": exclude,
        "use_regex": user_input.get("use_regex", False),
        "case_sensitive": user_input.get("case_sensitive", False),
    }


def _icon_and_picture_fields(defaults: dict) -> dict:
    return {
        vol.Optional(CONF_ICON, default=defaults.get(CONF_ICON, "")): selector.IconSelector(),
        vol.Optional(CONF_PICTURE, default=defaults.get(CONF_PICTURE, "")): selector.TextSelector(),
    }


def _activity_sensor_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    rule = defaults.get(CONF_FILTER) or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Aktivitet")): str,
            vol.Required(
                CONF_SOURCES, default=defaults.get(CONF_SOURCES, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="calendar", multiple=True)
            ),
            **_icon_and_picture_fields(defaults),
            vol.Optional("field", default=rule.get("field", "any")): vol.In(FILTER_FIELDS),
            vol.Optional("include", default=", ".join(rule.get("include", []))): str,
            vol.Optional("exclude", default=", ".join(rule.get("exclude", []))): str,
            vol.Optional("use_regex", default=rule.get("use_regex", False)): bool,
            vol.Optional("case_sensitive", default=rule.get("case_sensitive", False)): bool,
            vol.Optional(
                CONF_TRIGGER_MODE, default=defaults.get(CONF_TRIGGER_MODE, TRIGGER_MODE_ACTIVE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=TRIGGER_MODES,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_TRIGGER_MODE,
                )
            ),
            vol.Optional(
                "create_binary_sensor", default=defaults.get(CONF_CREATE_BINARY, True)
            ): bool,
            vol.Optional("create_sensor", default=defaults.get(CONF_CREATE_SENSOR, True)): bool,
        }
    )


class CalendarMergeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Lets the user create either a merged calendar or an activity sensor."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(
            step_id="user", menu_options=["merge_calendar", "activity_sensor"]
        )

    async def async_step_merge_calendar(self, user_input=None):
        if user_input is not None:
            data = dict(user_input)
            data[CONF_ENTRY_TYPE] = ENTRY_TYPE_MERGE
            data[CONF_TOKEN] = secrets.token_urlsafe(24)
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Merged Calendar"): str,
                vol.Optional(CONF_SOURCES, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar", multiple=True)
                ),
                **_icon_and_picture_fields({}),
            }
        )
        return self.async_show_form(step_id="merge_calendar", data_schema=schema)

    async def async_step_activity_sensor(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input[CONF_SOURCES]:
                errors["sources"] = "no_sources"
            elif not (user_input.get("create_binary_sensor") or user_input.get("create_sensor")):
                errors["create_binary_sensor"] = "no_sensor_type"
            else:
                data = {
                    CONF_ENTRY_TYPE: ENTRY_TYPE_ACTIVITY,
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_SOURCES: user_input[CONF_SOURCES],
                    CONF_ICON: user_input.get(CONF_ICON),
                    CONF_PICTURE: user_input.get(CONF_PICTURE),
                    CONF_FILTER: _build_filter_from_flat_input(user_input),
                    CONF_TRIGGER_MODE: user_input.get(CONF_TRIGGER_MODE, TRIGGER_MODE_ACTIVE),
                    CONF_CREATE_BINARY: user_input["create_binary_sensor"],
                    CONF_CREATE_SENSOR: user_input["create_sensor"],
                }
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="activity_sensor", data_schema=_activity_sensor_schema(), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CalendarMergeOptionsFlow()


class CalendarMergeOptionsFlow(config_entries.OptionsFlow):
    """Edit an existing merged calendar or activity sensor."""

    def __init__(self):
        self._filter_source: str | None = None

    async def async_step_init(self, user_input=None):
        if self.config_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MERGE) == ENTRY_TYPE_ACTIVITY:
            return await self.async_step_edit_activity_sensor()
        return self.async_show_menu(
            step_id="init", menu_options=["edit_sources", "edit_filters", "edit_appearance"]
        )

    # ---- Merged calendar options ----

    async def async_step_edit_sources(self, user_input=None):
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_SOURCES] = user_input[CONF_SOURCES]
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SOURCES, default=current.get(CONF_SOURCES, [])
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="edit_sources", data_schema=schema)

    async def async_step_edit_appearance(self, user_input=None):
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data[CONF_ICON] = user_input.get(CONF_ICON)
            new_data[CONF_PICTURE] = user_input.get(CONF_PICTURE)
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(_icon_and_picture_fields(self.config_entry.data))
        return self.async_show_form(step_id="edit_appearance", data_schema=schema)

    async def async_step_edit_filters(self, user_input=None):
        sources = self.config_entry.data.get(CONF_SOURCES, [])
        if not sources:
            return self.async_abort(reason="no_sources")

        if user_input is not None:
            self._filter_source = user_input["source"]
            return await self.async_step_filter_rules()

        schema = vol.Schema({vol.Required("source"): vol.In(sources)})
        return self.async_show_form(step_id="edit_filters", data_schema=schema)

    async def async_step_filter_rules(self, user_input=None):
        entity_id = self._filter_source
        filters = dict(self.config_entry.data.get("filters", {}))
        current = filters.get(entity_id, {})

        if user_input is not None:
            rule = _build_filter_from_flat_input(user_input)
            if rule:
                filters[entity_id] = rule
            else:
                filters.pop(entity_id, None)

            new_data = dict(self.config_entry.data)
            new_data["filters"] = filters
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Optional("field", default=current.get("field", "any")): vol.In(FILTER_FIELDS),
                vol.Optional("include", default=", ".join(current.get("include", []))): str,
                vol.Optional("exclude", default=", ".join(current.get("exclude", []))): str,
                vol.Optional(
                    "case_sensitive", default=current.get("case_sensitive", False)
                ): bool,
                vol.Optional("use_regex", default=current.get("use_regex", False)): bool,
            }
        )
        return self.async_show_form(
            step_id="filter_rules",
            data_schema=schema,
            description_placeholders={"entity_id": entity_id},
        )

    # ---- Activity sensor options ----

    async def async_step_edit_activity_sensor(self, user_input=None):
        errors: dict[str, str] = {}
        current = self.config_entry.data

        if user_input is not None:
            if not user_input[CONF_SOURCES]:
                errors["sources"] = "no_sources"
            elif not (user_input.get("create_binary_sensor") or user_input.get("create_sensor")):
                errors["create_binary_sensor"] = "no_sensor_type"
            else:
                new_data = dict(current)
                new_data[CONF_NAME] = user_input[CONF_NAME]
                new_data[CONF_SOURCES] = user_input[CONF_SOURCES]
                new_data[CONF_ICON] = user_input.get(CONF_ICON)
                new_data[CONF_PICTURE] = user_input.get(CONF_PICTURE)
                new_data[CONF_FILTER] = _build_filter_from_flat_input(user_input)
                new_data[CONF_TRIGGER_MODE] = user_input.get(CONF_TRIGGER_MODE, TRIGGER_MODE_ACTIVE)
                new_data[CONF_CREATE_BINARY] = user_input["create_binary_sensor"]
                new_data[CONF_CREATE_SENSOR] = user_input["create_sensor"]
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data, title=user_input[CONF_NAME]
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="edit_activity_sensor",
            data_schema=_activity_sensor_schema(current),
            errors=errors,
        )
