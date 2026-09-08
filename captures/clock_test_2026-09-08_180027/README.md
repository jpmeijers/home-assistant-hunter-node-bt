# Clock synchronization hardware test

Completed 8 September 2026, 20:00–20:01 SAST, using the local Bluetooth adapter and the integration's
`HunterNodeSession`. Controller: NODE-BT-707796, serial 16707796, firmware 2.2A.

- Authenticated and read configuration and idle state.
- Observed clock approximately 29 seconds behind South African local wall time.
- Wrote local wall time encoded as epoch seconds: `{"Controller":{"CurrentTime":1788897634}}`.
- Received integer `Status: 0`; immediate readback was `1788897635`.
- Disconnected, waited 15 seconds, and reconnected. Clock had advanced to `1788897657`.
- Readbacks were within three seconds of host local wall time at response completion, including BLE response latency.
- Programs A/B/C, stations, and configuration remained unchanged. `SettingsChangeDate` stayed unchanged too.
- Final state was idle; daily watering counter remained 270 seconds. No watering command or schedule edit was sent.

`transactions.jsonl` contains UTC host timestamps, transaction timing, commands, replies, and assertions' outcomes.
`baseline.json`, `after_sync.json`, `after_reconnect.json`, and `final_state.json` contain the corresponding readbacks.
`probe.py` preserves the executed test script. It is a hardware-writing test, not an offline unit test.

This establishes a small clock correction away from a programmed start and clock continuity while BLE is disconnected.
It does not test clock jumps across starts, DST, battery removal, a new scheduled run after synchronization, or an
ESPHome proxy. Automatic clock synchronization is not yet implemented in the HA integration.
