"""Regression tests for Home Assistant config-flow forms."""

from __future__ import annotations

import importlib.util
import unittest

HOME_ASSISTANT_AVAILABLE = importlib.util.find_spec("homeassistant") is not None


@unittest.skipUnless(HOME_ASSISTANT_AVAILABLE, "Home Assistant is not installed")
class ConfigFlowSchemaTests(unittest.TestCase):
    """Check schemas with Home Assistant's frontend serializer."""

    def test_details_schema_is_frontend_serializable(self) -> None:
        """Ensure opening the config flow cannot fail during serialization."""
        from probatio.codecs.fields import to_field_list

        from homeassistant.helpers import config_validation as cv

        from custom_components.hunter_node_bt.config_flow import (
            HunterNodeConfigFlow,
            HunterNodeOptionsFlow,
        )

        fields = to_field_list(
            HunterNodeConfigFlow._details_schema(),
            custom_serializer=cv.custom_serializer,
        )

        self.assertEqual([field["name"] for field in fields], ["pin"])

        option_fields = to_field_list(
            HunterNodeOptionsFlow._run_time_schema(600),
            custom_serializer=cv.custom_serializer,
        )
        self.assertEqual([field["name"] for field in option_fields], ["run_time"])
