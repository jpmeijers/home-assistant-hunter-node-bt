"""Constants for the Hunter NODE-BT integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "hunter_node_bt"

ATTR_DURATION = "duration"
CONF_PIN = "pin"
CONF_RUN_TIME = "run_time"

DEFAULT_RUN_TIME = 600
MAX_RUN_TIME = 3600
MIN_RUN_TIME = 1
UPDATE_INTERVAL = timedelta(hours=1)

MESSAGE_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
MESSAGE_REQUEST = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
MESSAGE_RESPONSE = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
PIN_SERVICE = "0ed3e3d3-8cd8-4f29-8fec-a7d3a2c5443e"
PIN_CHARACTERISTIC = "4c9dbe52-3566-4dfc-a299-4ea1353970e2"

CONTROLLER_STATE_NAMES = {
    0: "idle",
    1: "manual_station",
    2: "system_off",
    3: "programmable_off",
    4: "rain_off",
    5: "rain_delay",
    6: "soil_off",
    7: "program_a",
    8: "program_b",
    9: "program_c",
    10: "manual_all",
    11: "manual_program_a",
    12: "manual_program_b",
    13: "manual_program_c",
}

STATION_ACTIVE_STATES = frozenset({1, 2, 3, 4, 5})
