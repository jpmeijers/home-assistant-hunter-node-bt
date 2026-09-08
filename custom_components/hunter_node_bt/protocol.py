"""Asynchronous Hunter NODE-BT protocol implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any, Protocol

from .const import (
    MAX_RUN_TIME,
    MESSAGE_REQUEST,
    MESSAGE_RESPONSE,
    MIN_RUN_TIME,
    PIN_CHARACTERISTIC,
)
from .models import HunterNodeData
from .schedules import (
    PROGRAMS,
    HunterNodeProgram,
    build_program_patch,
    integer,
    validate_daily_runtime_sync,
)

NotificationCallback = Callable[[object, bytearray], None]
_LOGGER = logging.getLogger(__name__)


class BleakClientLike(Protocol):
    """Subset of BleakClient used by the protocol."""

    async def start_notify(
        self, characteristic: str, callback: NotificationCallback
    ) -> None: ...

    async def write_gatt_char(
        self, characteristic: str, data: bytes, *, response: bool
    ) -> None: ...

    async def disconnect(self) -> None: ...


ClientConnector = Callable[[], Awaitable[BleakClientLike]]


class HunterNodeError(Exception):
    """Base error raised by the Hunter NODE-BT protocol."""


class HunterNodeAuthenticationError(HunterNodeError):
    """The controller rejected authentication."""


class HunterNodeProtocolError(HunterNodeError):
    """The controller returned an invalid or unsuccessful response."""


class HunterNodeAmbiguousCommandError(HunterNodeError):
    """A control command may have reached the controller."""


class HunterNodeScheduleUnverifiedError(HunterNodeError):
    """A program write was attempted but its final configuration is unverified."""


def transform_pin_packet(packet: bytes) -> bytes:
    """Apply the symmetric PIN packet transform; zero bytes stay zero."""
    return bytes(value ^ 0xAC if value else 0 for value in packet)


def encode_pin_packet(
    packet_type: int, random_number: int = 0, pin_response: int = 0
) -> bytes:
    """Encode a six-byte PIN packet for transmission."""
    return transform_pin_packet(
        struct.pack("<BBHH", packet_type, 0, random_number, pin_response)
    )


def decode_pin_packet(packet: bytes) -> tuple[int, int, int, int]:
    """Decode and validate a PIN notification."""
    if len(packet) != 6:
        raise HunterNodeProtocolError(f"PIN packet has {len(packet)} bytes; expected 6")
    return struct.unpack("<BBHH", transform_pin_packet(packet))


def encode_json_chunks(command: object) -> tuple[bytes, ...]:
    """Encode compact JSON into the controller's 20-byte request chunks."""
    body = json.dumps(command, separators=(",", ":")).encode("utf-8")
    return tuple(body[offset : offset + 20] for offset in range(0, len(body), 20))


class HunterNodeSession:
    """One authenticated connection to a Hunter NODE-BT controller."""

    def __init__(
        self,
        client: BleakClientLike,
        pin: int,
        *,
        authentication_timeout: float = 15,
        response_timeout: float = 75,
    ) -> None:
        if pin not in range(10000):
            raise ValueError("PIN must be between 0000 and 9999")
        self._client = client
        self._pin = pin
        self._authentication_timeout = authentication_timeout
        self._response_timeout = response_timeout
        self._pin_packets: asyncio.Queue[bytes] = asyncio.Queue()
        self._response_future: asyncio.Future[dict[str, Any]] | None = None
        self._response = bytearray()
        self._last_fragment: bytes | None = None
        self._last_fragment_time = 0.0

    async def authenticate(self) -> None:
        """Subscribe to responses and complete the challenge exchange."""
        await self._client.start_notify(PIN_CHARACTERISTIC, self._on_pin)
        await self._client.start_notify(MESSAGE_RESPONSE, self._on_message)
        await self._client.write_gatt_char(
            PIN_CHARACTERISTIC, encode_pin_packet(1), response=False
        )
        challenge = await self._get_pin_packet()
        packet_type, result, random_number, _ = decode_pin_packet(challenge)
        if packet_type != 2 or result != 0:
            raise HunterNodeProtocolError(
                f"unexpected login challenge: type={packet_type}, result={result}"
            )

        await self._client.write_gatt_char(
            PIN_CHARACTERISTIC,
            encode_pin_packet(3, random_number, self._pin ^ random_number),
            response=False,
        )
        packet_type, result, _, _ = decode_pin_packet(await self._get_pin_packet())
        if packet_type != 4:
            raise HunterNodeProtocolError(
                f"unexpected login result packet: type={packet_type}"
            )
        if result != 0:
            raise HunterNodeAuthenticationError(
                f"controller rejected the PIN with result {result}"
            )

    async def transact(self, command: object) -> dict[str, Any]:
        """Send one JSON transaction and wait for its complete response."""
        if self._response_future is not None:
            raise HunterNodeProtocolError("another transaction is already active")
        loop = asyncio.get_running_loop()
        self._response.clear()
        self._last_fragment = None
        self._response_future = loop.create_future()
        try:
            for chunk in encode_json_chunks(command):
                await self._client.write_gatt_char(
                    MESSAGE_REQUEST, chunk, response=True
                )
            return await asyncio.wait_for(
                self._response_future, timeout=self._response_timeout
            )
        except TimeoutError as err:
            raise HunterNodeProtocolError("timed out waiting for response") from err
        finally:
            self._response_future = None
            self._response.clear()

    async def read_data(self) -> HunterNodeData:
        """Read configuration/telemetry and live state."""
        read_all = await self.transact({"Read": "All"})
        read_state = await self.transact({"Read": "Section_State"})
        return HunterNodeData.from_responses(read_all, read_state)

    async def start_station(self, station: int, duration: int) -> None:
        """Start one station with a controller-enforced duration."""
        if station not in range(1, 5):
            raise ValueError("station must be between 1 and 4")
        if duration not in range(MIN_RUN_TIME, MAX_RUN_TIME + 1):
            raise ValueError(
                f"duration must be between {MIN_RUN_TIME} and {MAX_RUN_TIME} seconds"
            )
        try:
            response = await self.transact(
                {"Manual": {"StationNumber": station, "RunTime": duration}}
            )
        except Exception as err:
            raise HunterNodeAmbiguousCommandError(
                "station start may have reached the controller"
            ) from err
        _require_success(response)

    async def set_program(
        self,
        letter: str,
        changes: dict[str, Any],
        save_backup: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> HunterNodeData:
        """Read, patch and verify in one session; never retry an uncertain write."""
        if letter not in PROGRAMS:
            raise ValueError("program must be A, B or C")
        before = await self.transact({"Read": "All"})
        count = integer(
            before.get("Controller", {}).get("StationCount"), 1, 4, "station count"
        )
        key = f"Program_{letter}"
        raw = before.get(key)
        HunterNodeProgram.from_raw(letter, raw, count)
        changes = dict(changes)
        require_daily = changes.pop("require_daily_single_start", False)
        if type(require_daily) is not bool:
            raise ValueError("require_daily_single_start must be a boolean")
        patch = build_program_patch(raw, count, changes)
        if require_daily:
            validate_daily_runtime_sync(before, letter, changes)
        if not patch:
            state = await self.transact({"Read": "Section_State"})
            return HunterNodeData.from_responses(before, state)
        if save_backup is not None:
            await save_backup(letter, deepcopy(raw))
        try:
            response = await self.transact({key: patch})
        except Exception as err:
            raise HunterNodeScheduleUnverifiedError(
                "program write may have reached the controller; refresh before retrying"
            ) from err
        _require_success(response)
        try:
            after = await self.transact({"Read": "All"})
            expected = {**raw, **patch}
            actual = after.get(key)
            if (
                not isinstance(actual, dict)
                or any(k not in actual for k in expected)
                or json.dumps({k: actual[k] for k in expected}, sort_keys=True)
                != json.dumps(expected, sort_keys=True)
            ):
                raise HunterNodeProtocolError(
                    "program readback does not match the requested configuration"
                )
            state = await self.transact({"Read": "Section_State"})
            return HunterNodeData.from_responses(after, state)
        except Exception as err:
            raise HunterNodeScheduleUnverifiedError(
                "program write acknowledged but verification did not complete; refresh before retrying"
            ) from err

    async def stop_all(self) -> None:
        """Stop every station. The controller treats this as idempotent."""
        _require_success(await self.transact({"Manual": {"StopAll": True}}))

    async def _get_pin_packet(self) -> bytes:
        try:
            return await asyncio.wait_for(
                self._pin_packets.get(), timeout=self._authentication_timeout
            )
        except TimeoutError as err:
            raise HunterNodeProtocolError("timed out during authentication") from err

    def _on_pin(self, _sender: object, data: bytearray) -> None:
        self._pin_packets.put_nowait(bytes(data))

    def _on_message(self, _sender: object, data: bytearray) -> None:
        future = self._response_future
        if future is None or future.done():
            return
        fragment = bytes(data)
        now = time.monotonic()
        if fragment == self._last_fragment and now - self._last_fragment_time < 0.1:
            return
        self._last_fragment = fragment
        self._last_fragment_time = now
        self._response.extend(fragment)
        terminator = self._response.find(0)
        if terminator < 0:
            return
        payload = bytes(self._response[:terminator])
        if any(self._response[terminator + 1 :]):
            future.set_exception(
                HunterNodeProtocolError("unexpected data after JSON response")
            )
            return
        try:
            decoded = json.loads(payload.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise HunterNodeProtocolError("JSON response is not an object")
        except (UnicodeDecodeError, json.JSONDecodeError, HunterNodeProtocolError):
            future.set_exception(HunterNodeProtocolError("invalid JSON response"))
        else:
            future.set_result(decoded)


class HunterNodeController:
    """Serialize short-lived sessions for one controller."""

    def __init__(
        self, connector: ClientConnector, pin: int, *, session_lock: asyncio.Lock | None = None
    ) -> None:
        self._connector = connector
        self._pin = pin
        self._lock = session_lock if session_lock is not None else asyncio.Lock()

    async def read_data(self) -> HunterNodeData:
        """Read a complete snapshot in one authenticated session."""
        async with self._lock:
            return await self._with_session(HunterNodeSession.read_data)

    async def start_station(self, station: int, duration: int) -> None:
        """Start a bounded manual run without retrying an ambiguous command."""
        async with self._lock:
            await self._with_session(
                lambda session: session.start_station(station, duration)
            )

    async def stop_all(self) -> None:
        """Stop all watering."""
        async with self._lock:
            await self._with_session(HunterNodeSession.stop_all)

    async def set_program(
        self,
        letter: str,
        changes: dict[str, Any],
        save_backup: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> HunterNodeData:
        """Hold the controller lock across fresh read, backup, write and verification."""
        changes = deepcopy(changes)
        async with self._lock:
            return await self._with_session(
                lambda session: session.set_program(letter, changes, save_backup)
            )

    async def _with_session(
        self, operation: Callable[[HunterNodeSession], Awaitable[Any]]
    ) -> Any:
        client = await self._connector()
        try:
            session = HunterNodeSession(client, self._pin)
            await session.authenticate()
            return await operation(session)
        finally:
            try:
                await client.disconnect()
            except Exception:
                _LOGGER.debug("Error disconnecting from NODE-BT", exc_info=True)


def _require_success(response: dict[str, Any]) -> None:
    status = response.get("Status")
    if type(status) is not int or status != 0:
        raise HunterNodeProtocolError(f"controller returned status {status!r}")
