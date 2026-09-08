# Schedule hardware tests, 8 September 2026

Device: NODE-BT-707796, two stations, controller firmware 2.2A, Bluetooth firmware 1.02.
Transport: local Bleak adapter, default PIN, actual `HunterNodeSession.set_program` implementation.
Home Assistant's frontend and Bluetooth proxies were not exercised by this test harness.

## Configuration edits

The successful final edit pass ran at 17:17–17:18 UTC. All tests used unused Program B. Start times remained disabled
while testing nonzero runtimes; runtimes were zero while testing enabled start times.

Passed: batch and individual runtimes, zero runtimes, short program name, weekday selection, start-time replacement,
individual start edit, weekday switch patch, no-op edit, clearing all starts, preservation of an independently written
program name, rejection of a nonexistent station, excessive runtime, and incompatible daily-duration synchronization.
Restoration was read back and verified at 17:18:45 UTC: all three programs and all station configuration objects matched
the saved baseline; controller settings matched except naturally changing clock/settings timestamps; controller idle.

## Findings that required implementation changes

1. Names of 16 and 32 ASCII characters were acknowledged but truncated to 14. A 12-character name was retained.
   The integration now limits new names to 14 UTF-8 bytes (the byte policy for non-ASCII remains conservative).
2. Enabled starts are sorted and packed at the front of the array. The integration now normalizes writes accordingly;
   start positions cannot be treated as permanent slot identities.
3. During a full program restoration, clearing starts together with zero runtimes returned two midnight starts instead
   of disabled values. Runtimes stayed zero, so this did not water. A subsequent separate start-array clear worked.
   The precise firmware cause was not isolated; the integration rejects combined start/runtime array edits.
4. Duplicate starts were retained in readback. Their execution was not tested, so the integration rejects duplicates.

## Evidence files

- `baseline.json` and `baseline_state.json`: original configuration and idle state, saved before any write.
- `transactions.jsonl`: command/response pairs, including failed expectations, normalization experiments, and restores.
  PIN exchanges are not logged. Recording started after the first failed long-name expectation.
- `events.jsonl`: progress, timestamps, observations, successful checks, and restoration confirmations.
- `prewrite_B.json`: rolling last pre-write program snapshot used by the integration callback in the edit tests.
- `scheduled_configuration.json`: configuration uploaded for the separate autonomous-run test.
- `final_configuration.json` and `final_state.json`: latest verified restoration, updated after each test phase.

No controller clock, seasonal adjustment, rain suspension, sensor, cycle/soak, firmware, or factory-reset settings were
written. The independently edited name was sent with the raw protocol, simulating an intervening client edit; it was not
a physical phone-app test.

## Autonomous scheduled run

Program B was set to Tuesday at 19:21 on the controller clock, station 1 (Pots) for 30 seconds, station 2 zero.
Name/day, start-time, and runtime writes were separate and individually verified. BLE disconnected at 17:19:45 UTC
and remained disconnected through the expected start/stop window, reconnecting after 17:22:19 UTC. No manual start or
stop command was sent. At 17:22:24 UTC the controller reported idle, all station remaining times zero, and:

```json
{"StartEvent":2,"StartTime":1788895291,"Station":1,"RunTime":30,"StopEvent":1}
```

The daily runtime counter rose from 240 to 270 seconds only after the run. The configuration and all station settings
were restored and verified at 17:22:33 UTC, with the controller idle. The user subsequently confirmed: "The water ran
on pots for 30 seconds." Physical operation therefore corroborates the controller's completed-run telemetry while
BLE was disconnected.

The controller clock was about host Unix time +7,170 seconds. Interpreting its epoch digits as a local clock gave a
run window of roughly 19:21:30–19:22:00 SAST. `LastRun.StartTime` is 31 seconds later than the configured controller
start; whether that is completion time or scheduler latency remains unresolved. No timestamp normalization was added
to the integration based on this single observation.

`after_scheduled_state.json` and `after_scheduled_last_run.json` preserve the post-run responses. The final
configuration deliberately differs from baseline only in naturally changing timestamps (settings and controller time);
the separate live state also retains the additional 30 seconds in its daily runtime counter.
