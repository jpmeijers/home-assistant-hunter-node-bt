"""BLE discovery and protocol probe for Hunter NODE-BT controllers."""

from __future__ import annotations

import argparse
import asyncio
import json
import struct

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

MESSAGE_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
MESSAGE_REQUEST = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
MESSAGE_RESPONSE = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
PIN_SERVICE = "0ed3e3d3-8cd8-4f29-8fec-a7d3a2c5443e"
PIN_CHARACTERISTIC = "4c9dbe52-3566-4dfc-a299-4ea1353970e2"

READ_COMMANDS = {
    "all": {"Read": "All"},
    "controller": {"Read": "Section_Controller"},
    "sensor": {"Read": "Section_Sensor"},
    "state": {"Read": "Section_State"},
    "last-run": {"Read": "LastRun"},
}


def _pin_obfuscate(data: bytes) -> bytes:
    """Apply the app's byte-wise XOR transform (zero bytes stay zero)."""
    return bytes(value ^ 0xAC if value else 0 for value in data)


def _pin_packet(packet_type: int, random_number: int = 0, pin: int = 0) -> bytes:
    return _pin_obfuscate(struct.pack("<BBHH", packet_type, 0, random_number, pin))


def _service_match(_device: BLEDevice, advertisement: AdvertisementData) -> bool:
    return MESSAGE_SERVICE in {uuid.lower() for uuid in advertisement.service_uuids}


async def find_controller(timeout: float, address: str | None) -> BLEDevice | None:
    if address:
        return await BleakScanner.find_device_by_address(address, timeout=timeout)

    found: dict[str, tuple[BLEDevice, AdvertisementData]] = {}

    def on_advertisement(device: BLEDevice, advertisement: AdvertisementData) -> None:
        if _service_match(device, advertisement):
            found[device.address] = (device, advertisement)
            display_name = advertisement.local_name or device.name or ""
            print(
                f"NODE-BT candidate: {device.address} "
                f"name={display_name!r} "
                f"rssi={advertisement.rssi}"
            )

    scanner = BleakScanner(on_advertisement, service_uuids=[MESSAGE_SERVICE])
    async with scanner:
        await asyncio.sleep(timeout)

    if not found:
        return None
    return max(found.values(), key=lambda item: item[1].rssi)[0]


async def authenticate(client: BleakClient, pin: int) -> None:
    packets: asyncio.Queue[tuple[int, int, int, int]] = asyncio.Queue()

    def on_pin(_sender: object, encrypted: bytearray) -> None:
        plain = _pin_obfuscate(bytes(encrypted))
        if len(plain) == 6:
            packets.put_nowait(struct.unpack("<BBHH", plain))

    await client.start_notify(PIN_CHARACTERISTIC, on_pin)
    await client.write_gatt_char(PIN_CHARACTERISTIC, _pin_packet(1), response=False)
    packet_type, result, random_number, _ = await asyncio.wait_for(
        packets.get(), timeout=15
    )
    if packet_type != 2 or result != 0:
        raise RuntimeError(
            f"unexpected login challenge: type={packet_type}, result={result}"
        )

    encrypted_pin = pin ^ random_number
    await client.write_gatt_char(
        PIN_CHARACTERISTIC,
        _pin_packet(3, random_number, encrypted_pin),
        response=False,
    )
    packet_type, result, _, _ = await asyncio.wait_for(packets.get(), timeout=15)
    if packet_type != 4 or result != 0:
        raise RuntimeError(f"login rejected: type={packet_type}, result={result}")


async def transact_json(client: BleakClient, command: object) -> object:
    complete = asyncio.Event()
    response = bytearray()

    def on_message(_sender: object, data: bytearray) -> None:
        response.extend(data)
        if 0 in data:
            complete.set()

    await client.start_notify(MESSAGE_RESPONSE, on_message)
    body = json.dumps(command, separators=(",", ":")).encode()
    for offset in range(0, len(body), 20):
        await client.write_gatt_char(
            MESSAGE_REQUEST, body[offset: offset + 20], response=True
        )
    await asyncio.wait_for(complete.wait(), timeout=75)
    payload = bytes(response).split(b"\0", 1)[0]
    return json.loads(payload)


async def probe(args: argparse.Namespace) -> None:
    device = await find_controller(args.timeout, args.address)
    if device is None:
        raise SystemExit(
            f"No device advertising {MESSAGE_SERVICE} was found in {args.timeout:g}s"
        )
    if (
            args.read is None
            and args.start_station is None
            and not args.stop
            and args.command_json is None
    ):
        return

    async with BleakClient(device, timeout=20) as client:
        print(f"connected: {device.address}")
        for service in client.services:
            print(f"service {service.uuid}")
            for characteristic in service.characteristics:
                print(
                    f"  characteristic {characteristic.uuid} "
                    f"properties={','.join(characteristic.properties)}"
                )
        await authenticate(client, args.pin)
        print("login accepted")
        if args.command_json is not None:
            command = args.command_json
        elif args.read is not None:
            command = READ_COMMANDS[args.read]
        elif args.start_station is not None:
            command = {
                "Manual": {
                    "StationNumber": args.start_station,
                    "RunTime": args.duration,
                }
            }
        else:
            command = {"Manual": {"StopAll": True}}
        print(f"command: {json.dumps(command, separators=(',', ':'))}")
        print(json.dumps(await transact_json(client, command), indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--address", help="connect to a known BLE address")
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--read",
        choices=READ_COMMANDS,
        help="authenticate and issue one read-only command",
    )
    action.add_argument(
        "--start-station",
        type=int,
        choices=range(1, 5),
        metavar="1..4",
        help="start one station for the bounded --duration",
    )
    action.add_argument(
        "--stop",
        action="store_true",
        help="stop all running stations",
    )
    action.add_argument(
        "--command-json",
        type=json.loads,
        metavar="JSON",
        help="authenticate and transact one raw JSON object",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        choices=range(1, 301),
        metavar="1..300",
        help="manual station run time in seconds (default: 60, maximum: 300)",
    )
    parser.add_argument("--pin", type=int, default=0, choices=range(10000))
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(probe(parse_args()))
