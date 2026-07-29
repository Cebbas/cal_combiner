"""Constants for Cal Combiner."""

DOMAIN = "cal_combiner"

CONF_SOURCES = "sources"
CONF_NAME = "name"
CONF_TOKEN = "token"
CONF_FILTERS = "filters"
CONF_ICON = "icon"
CONF_PICTURE = "picture"

# Distinguishes the two kinds of config entry this integration creates.
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_MERGE = "merge_calendar"
ENTRY_TYPE_ACTIVITY = "activity_sensor"

# Activity sensor specific config keys (single filter rule, not one per source).
CONF_FILTER = "filter"
CONF_CREATE_BINARY = "create_binary_sensor"
CONF_CREATE_SENSOR = "create_sensor"
CONF_TRIGGER_MODE = "trigger_mode"
TRIGGER_MODE_ACTIVE = "active_now"
TRIGGER_MODE_TODAY = "today"
TRIGGER_MODES = [TRIGGER_MODE_ACTIVE, TRIGGER_MODE_TODAY]

FILTER_FIELDS = ["any", "summary", "description", "location"]

DEFAULT_MERGE_ICON = "mdi:calendar-multiple"
DEFAULT_OWN_ICON = "mdi:calendar-heart"
DEFAULT_ACTIVITY_ICON = "mdi:calendar-check"

PLATFORMS_MERGE = ["calendar"]
PLATFORMS_ACTIVITY = ["binary_sensor", "sensor"]
