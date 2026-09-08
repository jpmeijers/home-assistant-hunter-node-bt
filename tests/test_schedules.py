"""Schedule read/modify/verify tests using hardware fixtures and a fake BLE link."""

from __future__ import annotations

import asyncio
import json
import unittest
from copy import deepcopy

from custom_components.hunter_node_bt.models import HunterNodeData
from custom_components.hunter_node_bt.protocol import (
    HunterNodeController,
    HunterNodeProtocolError,
    HunterNodeScheduleUnverifiedError,
    HunterNodeSession,
)
from custom_components.hunter_node_bt.schedules import (
    DISABLED_START,
    HunterNodeProgram,
    build_program_patch,
    validate_daily_runtime_sync,
)

from .test_protocol import FIXTURES, FakeClient


def configuration():
    return json.loads(
        (FIXTURES / "node_bt_707796_read_all_2026-09-07.json").read_text()
    )


def state():
    return json.loads(
        (FIXTURES / "node_bt_707796_idle_state_2026-09-07.json").read_text()
    )


class ScheduleValidationTests(unittest.TestCase):
    def setUp(self):
        self.raw = configuration()["Program_A"]

    def test_models_expose_programs_and_disabled_slots(self):
        data = HunterNodeData.from_responses(configuration(), state())
        self.assertEqual([p.letter for p in data.programs], ["A", "B", "C"])
        attrs = data.programs[0].as_attributes(2)
        self.assertEqual(attrs["start_times"], ["13:30"] + [None] * 7)
        self.assertEqual(attrs["station_runtimes"], {"1": 180, "2": 60})
        self.assertEqual(
            attrs["weekdays"], ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        )
        self.assertIsNotNone(data.configuration_read_at.tzinfo)

    def test_patch_preserves_hidden_stations_and_unknown_fields(self):
        self.raw["RunTime"][3] = 77
        original = deepcopy(self.raw)
        patch = build_program_patch(self.raw, 2, {"station_runtimes": {"1": 240}})
        self.assertEqual(patch, {"RunTime": [240, 60, 0, 77]})
        self.assertEqual(original, self.raw)

    def test_accepts_station_count_shape(self):
        self.raw["RunTime"] = [180, 60]
        self.assertEqual(
            build_program_patch(self.raw, 2, {"station_runtimes": {2: 0}}),
            {"RunTime": [180, 0]},
        )

    def test_stored_long_runtime_is_readable_but_new_long_runtime_is_rejected(self):
        self.raw["RunTime"][0] = 7200
        self.assertEqual(HunterNodeProgram.from_raw("A", self.raw, 2).runtimes[0], 7200)
        with self.assertRaises(ValueError):
            build_program_patch(self.raw, 2, {"station_runtimes": {2: 3601}})

    def test_rejects_invalid_input(self):
        cases = [
            {},
            {"unsupported": 1},
            {"station_runtimes": {}},
            {"station_runtimes": {3: 30}},
            {"station_runtimes": {True: 30}},
            {"station_runtimes": {1: True}},
            {"station_runtimes": {1: -1}},
            {"station_runtimes": {1: 1.5}},
            {"station_runtimes": {1: "60"}},
            {"station_runtimes": {1: 20, "1": 30}},
            {"start_times": ["24:00"]},
            {"start_times": ["06:00:30"]},
            {"start_times": ["6:00"]},
            {"start_times": [360]},
            {"start_times": [None] * 9},
            {"start_time_slots": {0: "06:00"}},
            {"start_time_slots": {1: None, "1": None}},
            {"start_times": [], "start_time_slots": {1: None}},
            {"weekdays": ["monday"]},
            {"weekdays": [True]},
            {"weekdays": [], "weekday_flags": {"mon": True}},
            {"weekday_flags": {"mon": 1}},
            {"name": ""},
            {"name": "a" * 15},
            {"name": "é" * 8},
            {"name": "bad\u0000name"},
            {"start_times": ["06:00", "06:00"]},
            {"start_times": [], "station_runtimes": {1: 0}},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_program_patch(self.raw, 2, changes)

    def test_start_replacement_padding_and_slot_edits(self):
        self.assertEqual(
            build_program_patch(self.raw, 2, {"start_times": ["00:00", "23:59"]}),
            {"StartTimes": [0, 1439] + [DISABLED_START] * 6},
        )
        self.assertEqual(
            build_program_patch(self.raw, 2, {"start_time_slots": {"8": "06:00"}}),
            {"StartTimes": [360, 810] + [DISABLED_START] * 6},
        )
        self.assertEqual(
            build_program_patch(self.raw, 2, {"start_times": []}),
            {"StartTimes": [DISABLED_START] * 8},
        )

    def test_weekday_patch_preserves_unedited_bits(self):
        self.raw["ScheduleDays"] = 255
        self.assertEqual(
            build_program_patch(self.raw, 2, {"weekday_flags": {"mon": False}}),
            {"ScheduleDays": 254},
        )

    def test_program_name_limit_counts_utf8_bytes(self):
        self.assertEqual(
            build_program_patch(self.raw, 2, {"name": "12345678901234"}),
            {"Name": "12345678901234"},
        )
        self.assertEqual(
            build_program_patch(self.raw, 2, {"name": "é" * 7}),
            {"Name": "é" * 7},
        )

    def test_explicit_weekdays_switches_mode_but_individual_switch_refuses(self):
        self.raw.update(ScheduleType=2, IntervalDayCount=3, IntervalDayNext=1788739200)
        with self.assertRaises(ValueError):
            build_program_patch(self.raw, 2, {"weekday_flags": {"mon": True}})
        self.assertEqual(
            build_program_patch(self.raw, 2, {"weekdays": ["mon", "wed", "mon"]}),
            {
                "ScheduleType": 0,
                "ScheduleDays": 5,
                "IntervalDayCount": 0,
                "IntervalDayNext": 0,
            },
        )

    def test_malformed_program_is_not_treated_as_empty(self):
        for raw in (
            None,
            {},
            {**self.raw, "StartTimes": [360]},
            {**self.raw, "RunTime": [180]},
            {**self.raw, "StartTimes": [1440] * 8},
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                HunterNodeProgram.from_raw("A", raw, 2)

    def test_daily_sync_guard(self):
        source = configuration()
        changes = {"station_runtimes": {"1": 240}}
        validate_daily_runtime_sync(source, "A", changes)
        edits = [
            ("Controller", "SeasonAdjust", 80),
            ("Controller", "SeasonAdjustByMonthEnable", True),
            ("Program_A", "ScheduleDays", 5),
            ("Program_A", "ScheduleType", 2),
            ("Program_A", "StartTimes", [360, 420] + [DISABLED_START] * 6),
        ]
        for section, field, value in edits:
            with self.subTest(field=field), self.assertRaises(ValueError):
                altered = deepcopy(source)
                altered[section][field] = value
                validate_daily_runtime_sync(altered, "A", changes)
        source["Program_B"].update(
            StartTimes=[360] + [DISABLED_START] * 7, RunTime=[60, 0, 0, 0]
        )
        with self.assertRaisesRegex(ValueError, "another program"):
            validate_daily_runtime_sync(source, "A", changes)


class ScriptedSession(HunterNodeSession):
    """Exercise the actual schedule transaction logic with injected responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    async def transact(self, command):
        self.commands.append(deepcopy(command))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


class ScheduleTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_edit_matches_hardware_sorting_and_compaction(self):
        before = configuration()
        before["Program_B"]["StartTimes"] = [377, 1183] + [DISABLED_START] * 6
        after = deepcopy(before)
        after["Program_B"]["StartTimes"] = [377, 1439] + [DISABLED_START] * 6
        session = ScriptedSession([before, {"Status": 0}, after, state()])
        data = await session.set_program(
            "B", {"start_time_slots": {"2": None, "8": "23:59"}}
        )
        self.assertEqual(
            data.programs[1].start_times, tuple(after["Program_B"]["StartTimes"])
        )
        self.assertEqual(
            session.commands[1],
            {"Program_B": {"StartTimes": [377, 1439] + [DISABLED_START] * 6}},
        )

    async def test_combined_array_edit_is_rejected_before_write(self):
        session = ScriptedSession([configuration()])
        with self.assertRaisesRegex(ValueError, "separate actions"):
            await session.set_program(
                "B", {"start_times": [], "station_runtimes": {1: 0}}
            )
        self.assertEqual(session.commands, [{"Read": "All"}])

    async def test_verified_patch_with_backup_before_write(self):
        before = configuration()
        before["Program_A"]["FutureField"] = {"keep": 7}
        after = deepcopy(before)
        after["Program_A"]["RunTime"] = [240, 60, 0, 0]
        session = ScriptedSession([before, {"Status": 0}, after, state()])
        backups = []

        async def backup(letter, raw):
            self.assertEqual(session.commands, [{"Read": "All"}])
            backups.append((letter, raw))

        data = await session.set_program("A", {"station_runtimes": {1: 240}}, backup)
        self.assertEqual(data.programs[0].runtimes, (240, 60, 0, 0))
        self.assertEqual(backups, [("A", before["Program_A"])])
        self.assertEqual(
            session.commands,
            [
                {"Read": "All"},
                {"Program_A": {"RunTime": [240, 60, 0, 0]}},
                {"Read": "All"},
                {"Read": "Section_State"},
            ],
        )

    async def test_noop_does_not_write_or_replace_backup(self):
        session = ScriptedSession([configuration(), state()])

        async def backup(*args):
            self.fail("a no-op must not replace the recovery snapshot")

        await session.set_program("A", {"station_runtimes": {1: 180}}, backup)
        self.assertEqual(session.commands, [{"Read": "All"}, {"Read": "Section_State"}])

    async def test_unknown_field_readback_mismatch_is_unverified(self):
        before = configuration()
        before["Program_A"]["FutureField"] = 7
        after = deepcopy(before)
        after["Program_A"].update(RunTime=[240, 60, 0, 0], FutureField=8)
        session = ScriptedSession([before, {"Status": 0}, after])
        with self.assertRaises(HunterNodeScheduleUnverifiedError):
            await session.set_program("A", {"station_runtimes": {1: 240}})
        self.assertEqual(len(session.commands), 3)

    async def test_lost_ack_and_lost_readback_never_retry(self):
        for responses, count in (
            ([configuration(), TimeoutError()], 2),
            ([configuration(), {"Status": 0}, TimeoutError()], 3),
        ):
            session = ScriptedSession(responses)
            with (
                self.subTest(count=count),
                self.assertRaises(HunterNodeScheduleUnverifiedError),
            ):
                await session.set_program("A", {"station_runtimes": {1: 240}})
            self.assertEqual(len(session.commands), count)

    async def test_nonzero_or_malformed_status_is_failure(self):
        for status in (1, None, False, "0"):
            session = ScriptedSession([configuration(), {"Status": status}])
            with (
                self.subTest(status=status),
                self.assertRaises(HunterNodeProtocolError),
            ):
                await session.set_program("A", {"station_runtimes": {1: 240}})
            self.assertEqual(len(session.commands), 2)

    async def test_backup_failure_prevents_write(self):
        session = ScriptedSession([configuration()])

        async def backup(*args):
            raise OSError("disk full")

        with self.assertRaises(OSError):
            await session.set_program("A", {"station_runtimes": {1: 240}}, backup)
        self.assertEqual(session.commands, [{"Read": "All"}])

    async def test_bad_station_and_weather_guard_prevent_write(self):
        for changes in (
            {"station_runtimes": {3: 60}},
            {"name": "B", "require_daily_single_start": True},
        ):
            session = ScriptedSession([configuration()])
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await session.set_program("A", changes)
            self.assertEqual(session.commands, [{"Read": "All"}])

    async def test_fixture_roundtrip_over_fragmented_ble(self):
        before = configuration()
        after = deepcopy(before)
        after["Program_B"]["RunTime"] = [120, 0, 0, 0]
        client = FakeClient([before, {"Status": 0}, after, state()])
        session = HunterNodeSession(client, 0)
        await session.authenticate()
        data = await session.set_program("B", {"station_runtimes": {1: 120}})
        self.assertEqual(data.programs[1].runtimes, (120, 0, 0, 0))

    async def test_controllers_share_session_lock_across_reload(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        sessions = []

        class Controller(HunterNodeController):
            async def _with_session(self, operation):
                sessions.append(self)
                entered.set()
                await release.wait()

        lock = asyncio.Lock()
        old = Controller(None, 0, session_lock=lock)
        new = Controller(None, 0, session_lock=lock)
        first = asyncio.create_task(old.set_program("B", {"name": "Test"}))
        await entered.wait()
        second = asyncio.create_task(new.read_data())
        await asyncio.sleep(0)
        self.assertEqual(sessions, [old])
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(sessions, [old, new])

    async def test_controller_serializes_entire_operation_and_disconnects(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        class Controller(HunterNodeController):
            async def _with_session(self, operation):
                calls.append("session")
                entered.set()
                await release.wait()

        controller = Controller(None, 0)
        first = asyncio.create_task(
            controller.set_program("A", {"station_runtimes": {1: 30}})
        )
        await entered.wait()
        second = asyncio.create_task(controller.read_data())
        await asyncio.sleep(0)
        self.assertEqual(calls, ["session"])
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(calls, ["session", "session"])

        client = FakeClient([configuration()])
        disconnected = []

        async def disconnect():
            disconnected.append(True)

        client.disconnect = disconnect

        async def connect():
            return client

        with self.assertRaises(ValueError):
            await HunterNodeController(connect, 0).set_program(
                "A", {"station_runtimes": {3: 30}}
            )
        self.assertEqual(disconnected, [True])
