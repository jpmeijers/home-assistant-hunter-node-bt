"""Tests based on captured Hunter NODE-BT protocol samples."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from custom_components.hunter_node_bt.const import (
    MESSAGE_REQUEST,
    MESSAGE_RESPONSE,
    PIN_CHARACTERISTIC,
)
from custom_components.hunter_node_bt.models import HunterNodeData
from custom_components.hunter_node_bt.protocol import (
    MAX_RESPONSE_BYTES,
    HunterNodeProtocolError,
    HunterNodeSession,
    decode_pin_packet,
    encode_json_chunks,
    encode_pin_packet,
    transform_pin_packet,
)

FIXTURES = Path(__file__).parents[1] / "captures"


class FakeClient:
    """Small fake that implements the protocol's Bleak client subset."""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.callbacks = {}
        self.responses = list(responses)
        self.writes: list[tuple[str, bytes, bool]] = []
        self.request = bytearray()

    async def start_notify(self, characteristic: str, callback: object) -> None:
        self.callbacks[characteristic] = callback

    async def write_gatt_char(
        self, characteristic: str, data: bytes, *, response: bool
    ) -> None:
        self.writes.append((characteristic, bytes(data), response))
        if characteristic == PIN_CHARACTERISTIC:
            packet_type, _, _, _ = decode_pin_packet(data)
            callback = self.callbacks[PIN_CHARACTERISTIC]
            if packet_type == 1:
                callback(None, bytearray(encode_pin_packet(2, 0x1234)))
            elif packet_type == 3:
                callback(None, bytearray(encode_pin_packet(4)))
            return

        self.request.extend(data)
        try:
            json.loads(self.request)
        except json.JSONDecodeError:
            return
        if not self.responses:
            return
        payload = json.dumps(self.responses.pop(0), separators=(",", ":")).encode()
        callback = self.callbacks[MESSAGE_RESPONSE]
        for offset in range(0, len(payload), 7):
            callback(None, bytearray(payload[offset : offset + 7]))
        callback(None, bytearray(b"\0"))
        self.request.clear()

    async def disconnect(self) -> None:
        pass


class ProtocolEncodingTests(unittest.TestCase):
    def test_pin_transform_preserves_zero_bytes(self) -> None:
        packet = b"\x01\x00\xac\xff"
        self.assertEqual(transform_pin_packet(packet), b"\xad\x00\x00\x53")

    def test_pin_packet_round_trip(self) -> None:
        packet = encode_pin_packet(3, 0x1234, 0x5678)
        self.assertEqual(decode_pin_packet(packet), (3, 0, 0x1234, 0x5678))

    def test_json_is_compact_and_chunked(self) -> None:
        command = {"Manual": {"StationNumber": 1, "RunTime": 60}}
        chunks = encode_json_chunks(command)
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
        self.assertEqual(b"".join(chunks), b'{"Manual":{"StationNumber":1,"RunTime":60}}')


class ProtocolSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pin_flood_is_not_queued_after_expected_packet(self) -> None:
        class FloodClient(FakeClient):
            async def write_gatt_char(self, characteristic, data, *, response):
                await super().write_gatt_char(characteristic, data, response=response)
                if characteristic == PIN_CHARACTERISTIC:
                    for _ in range(100):
                        self.callbacks[PIN_CHARACTERISTIC](None, bytearray(b"noise!"))

        client = FloodClient([])
        session = HunterNodeSession(client, 0)
        await session.authenticate()
        self.assertIsNone(session._pin_future)
        client.callbacks[PIN_CHARACTERISTIC](None, bytearray(b"x" * 100000))
        self.assertIsNone(session._pin_future)

    async def test_invalid_pin_length_fails_authentication_promptly(self) -> None:
        class InvalidClient(FakeClient):
            async def write_gatt_char(self, characteristic, data, *, response):
                self.callbacks[PIN_CHARACTERISTIC](None, bytearray(b"x" * 100000))

        session = HunterNodeSession(InvalidClient([]), 0)
        with self.assertRaisesRegex(HunterNodeProtocolError, "PIN packet length"):
            await asyncio.wait_for(session.authenticate(), 1)
        self.assertIsNone(session._pin_future)

    async def test_response_limit_rejects_single_and_fragmented_overflow(self) -> None:
        for fragments in (
            [b"x" * (MAX_RESPONSE_BYTES + 1)],
            [b"x" * (MAX_RESPONSE_BYTES // 2), b"y" * (MAX_RESPONSE_BYTES // 2), b"z"],
        ):
            client = FakeClient([])
            session = HunterNodeSession(client, 0)
            await session.authenticate()
            task = asyncio.create_task(session.transact({"Read": "All"}))
            await asyncio.sleep(0)
            for fragment in fragments:
                session._on_message(None, bytearray(fragment))
            with self.assertRaisesRegex(HunterNodeProtocolError, "size limit"):
                await asyncio.wait_for(task, 1)
            self.assertEqual(session._response, bytearray())

    async def test_response_at_limit_and_following_transaction_work(self) -> None:
        client = FakeClient([])
        session = HunterNodeSession(client, 0)
        await session.authenticate()
        task = asyncio.create_task(session.transact({"Read": "All"}))
        await asyncio.sleep(0)
        payload = b'{"x":"' + b'a' * (MAX_RESPONSE_BYTES - 9) + b'"}\0'
        self.assertEqual(len(payload), MAX_RESPONSE_BYTES)
        session._on_message(None, bytearray(payload))
        self.assertEqual(len((await task)["x"]), MAX_RESPONSE_BYTES - 9)
        # The next transaction gets its own bounded accumulator.
        task = asyncio.create_task(session.transact({"Read": "All"}))
        await asyncio.sleep(0)
        session._on_message(None, bytearray(b'{"ok":true}\0'))
        self.assertEqual(await task, {"ok": True})

    async def test_authenticates_reads_fragmented_samples(self) -> None:
        read_all = json.loads(
            (FIXTURES / "node_bt_707796_read_all_2026-09-07.json").read_text()
        )
        read_state = json.loads(
            (FIXTURES / "node_bt_707796_idle_state_2026-09-07.json").read_text()
        )
        client = FakeClient([read_all, read_state])
        session = HunterNodeSession(client, 0)

        await session.authenticate()
        data = await session.read_data()

        self.assertEqual(data.serial_number, "16707796")
        self.assertEqual(data.firmware_version, "2.2A")
        self.assertEqual(data.battery, 60)
        self.assertEqual([station.name for station in data.stations], ["Pots", "Grass"])
        self.assertEqual([station.remaining for station in data.stations], [0, 0])

    async def test_start_and_stop_use_verified_commands(self) -> None:
        client = FakeClient([{"Status": 0}, {"Status": 0}])
        session = HunterNodeSession(client, 0)
        await session.authenticate()

        await session.start_station(2, 120)
        await session.stop_all()

        message = b"".join(
            data
            for characteristic, data, _ in client.writes
            if characteristic == MESSAGE_REQUEST
        )
        self.assertEqual(
            message,
            b'{"Manual":{"StationNumber":2,"RunTime":120}}'
            b'{"Manual":{"StopAll":true}}',
        )

    async def test_ignores_immediately_repeated_response_fragment(self) -> None:
        client = FakeClient([])
        session = HunterNodeSession(client, 0)
        await session.authenticate()
        task = asyncio.create_task(session.transact({"Read": "Section_State"}))
        await asyncio.sleep(0)
        callback = client.callbacks[MESSAGE_RESPONSE]
        callback(None, bytearray(b'{"State":'))
        callback(None, bytearray(b'{"State":'))
        callback(None, bytearray(b'{"ControllerState":0}}\0'))
        self.assertEqual(await task, {"State": {"ControllerState": 0}})


class ModelTests(unittest.TestCase):
    def test_invalid_station_count_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported station count"):
            HunterNodeData.from_responses(
                {"Controller": {"StationCount": 8}}, {"State": {}}
            )


if __name__ == "__main__":
    unittest.main()
