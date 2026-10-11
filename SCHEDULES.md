# Controller-stored schedules

Home Assistant edits the NODE-BT's resident programs. The NODE-BT starts and stops scheduled watering independently.
Existing programs are read on setup and every normal refresh. No schedule is written during setup or after an HA restart.

## Controls

Each of Programs A/B/C has:

- A schedule sensor with configured/inactive state and attributes for name, day mode, weekdays, interval fields, eight
  start slots, and physical-station runtimes. **Configured means the program contains a runnable configuration, not that
  watering is guaranteed:** controller off, rain/soil inhibits, and temporary suspension can still prevent it.
- One runtime number per physical station, in whole seconds. New values are limited to 0–3600 seconds per occurrence;
  zero skips a station. The limit is an integration policy, not a discovered controller maximum. Existing longer stored
  durations remain readable and are preserved when changing another station.
- Eight time entities, using the controller's local clock, at minute precision. Only slot 1 is enabled in HA by default;
  enable slots 2–8 in the entity registry when needed. A disabled slot has unknown time state and `enabled: false`.
  Setting a time enables that slot. Use `hunter_node_bt.clear_start_time` targeting the time entity to disable it.
  The controller sorts and compacts enabled times after each edit: these are positions in its current list, not stable
  slot identifiers. Adding a time to slot 8 can move it to position 2; deleting position 1 shifts later times forward.
- Seven weekday switches, disabled in the HA entity registry by default. Enable them if wanted. They are unavailable
  for odd/even or interval programs. Switch edits preserve other weekdays, including changes just made in the phone app.
- A stored program-name text entity (1–14 UTF-8 bytes; longer names are truncated by the tested firmware).

The configuration-read timestamp and program-write status remain visible through BLE failures. Write status describes
the last requested edit in this HA session: not requested, writing, verified, unverified, or failed. An ordinary refresh
updates the observed program but does not claim an earlier ambiguous write succeeded. The last verified-write timestamp
is not advanced on failed writes. A verified no-op does advance it, because the requested values were freshly observed.

## Batch action

Prefer one batch action to several entity edits when an automation changes multiple values. Select the controller using
the action's **Controller** field; this action accepts exactly one `device_id` and does not accept area/entity targets.

Calls attributed to a Home Assistant user require control permission for every editing entity (runtime, start time,
weekday, and name) belonging to the selected program on that controller, including disabled entities. Unknown users
and targets without registered editing entities are rejected before Bluetooth access. Internal automation calls without
a user context remain supported. Individual entity actions retain Home Assistant's normal entity permission checks.

```yaml
action: hunter_node_bt.set_program
data:
  device_id: YOUR_CONTROLLER_DEVICE_ID
  program: A
  station_runtimes:
    "1": 240
    "2": 90
```

Omitted fields are retained. Station numbers and slot numbers start at 1. A batch write affects one program only; there
is no multi-program transaction. Each start repeats all that program's nonzero station durations.

Start times and runtimes must be edited in separate actions. Hardware testing found that writing both arrays in one
payload can replace intended disabled starts with midnight entries. The integration rejects such requests before writing.
For a complete reconfiguration, first zero the program's physical-station runtimes, edit its times/days, then set the
desired runtimes with a separate action like the example above. Do this well before the next scheduled start.

With the program's runtimes zero, configure its name and weekday schedule:

```yaml
action: hunter_node_bt.set_program
data:
  device_id: YOUR_CONTROLLER_DEVICE_ID
  program: A
  name: Morning
  weekdays: [mon, tue, wed, thu, fri, sat, sun]
  start_times: ["06:00"]
```

`start_times` replaces all eight slots; enabled times are sorted and unused slots are padded at the end. Duplicate start
times are rejected because their execution behavior is unverified. An empty list disables every start. Use
`start_time_slots` instead to change or clear particular slots while retaining the others:

```yaml
action: hunter_node_bt.set_program
data:
  device_id: YOUR_CONTROLLER_DEVICE_ID
  program: A
  start_time_slots:
    "1": "06:30"
    "2": null
```

`weekdays` explicitly switches to weekday mode and clears interval fields. An empty weekday list selects no watering
days. Other edits preserve odd/even/interval settings. Their rules are not editable in this release because date/clock
semantics need more device coverage. Clearing start slots does not remember their previous times: explicitly set times
to re-enable them. There is no synthetic program-enable switch backed only by HA memory.

## Weather duration blueprint

Copy `blueprints/automation/hunter_node_bt/sync_daily_runtimes.yaml` into the corresponding directory under your HA
configuration, reload automations/blueprints as needed, and create an automation from **Hunter NODE-BT - upload daily
duration sensors**. Merely installing this integration does not install or activate the blueprint.

Select a controller, program, and station-to-sensor mapping:

```yaml
"1": sensor.smart_irrigation_pots
"2": sensor.smart_irrigation_grass
```

The sensors must report seconds (`s` or `seconds`). Choose an upload time after their calculations and well before the
controller's start time. The blueprint uploads once per day, not on HA startup and not on every sensor change. It rejects
the entire update if a source is missing, unavailable, nonnumeric, negative, stale by its HA `last_reported` timestamp,
or above the selected maximum. HA report freshness does not prove that the source's underlying weather observations are
fresh; configure weather-data freshness in the calculation integration. Fractional seconds round up to whole seconds.
Sensor validation and duration capture happen together, so later sensor changes cannot bypass those checks.

The action's optional `require_daily_single_start: true` checks the **fresh controller configuration** before writing:

- All seven weekdays selected and exactly one enabled start.
- Global seasonal adjustment at 100%, monthly adjustment disabled.
- No other active program has a nonzero duration for a mapped station.
- Only station runtimes are changed.

These checks prevent multiplying a daily recommendation across several starts or applying seasonal adjustment twice.
The action still validates physical station count. A changed schedule in the Hunter app can cause the upload to fail
instead of silently applying the wrong watering amount. Failures appear in HA's automation trace; use the write-status
sensor to monitor controller update failures. Source-validation failures occur before the action and do not change that
sensor. There is no automatic retry or delayed replay of an old weather decision.

**Offline behavior:** the last verified durations keep recurring until successfully changed. Zero is rejected by default
because it could disable watering indefinitely if HA goes down. You may opt in to zero, with that explicit consequence.
There is no controller-side expiry for runtime overrides in the documented protocol, and an HA timer cannot supply an
offline fallback. Automatic temporary rain suspension is deferred until its hardware expiry behavior is tested.

**Water accounting:** the blueprint does not reset Smart Irrigation buckets or claim that a scheduled run happened.
Configure accounting separately and avoid enabling an additional valve-driving automation for the same program. Until
NODE-BT run history and its timestamp semantics are validated, hourly polling is insufficient to reliably observe short
runs. A single `LastRun` reply was captured on hardware, but that cannot recover multiple missed runs. This blueprint is an
advance configuration adapter, not a complete closed-loop Smart Irrigation controller. Smart Irrigation's public
duration outputs are documented in its [repository](https://github.com/altmenorg/HAsmartirrigation). Irrigation Unlimited
normally executes watering from HA; it does not automatically upload programs through these entities. See its
[action/event interface](https://github.com/rgc99/irrigation_unlimited).

## Write and recovery behavior

One controller lock covers fresh `Read All`, validation, backup, minimal program patch, successful integer status 0,
and full readback. Readback compares every original program field after merging the patch, including unknown fields.
Unchanged fields are not transmitted. Arrays retain the shape read from the controller, including unused station entries.
The BLE session lock is shared across coordinator reloads, so an in-flight edit finishes before the new coordinator connects.

Before each non-no-op write, the integration saves the previous raw program in HA storage:
`.storage/hunter_node_bt.<config-entry-id>.program_backup`. There is one most-recent backup per program; each successful
backup replaces that program's previous backup. A storage failure prevents the BLE write. Recovery is manual: inspect
the backup, refresh the controller, and restore supported fields using `set_program` (or use the documented raw probe
for fields unsupported by the action). Do not restore start and runtime arrays together: restore them separately and
verify each step. Backups are never automatically restored over newer app edits. Keep a separate full configuration
export before device testing; these rolling backups are not an archival history.

Lost acknowledgement or failed readback marks a write unverified and program controls unavailable until a successful
refresh. Refresh and inspect observed values before deciding whether to retry. There is no automatic retry, queued
intent, rollback, or promise of crash-safe atomic firmware writes. A negative/malformed status is an action failure.

## Device test procedure

The current protocol implementation was exercised on firmware 2.2A on 8 September, including a 30-second scheduled run
with BLE disconnected throughout its expected start/stop window and successful post-run telemetry/readback. The test
found and fixed name-length, start sorting, and combined-array write issues. See the
[captured results](captures/schedule_test_2026-09-08/README.md). Live HA discovery, entity/service dispatch, backups,
restoration, and reload also passed: see the [HA test report](captures/ha_test_2026-09-08_181012/README.md).
A reload during an in-flight write exposed a connection race that was fixed and
[retested on hardware](captures/ha_test_2026-09-08_181523/README.md). Browser interactions, Bluetooth proxy transport,
and the complete Smart Irrigation/blueprint workflow remain untested. Close the Hunter app while HA connects.

1. Save a fresh full controller configuration externally. Confirm Program A and station names match HA; confirm the
   new sensors show the captured days/start times/runtimes and only physical stations have runtime numbers.
2. Use an unused Program B or C. **Keep all start slots disabled while testing nonzero durations.** Update both runtimes
   in one action, check HA write status, and inspect the readback through a separate fresh read/the Hunter app.
3. With that program's runtimes all zero, set and clear a start slot, change its name and weekdays, and verify each
   change in the Hunter app. Confirm unrelated Program A and unused fields remain unchanged. Test the extra time entities
   and weekday switches after enabling them in HA.
4. Change a program field in the phone app, disconnect the app, then change another field from HA. Verify the phone edit
   survives. Test a failed connection by making the controller unreachable **before** an edit; the action must fail without
   optimistic entity changes. Do not intentionally interrupt a live irrigation run to test write ambiguity.
5. After confirming controller clock alignment, arrange one supervised short scheduled run on the unused program,
   disconnect BLE before its start, and confirm both physical start and controller-owned shutoff. Restore the original
   program immediately afterwards and verify it. This step actually waters and should happen while we are at the device.
6. Trial the blueprint with known test duration sensors and a suitable daily program. Verify rejection of unavailable,
   stale, zero (default), and over-limit recommendations, multiple starts, and non-100% seasonal adjustment. Make test
   configuration changes with runtimes zero/start slots disabled as appropriate; restore the original configuration.

Additional hardware work before further features: verify `ProgrammableDaysOff` expiry/resume, seasonal adjustment
behavior and limits, clock jumps across scheduled starts, interval-date semantics, `LastRun`/log responses after scheduled and inhibited
runs, and cycle/soak sequencing. No new commands for these unverified capabilities are enabled here.
The app's local-wall-time clock encoding, a small clock correction, and continued timekeeping across BLE disconnect
were verified; automatic clock synchronization is not yet implemented in HA. See [clock synchronization](PROTOCOL.md#clock-synchronization-app-derived-and-hardware-tested-8-september-2026).

## Local verification

Use the project's configured Python interpreter with `-m pip install -r requirements-dev.txt`, then run
`-m unittest discover -v`. Optional HA-specific tests require Home Assistant and its dependencies, including
`bleak-retry-connector`, in the test environment. The local Python 3.15 environment could not build all Home Assistant
dependencies because Python development headers were missing. The full suite subsequently passed in the existing
Home Assistant Core Python 3.14.6 environment: 40 tests, no skips.
After the security fixes, the suite passed in that environment again: **53 tests, no skips**, including the new
service authorization regression test. From this project's root, run it with:

```shell
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$PWD:/home/jpmeijers/home-assistant-core" \
/home/jpmeijers/home-assistant-core/.venv/bin/python -m unittest discover -s tests -t .
```

Tests cover captured programs, preserved fields, limits, no-op writes, backups, BLE fragmentation, serialization,
nonzero/malformed statuses, lost acknowledgements/readbacks, and blueprint validation. They never connect to BLE hardware.
