# Hunter NODE-BT investigation

## Current conclusion

The NODE-BT uses a custom authenticated JSON protocol over two BLE services. The protocol is sufficiently understood and
hardware-verified to implement a local Home Assistant integration for discovery, authentication, status reads, battery
reporting, timed station control, emergency stop, and schedule reads. Schedule modification is also understood, but
should use read-modify-write and readback verification. [PROTOCOL.md](PROTOCOL.md) is the normative technical
specification; this file records how the result was reached and what remains.

No application-level encryption protects control JSON. The only custom authentication is a six-byte PIN challenge
exchange using a byte transform and a 16-bit XOR challenge response. Commands are compact UTF-8 JSON split into 20-byte
writes, and responses are NUL-terminated JSON indications. The controller enforces manual run durations after the client
disconnects.

## Android application analysis

The official package is `com.hunter.nodev2`. The analysed signed base APK is version `6.0.611246` (`versionCode` 611246)
with SHA-256
`748773ccb6aeb61518f279206b6e706ebfbf1377f68154730b68d7b73d982a2d`. Its signing-certificate SHA-256 is
`57af395ac5a145f7a032ca6516e3e46124ac63a2c7c65ed4667e50028685a099`.

The app is .NET MAUI. Its meaningful code is stored as LZ4-compressed managed assemblies in an Android XABA
assembly-store payload, so ordinary Java decompilation is not sufficient. `tools/unpack_assembly_store.py` extracts the
XALZ assemblies for ILSpy. The main evidence came from `BleGuids`,
`BleDeviceCommunication`, `DevicePinInfo`, and `Commands` in
`NodeV2.Services.dll` and `NodeV2.Service.Interface.dll`, plus the schedule view models in `NodeV2.ViewModelsMaui.dll`.

The app supplied the UUIDs, scan filter, authentication packet layout, all JSON command builders, message fragmentation,
response termination, state enums, schedule encodings, telemetry models, and retry/serialization behavior. Direct
hardware tests were then used to distinguish working behavior from static inference. The attached Pixel 8 was available
and authorized through ADB, but neither APK extraction from the phone nor Bluetooth HCI snoop capture was needed.

## Hardware validation — 7 September 2026

The official Android app was decompiled and its protocol was reproduced directly from the computer's Bluetooth adapter.
The connected two-station controller accepted PIN `0000`, returned controller and live-state data, started stations 1
and 2, and accepted an explicit stop command. The user physically confirmed that each station command opened the
corresponding water line.

A separate 15-second run continued after the BLE client disconnected and was idle on a later state read, confirming that
the controller enforces the requested duration itself. The Android phone and Bluetooth traffic capture were not needed.
The complete UUIDs, authentication exchange, JSON framing, commands, observed hardware versions, and probe examples are
in [PROTOCOL.md](PROTOCOL.md).

The resident schedule was also read and backed up. Program A runs every day at 13:30: station 1 (`Pots`) for 180
seconds, followed by station 2 (`Grass`) for 60 seconds. Programs B and C are empty. Tests on Program B confirmed
partial and complete schedule modification, clearing start times with the `65535` sentinel, zeroing runtimes, and
restoring the original program. The global
`ControllerOff` flag was toggled and restored. A final full read verified that Program A was unchanged, Programs B and C
were empty, and the controller was enabled.

The final full-read fixture is
[`captures/node_bt_707796_read_all_2026-09-07.json`](captures/node_bt_707796_read_all_2026-09-07.json), the idle state
is
[`captures/node_bt_707796_idle_state_2026-09-07.json`](captures/node_bt_707796_idle_state_2026-09-07.json), and the
concise schedule backup is
[`captures/node_bt_707796_schedules_2026-09-07.json`](captures/node_bt_707796_schedules_2026-09-07.json).

The tested device was `NODE-BT-707796`, serial `16707796`, with two stations, controller firmware `2.2A`, bootloader
`1.00`, and Bluetooth firmware `1.02`. BLE RSSI varied roughly from -56 to -78 dBm. Discovery was intermittent: some
10-, 20-, and 30-second windows saw no advertisement, and one cached-address connection timed out. Repeating a
service-filtered scan produced a fresh device object and connected successfully. This should directly shape retry
behavior in the integration.

## Handoff status and limits

Completed and hardware-verified:

- Service-filtered discovery and the control/authentication GATT inventory.
- PIN `0000` login without BLE pairing or bonding.
- Controller, sensor, full configuration, and idle-state reads.
- Physical station 1 and 2 mapping, timed starts, stop-all, and disconnected timer enforcement.
- Resident schedule decoding, partial/full schedule writes, program clearing, exact restoration, and global
  automatic-watering disable/enable.

Still app-derived or untested:

- One- and four-station models and other firmware versions.
- Non-default/wrong PIN behavior and PIN changes.
- Manual program/run-all, temporary suspension, cycle/soak, master valve, automatic schedule activation, logs, and
  LastRun on hardware.
- Home Assistant Bluetooth proxies, polling impact, and connection contention with the official app.

The controller was left enabled with Program A unchanged, Programs B and C empty, and every station idle. The only
persistent side effect of the reversible write tests is an advanced `SettingsChangeDate` timestamp.

## Initial public research — 5 September 2026

**I couldn’t find a working Home Assistant integration for the Hunter NODE-BT, or a published specification of its
irrigation commands.** There is some unfinished community work—and a useful Bluetooth service UUID to start from.

I checked public repositories, the HACS default integration list, Home Assistant discussions, and Hunter’s documentation
on **5 September 2026**. This doesn’t rule out an unlisted or private implementation.

| Project or source                                                                                                                  | What I found                                                                                                                                                                              |
|------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [Home Assistant NODE-BT discussion](https://community.home-assistant.io/t/hunter-node-bt-integration-irrigation-controller/220349) | Requests for support, but no working implementation linked in the thread.                                                                                                                 |
| [piBeacon](https://github.com/kw123/pibeacon)                                                                                      | An Indigo automation plugin that lists NODE-BT. I inspected its code: the NODE-BT advertisement parser is a stub, with no irrigation commands implemented.                                |
| [TheSnook/hunter_btt](https://github.com/TheSnook/hunter_btt)                                                                      | A related Hunter **BTT** project. Its README explicitly says it is under construction and non-functional; the code is largely integration boilerplate. NODE-BT compatibility is unproven. |
| [Home Assistant Hydrawise](https://www.home-assistant.io/integrations/hydrawise/)                                                  | Supports Hunter’s Hydrawise Wi-Fi systems; it doesn’t provide a NODE-BT Bluetooth connection.                                                                                             |

The NODE-BT itself is a promising candidate for **local control**: Hunter specifies Bluetooth Low Energy, battery
operation, and one-, two-, or four-station models. Its app supports manual watering, schedules, suspension,
battery/status reporting, and an optional controller passcode. The Android package is **`com.hunter.nodev2`**. These
establish what the official app can do, but not how its commands are
encoded. [Hunter specifications](https://www.hunterirrigation.com/irrigation-product/controllers/node-bt), [official Android app](https://play.google.com/store/apps/details?id=com.hunter.nodev2)

A concrete protocol lead was that piBeacon contained a sample advertisement named `NODE-BT-223358`. Decoding its
advertised 128-bit service UUID gave:

```text
6e400001-b5a3-f393-e0a9-e50e24dcca9e
```

That matched the **Nordic UART-style service**, commonly used to carry application-defined commands over BLE. The
initial characteristic hypothesis was:

| UUID                                   | Initially expected role                 |
|----------------------------------------|-----------------------------------------|
| `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Commands written to the device          |
| `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Responses/notifications from the device |

The service UUID came from piBeacon’s recorded advertisement, while the characteristic roles were initially a
UART-convention hypothesis. Both roles were later confirmed on the controller. The transport lead alone did not reveal
authentication or command encoding; those came from app analysis and direct
testing. [piBeacon advertisement definitions](https://github.com/kw123/pibeacon/blob/master/piBeacon.indigoPlugin/Contents/Server%20Plugin/knownBeaconTags.json), [BLE UART reference implementation](https://github.com/nkolban/ESP32_BLE_Arduino/blob/master/examples/BLE_uart/BLE_uart.ino)

The following was the original investigation plan. Its first seven milestones now have an initial implementation to the
extent described above; deployment and hardware validation of the Home Assistant layer remain.

1. **Establish a reproducible test setup.**

   Use an owned NODE-BT, its known passcode, an Android phone running the official app, and a computer with Bluetooth.
   Record the exact controller model, firmware, app version, and phone OS. Export or photograph the existing schedule.

   Initially isolate the water supply or use a spare valve. For live tests, use short, supervised runs. Don’t change
   firmware during protocol discovery.

   **Deliverable:** hardware/version inventory and a baseline configuration.

2. **Discover the actual BLE interface.**

   With the Hunter app disconnected, inspect the controller using nRF Connect or a small Bleak script. Export
   advertisement data, services, characteristic UUIDs, properties, descriptors, and readable values.

   Verify the UUIDs above rather than hardcoding assumptions. Determine whether connection requires physical wake-up,
   whether addresses remain stable, and whether pairing/bonding is involved.

   **Deliverable:** GATT inventory and timestamped advertisement samples.

3. **Capture the official app’s communication.**

   On Android, enable **Bluetooth HCI snoop logging** in Developer options, restart Bluetooth, then capture complete app
   sessions. Obtain the logs through a bug report or the device’s supported log export; availability varies by phone.
   Android documents both snoop logging and bug-report
   extraction. [Android Bluetooth debugging](https://source.android.com/docs/core/connect/bluetooth/verifying_debugging)

   Open the capture in Wireshark and inspect ATT traffic using `btatt`. Preserve connection setup, notification
   subscriptions, authentication, writes, and responses—not just the apparent watering command.

   Capture separate, labelled experiments:

   | Experiment                                  | What it helps identify                      |
      | ------------------------------------------- | ------------------------------------------- |
   | Connect, read status, disconnect            | Handshake, authentication, baseline queries |
   | Repeat the same operation in fresh sessions | Session tokens, counters, timestamps        |
   | Start station 1 for several short durations | Start command and duration encoding         |
   | Start another station, where available      | Station numbering                           |
   | Stop watering                               | Stop command and acknowledgement            |
   | Read battery and active-run status          | Telemetry formats                           |
   | Change one schedule field, save, reconnect  | Schedule structure and persistence          |
   | Suspend, then resume irrigation             | Suspension semantics                        |

   HCI captures normally expose ATT payloads despite radio-link encryption. **Application-level encryption could still
   obscure the command contents.** Keep raw captures private because they may contain credentials or unrelated Bluetooth
   traffic.

   **Deliverable:** labelled captures with an action timeline.

4. **Inspect the Android app to resolve ambiguities.**

   Obtain the installed APK and any split APKs from the test phone; record version and hashes. Inspect
   with [JADX](https://github.com/skylot/jadx), searching for the UUIDs, `BluetoothGatt`, characteristic writes,
   notification callbacks, packet builders, passcode handling, and checksum/cryptographic routines.

   Identify the app framework first: important logic might reside in native libraries, JavaScript, or .NET assemblies
   rather than ordinary Java classes.

   Correlate code paths with captured packets. Determine whether the passcode uses BLE pairing, a custom login exchange,
   or both. Use the known credential; don’t assume replayed login packets will work across sessions.

   **Deliverable:** command/authentication notes with supporting capture references.

5. **Write a protocol specification before implementing control.**

   Document framing, opcodes, field offsets, byte order, units, lengths, checksums, sequence numbers,
   acknowledgement/error responses, fragmentation, and session lifecycle.

   Mark every finding as **observed**, **inferred**, or **unverified**. Validate inferred duration fields against
   additional values. Distinguish information stored only by the phone—potentially names or pictures—from data actually
   read from the controller.

   **Deliverable:** `PROTOCOL.md` and sanitised request/response fixtures. Do not invent missing bytes.

6. **Build a standalone asynchronous Python library.**

   Use [Bleak](https://bleak.readthedocs.io/en/latest/api/client.html), keeping packet encoding/decoding separate from
   the Bluetooth transport. Start with:

   ```text
   connect/authenticate
   read_status
   start_station(station, duration)
   stop_all
   disconnect
   ```

   Subscribe to notifications before sending commands. Serialize transactions, implement bounded timeouts, and handle
   fragmented responses. After an ambiguous timeout, query state before retrying a start command: a blind retry might
   restart or extend watering.

   **Critical acceptance test:** start a timed run, disconnect the client, and confirm that the controller stops it
   independently. Home Assistant must not be the only mechanism responsible for stopping water.

   **Deliverable:** library, small CLI, parser tests, and verified hardware results.

7. **Wrap the library in a Home Assistant custom integration.**

   Use a domain such as `hunter_node_bt`, a configuration flow, device identification, and passcode entry where needed.
   Obtain connectable devices through Home Assistant’s Bluetooth APIs so local adapters and remote proxies can be
   supported. Use its shared scanner and connection-retry
   guidance. [Home Assistant Bluetooth development](https://developers.home-assistant.io/docs/bluetooth/), [Bluetooth APIs](https://developers.home-assistant.io/docs/core/bluetooth/api/)

   Suggested first release:

   | Feature                              | Home Assistant interface              |
      | ------------------------------------ | ------------------------------------- |
   | Station control                      | Valve entity per irrigation station   |
   | Timed watering                       | Action accepting station and duration |
   | Emergency stop                       | Stop-all button/action                |
   | Battery and verified run information | Sensors                               |
   | Rain/soil inhibit, if decoded        | Binary sensors                        |

   Require a bounded duration for opening a valve. Treat any pump/master-valve output according to its configured role,
   not as an ordinary watering zone. Represent stale or disconnected state honestly.

   Keep schedule editing for a later release; manual timed control plus status is a useful first milestone.

8. **Validate remote operation and failure recovery.**

   An ESPHome Bluetooth proxy near the controller is a sensible eventual deployment, provided the discovered
   authentication and GATT behavior work through it. The proxy must support **active connections**; it won’t supply the
   missing Hunter protocol
   itself. [ESPHome Bluetooth proxy documentation](https://esphome.io/components/bluetooth_proxy/)

   Test app/HA connection contention, out-of-range recovery, wrong passcodes, HA restart during watering, duplicate
   commands, and schedule preservation. Measure the effect of polling on battery life; avoid assuming a permanent
   connection is appropriate.

   **Release gate:** correct station control, reliable stop, controller-enforced timeout, reconnect recovery, and
   documented model/firmware coverage. Supply installation instructions, diagnostics redaction, tests, and a
   HACS-compatible repository.

**The best first milestone was a captured connect → status → short timed run → stop session, plus the GATT inventory.**
This milestone is now complete through direct BLE testing and static app analysis; see the hardware-validation update
above.
