"""Gemeinsame Fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """custom_components/ in jedem Test laden."""
    yield
