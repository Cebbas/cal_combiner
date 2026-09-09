"""Shared fixtures for the Cal Combiner test suite.

Only tests that actually need a running Home Assistant instance (storage,
entities, ...) request the `hass` fixture explicitly - plain unit tests for
filter/rename/ICS logic run as sync functions with no event loop, and an
autouse dependency on `hass` would force one on them too.
"""
pytest_plugins = "pytest_homeassistant_custom_component"
