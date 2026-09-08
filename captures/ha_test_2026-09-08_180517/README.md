# Interrupted HA test: reload race

Initial live HA run, 8 September 2026. Discovery, entry setup, seven entity platforms, and the Program B name edit
passed. Enabling a disabled weekday entity scheduled an automatic entry reload; the harness also reloaded immediately,
then started service edits before the delayed reload happened. That delayed reload overlapped a runtime service's
fresh read with the new coordinator's connection. Authentication errors and a response timeout followed.

The runtime write was not reached (failure was during its prewrite read). Cleanup also encountered connection errors;
the temporary HA process was interrupted and stopped. A subsequent direct BLE write restored `Program_B.Name` to
`Program B` with `Status: 0`. The next live test verified the original baseline, completed all edits/restoration,
and passed reload: see `../ha_test_2026-09-08_181012/README.md`.

The integration was fixed to share a per-address BLE session lock across coordinator reloads. Retained logs are
filtered to this integration/controller; unrelated discovery and HTTP traffic are omitted.
