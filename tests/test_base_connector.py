"""Tests for base connector contract."""

import pytest

from src.connectors.base import BaseAdsConnector


def test_base_ads_connector_is_abstract() -> None:
    """The base connector cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseAdsConnector()
