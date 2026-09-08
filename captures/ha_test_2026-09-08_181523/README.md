# Live write/reload overlap regression

Passed 8 September 2026 using the same HA Core environment and temporary configuration as
`../ha_test_2026-09-08_181012`. Executed `probe.py --reload`.

The harness called HA's `text.set_value` for Program B, waited until that operation acquired the BLE session lock,
then requested an integration reload while the operation was in progress. The old coordinator completed its write;
the new coordinator connected afterward, loaded successfully, and read the changed name. Both controller instances
were verified to share the same lock. No authentication collision occurred.

The original name was then restored. A fresh read verified all three programs exactly matched the pre-test baseline,
and HA stopped cleanly. No watering or start-time/runtime edits were made.

`events.jsonl` records assertions, `baseline_programs.json` and `final_programs.json` record the unchanged final
programs, and `home-assistant.log` retains only controller/integration-related log lines.
