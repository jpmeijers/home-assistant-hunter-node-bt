# Hunter NODE-BT Bluetooth protocol

This document describes protocol evidence recovered from the official Android app, package `com.hunter.nodev2`, version
`6.0.611246` (`versionCode` 611246), and verified against a physical two-station NODE-BT on 7 September 2026.

## Evidence status

Statements in this document use these meanings:

- **Hardware-verified** means the local Bleak probe exchanged the command with the physical controller and checked its
  response or readback.
- **App-derived** means the behavior is present in the decompiled official app but was not exercised against hardware.
- **Unknown** means neither the app nor the completed tests resolved it.

Summary of evidence:

- **Confirmed in app:** UUIDs, discovery filter, PIN exchange, JSON commands, 20-byte writes, response framing, and data
  field units below.
- **Confirmed on hardware:** service-filtered discovery, GATT properties, authentication with PIN `0000`, controller and
  state reads, physical control of stations 1 and 2, `StopAll`, and controller-enforced timed shutoff after the BLE
  client disconnects. Schedule reads, partial and complete program writes, program clearing, and the global
   controller-off flag are also hardware-verified. On 8 September, controller telemetry additionally confirmed a
   30-second scheduled Program B run while the BLE client was disconnected, followed by idle state and a `LastRun` read.
   The user also confirmed that water ran on Pots for 30 seconds.
- **Previously observed elsewhere:** a `NODE-BT-223358` advertisement containing the Nordic UART service UUID (recorded
  by piBeacon).

The tested controller identified itself as `NODE-BT-707796`, serial number
`16707796`, with two stations, controller firmware `2.2A`, bootloader `1.00`, and Bluetooth firmware `1.02`. It accepted
the default PIN without operating system pairing or bonding.

The app is a .NET MAUI application with managed code stored in an LZ4-compressed Android assembly store. The relevant
implementations are `BleGuids`,
`BleDeviceCommunication`, `DevicePinInfo`, and `Commands` in the recovered
`NodeV2.Service.Interface.dll` and `NodeV2.Services.dll` assemblies.

The APK was not taken from the attached phone. Static analysis was sufficient, and direct BLE testing confirmed the
protocol, so Android HCI snoop capture was not needed. `tools/unpack_assembly_store.py` extracts XALZ-compressed
assemblies from an XABA Android assembly-store payload; the managed DLLs can then be opened with ILSpy. Ordinary JADX
output does not contain the main application logic.

The analysed base APK has SHA-256
`748773ccb6aeb61518f279206b6e706ebfbf1377f68154730b68d7b73d982a2d`. Android's signature verifier accepts it; the signer
certificate SHA-256 is
`57af395ac5a145f7a032ca6516e3e46124ac63a2c7c65ed4667e50028685a099`.

## Discovery and GATT

The app scans with a service UUID filter for the message service. It does not filter on the advertised device name.

| Purpose            | UUID                                   | Observed properties                    |
|--------------------|----------------------------------------|----------------------------------------|
| Message service    | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | Advertised and used as the scan filter |
| Message request    | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Write                                  |
| Message response   | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Read, indicate                         |
| PIN service        | `0ed3e3d3-8cd8-4f29-8fec-a7d3a2c5443e` | Authentication service                 |
| PIN characteristic | `4c9dbe52-3566-4dfc-a299-4ea1353970e2` | Read, write without response, notify   |

The complete additional GATT inventory observed on the tested controller was:

| Service                                | Characteristic                         | Properties                    | App-derived purpose                          |
|----------------------------------------|----------------------------------------|-------------------------------|----------------------------------------------|
| `0031f62c-b837-11e7-abc4-cec278b6b50a` | `6d9e1460-b82e-11e7-abc4-cec278b6b50a` | Write without response        | Controller firmware request                  |
| `0031f62c-b837-11e7-abc4-cec278b6b50a` | `41a87e7b-c3a9-4abb-a869-a139ac129b0d` | Read, notify                  | Controller firmware response                 |
| `3595f2c9-f57c-429c-ae01-185ef51d4020` | `639b5b38-728d-4d48-830a-22e1c79d7e64` | Write without response        | Bootloader firmware request                  |
| `3595f2c9-f57c-429c-ae01-185ef51d4020` | `04498679-8822-40c6-b32a-ba1aedc8dd44` | Read, notify                  | Bootloader firmware response                 |
| `1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0` | `f7bf3564-fb6d-4e53-88a4-5e37e0326063` | Write                         | Bluetooth OTA control                        |
| `1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0` | `984227f3-34fc-4045-a5d0-2c581f81a153` | Write, write without response | Bluetooth OTA data                           |
| PIN service                            | `5ddbae59-d9d1-40ed-8023-7b6ae95b04e6` | Read, notify                  | Unknown; unused by the app's normal PIN flow |

The standard Generic Attribute service `00001801-0000-1000-8000-00805f9b34fb`
was also present. Firmware-update services were enumerated only and were never written during this investigation.

The observed address was `60:B6:47:FE:F0:D4` and RSSI varied roughly from -56 to -78 dBm. Address persistence was not
established, so discovery must use the advertised message-service UUID rather than assuming this address is stable.

## Connection lifecycle

The working sequence is:

1. Scan for advertisements containing the message-service UUID.
2. Connect using the resulting current BLE device object.
3. Subscribe to the PIN characteristic and the message-response characteristic. The latter uses GATT indications on the
   tested firmware, although Bleak exposes both notifications and indications through
   `start_notify`.
4. Complete PIN authentication.
5. Run only one JSON transaction at a time.
6. Disconnect when finished; a persistent connection is not required for a timed run to complete.

The official app uses a 15-second connection timeout, 15-second PIN packet timeouts, and a semaphore to serialize all
commands. Local testing saw intermittent advertisement-free scan windows and one cached-address connection timeout. A
fresh service-filtered scan succeeded. Use bounded retries with a new discovery result, and account for app/HA
connection contention.

## Session and PIN authentication

The official app always authenticates after connecting. It first tries a saved PIN, otherwise it tries PIN `0`; a
controller without a user passcode therefore uses `0` as its PIN. The UI accepts four decimal digits, while the packet
stores the value as an unsigned 16-bit integer.

Every PIN packet is six bytes, little-endian:

| Offset | Size | Field                      |
|--------|-----:|----------------------------|
| 0      |    1 | packet type                |
| 1      |    1 | result (`0` means success) |
| 2      |    2 | random challenge           |
| 4      |    2 | PIN response               |

Before transmission, each nonzero byte is XORed with `0xac`; zero bytes remain zero. Incoming packets use the same
transform.

1. Client writes a type `1` login request without response: plaintext
   `01 00 00 00 00 00`, wire bytes `ad 00 00 00 00 00`.
2. Controller notifies a type `2` challenge containing a random 16-bit value.
3. Client writes type `3` without response, copies the random value, and sets the PIN field to `pin XOR random`, then
   applies the byte transform.
4. Controller notifies type `4`; result `0` accepts the login.

Packet types are `0` none, `1` login request, `2` login challenge, `3` login response, `4` login result, `5` change-PIN
request, `6` change-PIN challenge,
`7` change-PIN response, and `8` change-PIN result. Types `5` through `8` use the same transform and challenge
calculation with the new PIN. The app performs the change only after an authenticated session. PIN change and wrong-PIN
result codes were not tested on hardware.

The transform is symmetric but is not ordinary XOR for zero bytes: decoding must also leave wire byte `00` as zero. A
literal implementation is:

```python
def transform(packet: bytes) -> bytes:
    return bytes(value ^ 0xAC if value else 0 for value in packet)
```

## Application messages

Commands are compact JSON encoded as UTF-8 and split into consecutive writes of at most 20 bytes. The app does not
append a terminator and does not add a checksum, sequence number, opcode, encryption, or outer frame.

The response characteristic emits UTF-8 JSON in one or more notifications. A zero byte terminates the response.
Successful write commands return JSON of the form `{"Status":0}` followed by the terminator. Read commands return a JSON
object followed by the terminator. The app serializes one transaction at a time. There is no delimiter between request
chunks, and the final request chunk is not NUL-terminated. The request characteristic supports acknowledged writes on
the tested controller; the PIN characteristic requires writes without response.

The official app drops an identical response fragment repeated within 100 ms and clears an incomplete response if a new
fragment starts with `{`. These are defensive behaviors rather than confirmed firmware requirements. An integration
should accumulate raw bytes until the first NUL, decode UTF-8, parse one JSON object, and reject or log malformed and
trailing data.

Useful read commands are:

```text
{"Read":"All"}
{"Read":"Section_Controller"}
{"Read":"Section_State"}
{"Read":"Section_Sensor"}
{"Read":"LastRun"}
{"Read":"Log"}
```

Manual control commands are:

```text
{"Manual":{"StationNumber":1,"RunTime":60}}
{"Manual":{"ProgramLetter":"A"}}
{"Manual":{"ProgramLetter":"T","RunTime":60}}
{"Manual":{"StopAll":true}}
```

`RunTime` is seconds and station numbers are one-based. Program `T` means run all stations. Hardware tests sent
120-second commands to stations 1 and 2; both returned `{"Status":0}` and the user confirmed water on the corresponding
physical lines. `StopAll` also returned status `0`, followed by an idle state read. A separate 15-second station 1 run
was allowed to continue after the BLE client disconnected; a later state read showed that the controller had ended the
run itself.

Only status `0` is known to mean success. The meanings of nonzero status values were not discovered. Treat any nonzero
value as failure.

## Read responses and state values

The final restored `Read All` response and an idle `Section_State` response are preserved as fixtures:

- [`captures/node_bt_707796_read_all_2026-09-07.json`](captures/node_bt_707796_read_all_2026-09-07.json)
- [`captures/node_bt_707796_idle_state_2026-09-07.json`](captures/node_bt_707796_idle_state_2026-09-07.json)

`Read All` returned `Controller`, `Sensor`, `HunterCustom`, the three programs, four station objects, and `Manual`; it
did not include `State` on firmware
`2.2A`. Read `Section_State` separately when live state is required. Although this controller has two physical stations,
the firmware still returned
`Station_1` through `Station_4` and four program runtime entries. Use
`Controller.StationCount` to expose only real stations.

Important observed fields and units are:

| Path                                                 | Meaning / observed value                                          |
|------------------------------------------------------|-------------------------------------------------------------------|
| `Controller.CurrentTime`                             | Local wall time encoded as seconds since 1970-01-01, without UTC conversion (see clock sync below) |
| `Controller.StationCount`                            | Physical station count; observed `2`                              |
| `Controller.SeasonAdjust`                            | Percent; observed `100`                                           |
| `Controller.SeasonAdjustByMonth`                     | Twelve monthly percentages                                        |
| `Controller.StationDelay`                            | Seconds between stations                                          |
| `Controller.ProgrammableDaysOff`                     | Suspension expiry at local midnight, using the app's wall-time epoch encoding |
| `Controller.BatteryChangeDate`, `SettingsChangeDate` | Battery date uses the app's wall-time epoch helper; device-generated settings date needs separate verification |
| `Controller.ManualRunTime`                           | Default manual runtime in seconds; observed `1800`                |
| `Sensor.Battery`                                     | Battery percent; observed `60`                                    |
| `Sensor.MoistureSensor`                              | Moisture percentage; observed `100`                               |
| `Sensor.MoistureADC`                                 | Raw moisture ADC; observed `0`, absent from the app's typed model |
| `State.NextWaterTime`                                | Minutes since midnight; observed `810` for 13:30                  |
| `State.DailyRunTime`                                 | Daily runtime counter in seconds; observed `240`, then `270` after a 30-second run |
| `State.Station_N.Remaining`                          | Remaining seconds                                                 |

The app-derived `ControllerState` enum is:

| Value | Meaning          | Value | Meaning           |
|------:|------------------|------:|-------------------|
|     0 | Idle             |     7 | Program A running |
|     1 | Manual station   |     8 | Program B running |
|     2 | System off       |     9 | Program C running |
|     3 | Programmable off |    10 | Manual run all    |
|     4 | Rain off         |    11 | Manual Program A  |
|     5 | Rain delay       |    12 | Manual Program B  |
|     6 | Soil off         |    13 | Manual Program C  |

The app-derived station `State` enum is `0` idle, `1` waiting to run, `2`
suspended, `3` running, `4` soaking, `5` delay, and `6` complete. Only idle state `0` was captured directly because the
attempted state read during a live manual run hit a transient connection timeout.

`LastRun` was read successfully on 8 September after the offline scheduled test:

```json
{"StartEvent":2,"StartTime":1788895291,"Station":1,"RunTime":30,"StopEvent":1}
```

The reply is a top-level object, not wrapped in `LastRun`. In this test `StartEvent: 2` corresponded to Program B and
`StopEvent: 1` accompanied the completed 30-second run. Other event meanings remain unverified.
The returned `StartTime` was 31 seconds after the programmed start in the controller's clock encoding, so do not yet
assume it is the exact start instant: completion-time behavior or scheduling latency needs another timed observation.
The fixture is in [`captures/schedule_test_2026-09-08/after_scheduled_last_run.json`](captures/schedule_test_2026-09-08/after_scheduled_last_run.json).
Log responses remain app-derived as entries with a numeric `Time` and an integer `Event` list; the 255-entry log was
not downloaded.

During this test `Controller.CurrentTime` was approximately host Unix time plus 7,170 seconds (UTC+2 minus about
30 seconds). Subsequent app analysis confirmed that its clock setter encodes local wall time without UTC conversion
(see clock sync below), consistent with this observation. No clock write was made. Program start `19:21` was interpreted against that
controller clock, with the expected real-world run window approximately 19:21:30–19:22:00 SAST.
Clock-write behavior, interval anchors, suspension expiry, and historical-event interpretation still need device tests.

`DailyRunTime` stayed `240` after uploading the new 30-second program, rose to `270` after it ran, and remained `270`
after restoring the original schedules. It is therefore not simply the sum of configured scheduled durations. Reset
timing, manual-run inclusion, and interrupted-run accounting still need testing.

Known log event numbers from the app are: program starts `1`/`2`/`3`, manual start `11`, rain sensor
active/inactive/enabled/disabled/delay-expired
`100`–`104`, soil threshold above/below `110`/`111`, Bluetooth connected/disconnected `120`/`121`, programmable-off
enabled/disabled
`130`/`131`, battery check `200`, battery inserted `250`, internal firmware reset `251`, log clear `252`, app/UI factory
reset `253`/`254`, and factory power-up `255`.

## Known write commands

The following command builders exist in the official app. Rows marked hardware-verified were exercised locally; the rest
are app-derived.

| Area                     | JSON payload or fields                                                                                               | Evidence                                           |
|--------------------------|----------------------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| Manual station           | `{"Manual":{"StationNumber":N,"RunTime":SECONDS}}`                                                                   | Hardware-verified for stations 1 and 2             |
| Stop                     | `{"Manual":{"StopAll":true}}`                                                                                        | Hardware-verified                                  |
| Manual program           | `{"Manual":{"ProgramLetter":"A"}}` (also B/C)                                                                        | App-derived                                        |
| Manual all               | `{"Manual":{"ProgramLetter":"T","RunTime":SECONDS}}`                                                                 | App-derived                                        |
| Program patch            | `Program_A`, `Program_B`, or `Program_C` with any program fields                                                     | Hardware-verified on B                             |
| Controller off           | `Controller.ControllerOff`                                                                                           | Hardware-verified true and restored false          |
| Temporary suspension     | `Controller.ProgrammableDaysOff`                                                                                     | App-derived                                        |
| Controller identity/time | `Controller.Name`, `Controller.CurrentTime`                                                                          | App-derived                                        |
| Seasonal adjustment      | `Controller.SeasonAdjust`, `SeasonAdjustByMonthEnable`, `SeasonAdjustByMonth`                                        | App-derived                                        |
| Sensors                  | `Controller.ClickSensorEnabled`, `ClickDelaySeconds`, `SoilSensorEnabled`, `SoilTriggerLevel`, `SensorBypassEnabled` | App-derived                                        |
| Station behavior         | `Controller.StationDelay`, `PmvEnabled`                                                                              | App-derived                                        |
| Other controller fields  | `BatteryChangeDate`, `SolarPanelAttached`                                                                            | App-derived                                        |
| Station patch            | `Station_N.Name`, `Cycle`, `Soak`                                                                                    | App-derived                                        |
| Clear logs               | `{"Controller":{"LogCount":0}}`                                                                                      | App-derived                                        |
| Factory reset            | `{"HunterCustom":{"FactoryReset":true}}`                                                                             | App-derived and intentionally untested/destructive |

All writes can be minimal JSON patches; the controller merges the supplied fields. Preserve values you do not
understand, prefer narrow patches, and read back configuration writes. `SettingsChangeDate` advanced during schedule and
controller-off tests even after values were restored.

## Schedules

`{"Read":"All"}` returns three resident programs under `Program_A`,
`Program_B`, and `Program_C`. The schedule captured from the tested controller is preserved in
[`captures/node_bt_707796_schedules_2026-09-07.json`](captures/node_bt_707796_schedules_2026-09-07.json).

The active configuration at capture time was:

| Program | Days      | Start times | Station runtimes         |
|---------|-----------|-------------|--------------------------|
| A       | Every day | 13:30       | Pots: 180 s; Grass: 60 s |
| B       | Every day | None        | All zero                 |
| C       | Every day | None        | All zero                 |

Each program object contains:

| Field              | Encoding                                                                                                                                                                     |
|--------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `Name`             | String displayed by the app                                                                                                                                                  |
| `ScheduleType`     | `0` weekdays, `1` odd/even dates, `2` interval                                                                                                                               |
| `ScheduleDays`     | For type 0, low seven bits are Monday through Sunday (`1` through `64`); `127` means every day. For type 1, values below `256` mean odd and values at least `256` mean even. |
| `IntervalDayCount` | Number of days in the type-2 interval                                                                                                                                        |
| `IntervalDayNext`  | Unix timestamp at local midnight for the next interval run                                                                                                                   |
| `StartTimes`       | Eight minutes-since-midnight values; unused slots are `65535`                                                                                                                |
| `RunTime`          | Per-station durations in seconds, indexed from station 1                                                                                                                     |

The official app's field-only runtime editor sends one entry per configured station, while full program objects and
controller reads contain four entries. The hardware tests used four-entry arrays. A portable implementation should
preserve the array shape returned by that controller or follow the app's station-count shape for a narrow runtime patch.

Fields can be patched independently. These forms are generated by the app and were also accepted by the controller:

```text
{"Program_A":{"StartTimes":[810,65535,65535,65535,65535,65535,65535,65535]}}
{"Program_A":{"RunTime":[180,60,0,0]}}
{"Program_A":{"ScheduleType":0,"ScheduleDays":127,"IntervalDayCount":0,"IntervalDayNext":0}}
{"Program_A":{"Name":"Program A"}}
```

A complete program object can be written in one transaction. A hardware test changed every Program B field, read all
values back successfully, then restored the captured Program B object and verified it with another full read.

**8 September follow-up:** do not infer that every complete-object transition is safe from that earlier test. A later
full-object restoration which simultaneously cleared `StartTimes` and wrote zero `RunTime` values acknowledged success
but returned two midnight (`0`) starts instead of eight disabled entries. A separate narrow `StartTimes` clear succeeded.
The integration now rejects requests that include both arrays; edit and verify starts and runtimes separately. The exact
firmware cause of the combined-write discrepancy is not yet isolated.

Additional behavior observed directly on the same firmware on 8 September:

- Enabled start times are sorted ascending and packed at the beginning of the eight-entry array. Writing positions 1
  and 8 returned them in positions 1 and 2. Positions are not persistent slot identities.
- Duplicate enabled times were retained in readback; duplicate execution behavior was not tested. The integration
  rejects duplicate start times.
- Twelve-character ASCII program names were retained. Sixteen- and 32-character names were truncated to 14 ASCII
  characters despite status `0`. The integration conservatively caps new names at 14 UTF-8 bytes; non-ASCII limits
  were not hardware-tested.
- Batch and individual station-runtime patches, zeroing runtimes, weekday masks, sorted start edits, and narrow start
  clearing were exercised. Raw transactions are preserved in
  [`captures/schedule_test_2026-09-08/transactions.jsonl`](captures/schedule_test_2026-09-08/transactions.jsonl).

There is no per-program enabled boolean. A program is non-runnable if either all eight `StartTimes` entries are `65535`
or its `RunTime` values sum to zero. The official app clears individual start times from its list and, on save, pads the
array back to eight entries with `65535`. To clear a whole program while retaining its name and water-day selection,
write and verify the two disabled arrays **in separate transactions**:

```json
{"Program_B":{"RunTime":[0,0,0,0]}}
```

```json
{"Program_B":{"StartTimes":[65535,65535,65535,65535,65535,65535,65535,65535]}}
```

All automatic watering can be disabled without altering any program:

```text
{"Controller":{"ControllerOff":true}}
```

Write `false` to enable it again. Both transitions returned `{"Status":0}` on hardware, and reads confirmed the stored
values. Temporary suspension uses
`{"Controller":{"ProgrammableDaysOff":LOCAL_EPOCH_SECONDS}}`; the app chooses local midnight up to 99 days ahead,
encoded without UTC conversion using the helper described below.
A current or past timestamp removes the effective suspension.

Other confirmed examples include:

```text
{"Controller":{"ControllerOff":true}}
{"Controller":{"ProgrammableDaysOff":1788739200}}
{"Controller":{"SeasonAdjust":100,"SeasonAdjustByMonthEnable":false}}
{"Controller":{"StationDelay":30}}
{"Controller":{"CurrentTime":1788739200}}
{"Station_1":{"Name":"Front","Cycle":600,"Soak":300}}
{"Program_A":{"StartTimes":[360,65535,65535,65535,65535,65535,65535,65535]}}
{"Program_A":{"RunTime":[600,0,0,0]}}
```

Do not interpret every epoch-like number as a UTC Unix timestamp; the app uses different conversions for different
fields, as detailed below. Program start times are minutes from midnight. Program run, station
cycle/soak, station delay, sensor delay, and manual run values are seconds.

## Clock synchronization (app-derived and hardware-tested 8 September 2026)

The official Android app writes the phone's **local wall time**, encoded as seconds since a naive
`1970-01-01 00:00:00`. Despite the helper's name, this is not a standard UTC Unix timestamp.

The normal successful post-connect workflow in `PeripheralViewModel.DoIt` calls:

```csharp
Commands.SetCurrentDateTime((long)DateTime.Now.ToUnixTimestamp())
```

This runs after reading configuration, resolving offline edits, and checking firmware updates, when the firmware
update flow does not take over. There is no drift threshold at this call site. Failure disconnects; success opens
the dashboard. Factory-reset reconnection also calls this setter, and firmware-update restoration supplies the same
time expression to `Commands.MainRestoreCommand`.

`NodeV2.Utilities.DateTimeExtensions.ToUnixTimestamp` implements:

```csharp
return Math.Max(0.0, Math.Floor(dateTime.Subtract(TimeEpoch.UnixEpoch.EpochStart.DateTime).TotalSeconds));
```

`NodeV2.Services.TimeEpoch.UnixEpoch` is initialized to `1970-01-01 00:00:00 +00:00`.
Its `.DateTime` property drops the offset, and `DateTime.Subtract(DateTime)` does not normalize time zones.
Thus `DateTime.Now` contributes the phone's local calendar fields directly. These semantics are documented by
Microsoft for [DateTimeOffset.DateTime](https://learn.microsoft.com/en-us/dotnet/api/system.datetimeoffset.datetime)
and [DateTime.Subtract](https://learn.microsoft.com/en-us/dotnet/api/system.datetime.subtract).
`Commands.SetCurrentDateTime` copies the resulting integer directly into `{"Controller":{"CurrentTime":...}}`.
The command carries no timezone or UTC-offset field.

For example, at `2026-09-08 19:21:00` in South Africa (`17:21:00Z`), the app sends `1788895260`;
a true Unix timestamp for that instant is `1788888060`. The difference is 7,200 seconds. Our captured controller
clock was consistent with this encoding and approximately 30 seconds slow.

Other date fields must be traced individually:

- `SuspendPageViewModel.SaveDaysOffAsync` and the calendar picker pass `SelectedDate.Date.ToUnixTimestamp()`:
  suspension expiry uses the same wall-time encoding. Battery-date editing also uses this helper.
- `UnixTimestampToDateTime` adds seconds to the epoch and returns `.DateTime`, preserving the encoded calendar
  fields without converting to the phone's local timezone.
- `WaterDaysPageViewModel.SaveWateringMode` instead uses
  `new DateTimeOffset(SelectedDateUntil).ToUnixTimeSeconds()` for `IntervalDayNext`. This is a timezone-aware Unix
  conversion, unlike the clock helper; interval scheduling needs separate testing before implementation.
- This analysis does not establish the exact event represented by `LastRun.StartTime`, log timestamps, or all
  device-generated date fields. The observed 31-second discrepancy in the scheduled-run report remains unresolved.

Source locations in the recovered assemblies: `NodeV2.ViewModelsMaui.dll` (`PeripheralViewModel`,
`FactoryResetPageViewModel`, `FirmwareUpdatePageViewModel`, `SuspendPageViewModel`, `WaterDaysPageViewModel`),
`NodeV2.Service.Interface.dll` (`Commands`), and `NodeV2.Utilities.dll` (`DateTimeExtensions`, `TimeEpoch`).
The recovered Utilities DLL SHA-256 is `c62458a4bc3b20cbbc6683c15cfb8044279dcc83183ca396b1b2701f0c0e9791`;
APK identity is recorded above.

The HA integration does not yet synchronize the clock. A future implementation should obtain local time in HA's
configured timezone (assuming the controller is in that timezone), encode those wall-clock fields at the protocol
boundary, and retain real UTC timestamps for HA diagnostics. It must not use the host/container timezone implicitly.
Writing true UTC directly would move this controller's clock two hours behind South African local time. Clock writes
and readback were subsequently verified as described below. Behavior when a correction crosses a scheduled start
remains untested. DST transitions and operation
while HA is unavailable also need consideration for locations that observe DST.

At approximately 20:00 SAST on 8 September, a direct BLE test corrected the controller's clock forward by about
29 seconds using the app's encoding. The write `{"Controller":{"CurrentTime":1788897634}}` returned `{"Status":0}`.
Immediate readback was `1788897635`; after disconnecting, waiting 15 seconds, and reconnecting, the clock read
`1788897657`. Both reads agreed with host local wall time within three seconds at response completion (including
BLE response latency). All programs, station configuration, and other configuration values were unchanged;
`SettingsChangeDate` also stayed unchanged. The final controller state was idle and `DailyRunTime` remained `270`.
This test neither changed schedules nor initiated watering. It verifies a small clock correction away from a
scheduled start and continued timekeeping across a BLE disconnect, not power-loss persistence or scheduling across
a clock jump. Captures and the test script are in
[`captures/clock_test_2026-09-08_180027`](captures/clock_test_2026-09-08_180027/README.md).

## Home Assistant live integration test (8 September 2026)

The integration was run inside the local Home Assistant Core checkout using its Python 3.14.6 environment and a
temporary configuration. HA's real Bluetooth discovery found the controller through hci0; the Bluetooth confirmation
flow authenticated it and all seven entity platforms loaded (67 registry entries including disabled entities).

Real HA service calls successfully changed and verified Program B's name, runtimes, start time, and weekday, cleared
its start through `hunter_node_bt.clear_start_time`, and updated runtimes through `hunter_node_bt.set_program`.
HA storage contained the prewrite backup, and diagnostics reported a verified write. All original programs were
restored and verified by fresh reads both before and after integration reload. No watering was initiated in this test.

An initial run exposed a reload race: an old coordinator's in-flight service call and the new coordinator could open
overlapping BLE sessions, producing authentication errors and a read timeout. Controller sessions now share a lock
by Bluetooth address for the lifetime of the HA instance, including coordinator reloads. An automated regression
test covers the overlap. A targeted hardware test also reloaded during an active HA name-write service call: the
write completed, the new coordinator connected afterward and verified it, and the original programs were restored.
See the [live reload regression report](captures/ha_test_2026-09-08_181523/README.md).
All 40 tests pass in the HA environment with no skips.

See [`captures/ha_test_2026-09-08_181012`](captures/ha_test_2026-09-08_181012/README.md) for evidence and limitations.
ESPHome proxy transport, browser interactions, and end-to-end Smart Irrigation/blueprint execution remain untested.

## Direct probe

`tools/ble_probe.py` duplicates the app's scan filter and authentication. It can issue reads and bounded manual-control
commands. A default scan does not connect:

```shell
python tools/ble_probe.py --timeout 30
python tools/ble_probe.py --read controller --pin 0
python tools/ble_probe.py --start-station 1 --duration 60 --pin 0
python tools/ble_probe.py --stop --pin 0
python tools/ble_probe.py --command-json '{"Controller":{"ControllerOff":true}}' --pin 0
```

Use a real four-digit PIN in place of `0` when the controller has one. The tool limits manual runs to 300 seconds.
`--command-json` exposes arbitrary protocol writes and should be paired with a saved baseline and readback verification
for configuration changes. A direct reconnect by cached Bluetooth address timed out once during testing; repeating
service-filtered discovery connected successfully, so callers should refresh discovery and retry bounded connection
failures.

## Home Assistant implementation guidance

- Build an asynchronous transport/library layer independent of Home Assistant. Its minimum API should be `connect`,
  `authenticate`, `read_controller`,
  `read_state`, `read_all`, `start_station`, `stop_all`, and `disconnect`.
- Use Home Assistant's Bluetooth discovery and shared connection APIs rather than running an independent scanner inside
  the integration. Retain the connectable service-info/device object supplied by HA and support active Bluetooth proxies
  where possible.
- Serialize authentication and application transactions with one lock. Enable both subscriptions before authentication
  and keep one response accumulator per transaction.
- Require a positive bounded duration for valve opening. The research probe caps this at 300 seconds; product limits can
  be configurable while still enforcing a finite maximum.
- If a start command times out after transmission, read live state before retrying. Blind retries can restart or extend
  watering. Provide an emergency
  `stop_all` action that does not depend on cached state.
- Disconnect after work and poll sparingly because the controller is battery powered. The official app reconnects on
  demand rather than requiring an always-on session.
- Expose only `StationCount` stations. Station names come from `Station_N.Name`. A valve entity per station plus
  timed-water and stop actions is a suitable first release. Battery, controller state, remaining time, next watering
  time, and sensor inhibits are useful read-only entities.
- Schedule writes should begin from a fresh `Read All`, patch only intended fields, retain fixed array shapes/sentinels,
  verify `Status == 0`, and read back the result. Keep schedule editing out of the first release unless this
  read-modify-verify behavior is implemented.
- The integration now implements that program read-modify-verify path, persisted pre-write backups, runtime/start-time/
  weekday/name controls, and a batch program action. See [SCHEDULES.md](SCHEDULES.md) for supported edits, failure handling,
  the optional duration-sensor blueprint, and remaining HA end-to-end tests. The 8 September hardware tests verify the
  supported program edits and autonomous scheduled activation; other app-derived capabilities retain their stated gaps.
- Redact PINs, Bluetooth addresses, and serial numbers from diagnostics. Never log the PIN challenge response at normal
  logging levels.

## Completed hardware tests

All tests used the local computer's Bluetooth adapter, Bleak 3.0.2, and the default PIN. The Android phone was not used.

### 7 September

1. Discovered `NODE-BT-707796` by service UUID and enumerated GATT.
2. Authenticated repeatedly and read controller, state, sensor data through
   `Read All`, and the resident schedules.
3. Started station 1 for 120 seconds; the user confirmed water on line 1.
4. Sent `StopAll`, received status `0`, and read idle/zero remaining state.
5. Started station 2 for 120 seconds; the user confirmed water on line 2.
6. Sent and verified another `StopAll` and idle state.
7. Started station 1 for 15 seconds, disconnected immediately, waited past the deadline, and confirmed idle state. The
   controller owns the safety timer.
8. On unused Program B, wrote a test start time and read it back, cleared it to eight `65535` values, wrote and read
   back a complete test program object, then restored the original object.
9. Wrote `ControllerOff: true`, read it back, restored `false`, and performed a final full configuration read.

The final audit confirmed Program A unchanged, Programs B/C empty, controller enabled, and all stations idle. No
schedule test caused watering because the test program had no enabled start time when nonzero runtimes were present.

### 8 September

The current integration's program-write implementation passed runtime, name, weekday, start-time, no-op, preservation,
and validation tests on unused Program B. Hardware differences found during testing led to the 14-byte name limit,
sorted/compacted start arrays, and rejection of combined runtime/start-array writes described above.

A separate Program B schedule ran Pots for 30 seconds with BLE disconnected throughout the expected start/stop window.
The user confirmed the physical watering duration; `LastRun` reported station 1, 30 seconds, and idle state followed.
All programs and station settings were restored and verified against the pre-test backup. Only controller/settings
timestamps and the daily runtime counter changed as a consequence of time passing, configuration writes, and watering.
See [the test report](captures/schedule_test_2026-09-08/README.md) for captures and remaining timestamp uncertainties.

## Known gaps

- Only a two-station NODE-BT running controller firmware `2.2A`, bootloader
  `1.00`, and Bluetooth firmware `1.02` was tested.
- Non-default PIN login, wrong-PIN errors, PIN changes, nonzero status codes, and operating-system address rotation
  remain untested.
- Actual live values for non-idle controller/station state enums were not captured; their meanings come from the app.
- Manual whole-program and run-all commands, scheduled automatic activation, temporary suspension, cycle/soak behavior,
  master-valve mode, and log download were not covered by the 7 September tests. The 8 September offline scheduled
  activation and `LastRun` reply are now captured; the other items and precise timestamp semantics remain unverified.
- ESPHome Bluetooth proxies and Home Assistant connection contention were not tested.
- Firmware update and factory-reset paths were intentionally left untouched.

## Project artifacts

- `custom_components/hunter_node_bt/`: HACS-compatible Home Assistant custom integration with Bluetooth discovery,
  PIN setup, timed station valves, stop-all, and telemetry sensors.
- `tests/test_protocol.py`: fixture-driven tests for authentication, framing, response assembly, models, and verified
  manual-control payloads.
- `tools/ble_probe.py`: working direct BLE discovery/auth/read/manual/raw-command probe.
- `tools/unpack_assembly_store.py`: XABA/XALZ .NET Android assembly extractor.
- `requirements-dev.txt`: Bleak dependency used by the probe.
- `captures/node_bt_707796_read_all_2026-09-07.json`: final restored full-read fixture.
- `captures/node_bt_707796_idle_state_2026-09-07.json`: idle state fixture.
- `captures/node_bt_707796_schedules_2026-09-07.json`: concise schedule backup.
