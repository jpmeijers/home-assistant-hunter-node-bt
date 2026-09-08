"""Probe notifications must also be bounded without connecting to hardware."""

import asyncio
import unittest

from tests.test_protocol import FakeClient
from tools.ble_probe import (
    MAX_RESPONSE_BYTES,
    MESSAGE_RESPONSE,
    authenticate,
    transact_json,
)


class ProbeBufferTests(unittest.IsolatedAsyncioTestCase):
    async def test_authentication_and_normal_response(self):
        client = FakeClient([{"Status": 0}])
        await authenticate(client, 0)
        self.assertEqual(await transact_json(client, {"Read": "All"}), {"Status": 0})

    async def test_response_overflow_fails_promptly(self):
        client = FakeClient([])
        task = asyncio.create_task(transact_json(client, {"Read": "All"}))
        await asyncio.sleep(0)
        client.callbacks[MESSAGE_RESPONSE](None, bytearray(b"x" * MAX_RESPONSE_BYTES))
        client.callbacks[MESSAGE_RESPONSE](None, bytearray(b"y"))
        # More data after failure must not resume accumulation.
        client.callbacks[MESSAGE_RESPONSE](None, bytearray(b"z" * MAX_RESPONSE_BYTES))
        with self.assertRaisesRegex(ValueError, "size limit"):
            await asyncio.wait_for(task, 1)
