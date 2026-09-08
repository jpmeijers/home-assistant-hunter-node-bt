"""Exercise blueprint templates with representative duration sensor states."""

from __future__ import annotations

import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

ROOT = Path(__file__).parents[1]


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor(
    "!input", lambda loader, node: {"input": loader.construct_scalar(node)}
)


class States:
    def __init__(self, sensors):
        self.sensors = sensors

    def __call__(self, entity_id):
        return self.sensors[entity_id].state if entity_id in self.sensors else "unknown"

    def __getitem__(self, entity_id):
        return self.sensors[entity_id]


class BlueprintTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "blueprints/automation/hunter_node_bt/sync_daily_runtimes.yaml"
        self.blueprint = yaml.load(path.read_text(), Loader=BlueprintLoader)
        self.now = datetime.now(timezone.utc)
        self.sensors = {
            "sensor.pots": SimpleNamespace(
                state="240.2", last_reported=self.now, unit="s"
            ),
            "sensor.grass": SimpleNamespace(
                state="90", last_reported=self.now, unit="seconds"
            ),
        }
        self.variables = {
            "sources": {"1": "sensor.pots", "2": "sensor.grass"},
            "maximum_age": 36,
            "maximum_duration": 1800,
            "allow_zero": False,
        }

    def render(self):
        env = NativeEnvironment(undefined=StrictUndefined)

        def is_number(value):
            try:
                return math.isfinite(float(value))
            except (TypeError, ValueError):
                return False

        env.globals.update(
            states=States(self.sensors),
            is_number=is_number,
            now=lambda: self.now,
            as_timestamp=lambda value: value.timestamp(),
            state_attr=lambda entity_id, key: (
                self.sensors[entity_id].unit if key == "unit_of_measurement" else None
            ),
        )
        template = self.blueprint["actions"][0]["variables"]["runtime_values"]
        return env.from_string(template).render(**self.variables)

    def test_valid_sensor_values_round_up_once(self):
        self.assertEqual(self.render(), {"1": 241, "2": 90})
        action = self.blueprint["actions"][-1]
        self.assertEqual(action["action"], "hunter_node_bt.set_program")
        self.assertIs(action["data"]["require_daily_single_start"], True)
        self.assertNotIn("reset_bucket", json.dumps(self.blueprint))

    def test_bad_duration_rejects_whole_batch(self):
        for value in ("unknown", "unavailable", "nan", "inf", "-1", "0", "1800.1"):
            self.sensors["sensor.grass"].state = value
            with self.subTest(value=value):
                self.assertEqual(self.render(), {})

    def test_zero_requires_explicit_opt_in(self):
        self.sensors["sensor.grass"].state = "0"
        self.variables["allow_zero"] = True
        self.assertEqual(self.render(), {"1": 241, "2": 0})

    def test_missing_sensor_unit_or_stale_report_rejects_batch(self):
        del self.sensors["sensor.grass"]
        self.assertEqual(self.render(), {})
        self.sensors["sensor.grass"] = SimpleNamespace(
            state="90", last_reported=self.now, unit="min"
        )
        self.assertEqual(self.render(), {})
        self.sensors["sensor.grass"].unit = "s"
        self.sensors["sensor.grass"].last_reported = self.now - timedelta(hours=37)
        self.assertEqual(self.render(), {})
        self.sensors["sensor.grass"].last_reported = self.now + timedelta(hours=1)
        self.assertEqual(self.render(), {})

    def test_mapping_errors_reject_batch(self):
        for sources in (
            {},
            [],
            None,
            {"5": "sensor.pots"},
            {"1": None},
            {"1": "number.runtime"},
            {1: "sensor.pots", "1": "sensor.grass"},
        ):
            with self.subTest(sources=sources):
                self.variables["sources"] = sources
                self.assertEqual(self.render(), {})

    def test_service_descriptions_and_translations_are_consistent(self):
        component = ROOT / "custom_components/hunter_node_bt"
        services = yaml.safe_load((component / "services.yaml").read_text())
        strings = json.loads((component / "strings.json").read_text())
        english = json.loads((component / "translations/en.json").read_text())
        self.assertEqual(strings["entity"], english["entity"])
        self.assertEqual(strings["services"], english["services"])
        self.assertEqual(set(services), set(strings["services"]))
        self.assertEqual(
            set(services["set_program"]["fields"]),
            set(strings["services"]["set_program"]["fields"]),
        )
