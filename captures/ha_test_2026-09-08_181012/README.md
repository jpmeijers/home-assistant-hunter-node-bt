# Home Assistant live integration test

Passed on 8 September 2026, using `/home/jpmeijers/home-assistant-core` and its existing Python 3.14.6 environment.
Home Assistant ran with a temporary configuration at `/tmp/ha-node-live-config2`, loading this integration via a
custom_components symlink. No mocks replaced Home Assistant's Bluetooth routing, config flow, entity platforms,
service registry, storage, or the physical controller.

Verified:

- HA Bluetooth discovered NODE-BT-707796 through local adapter hci0.
- Bluetooth confirmation/PIN config flow created and loaded the controller entry.
- All seven platforms loaded; 67 entities were registered, including entities disabled by default.
- Enabled Program B's Monday switch and let HA's automatic reload complete.
- Real service calls: `text.set_value`, `number.set_value`, `time.set_value`,
  `hunter_node_bt.clear_start_time`, `switch.turn_off`, `switch.turn_on`, and `hunter_node_bt.set_program`.
- Entity states reflected verified name, runtime, and start-time readbacks; clearing a start exposed `enabled: false`.
- Program backup persisted through HA's storage helper and write status became `verified`.
- Restored and freshly verified all three original programs, then reloaded and verified them again.
- HA stopped cleanly. No manual watering service was called. Program B had no enabled starts when nonzero runtimes
  were tested, and had zero runtimes when its start time was tested.

`events.jsonl` records completed assertions and calls. `entities.json` is the initial registry/state snapshot;
`baseline_programs.json` records the pre-test programs. `backup.json` is the backup observed during the test,
not a recommended restoration target. `probe.py` is the executed hardware-writing harness.

An earlier run (`../ha_test_2026-09-08_180517`) exposed overlapping BLE sessions when an entity-enable reload
occurred during an in-flight service call. Only the test name change was confirmed in that interrupted run;
the original name was restored through a direct BLE write before this successful run. The integration now shares
a per-address session lock across coordinator reloads. A regression test covers serialization across two controller
instances. The full suite passed: 40 tests, no skips, in the HA environment.

Limitations: this exercised HA services and state objects, not browser interactions, an ESPHome proxy, the complete
Smart Irrigation integration, or an actual daily blueprint trigger. Automatic clock synchronization remains unimplemented.
