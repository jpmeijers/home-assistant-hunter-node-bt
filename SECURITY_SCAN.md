# Security scan — 8 September 2026

Implementation update: findings 1–3 below have been addressed in the working tree. `set_program` now checks user
control permissions for the target program's editing entities; extraction validates paths and sizes and refuses
overwrites; Bluetooth JSON responses are capped at 64 KiB and PIN exchanges no longer queue notifications. Regression
tests were added. The original findings and evidence below describe the pre-fix code. The inherited PIN weakness remains.

Post-fix validation used `/home/jpmeijers/home-assistant-core/.venv/bin/python` (Python 3.14.6), with the project and
Home Assistant Core checkout on `PYTHONPATH`: **53 tests passed, no skips**. This includes restricted-user rejection,
unknown-user rejection, authorized program edits, and internal automation calls. Added `tools/__init__.py` to prevent
Home Assistant's `tools` package from shadowing the project's utilities during combined-checkout testing. These are
automated tests with mocked device access; no controller connection was made.

Reviewed the working tree's integration, protocol, configuration flow, entity and service handlers, diagnostics, developer tools, automation blueprint, tests, workflow, dependency declarations, and captured-artifact references. `PROTOCOL.md` supplied the device protocol and hardware-test context. Severity reflects prerequisites and impact; it is not a CVSS assessment.

Found three implementation issues and one inherited protocol weakness. No application code was changed and no Bluetooth connections or watering commands were made.

## 1. High: schedule service does not enforce user permissions

**Location:** `custom_components/hunter_node_bt/services.py:33–60`.

`hunter_node_bt.set_program` is registered directly with `hass.services.async_register`. Its handler checks device identity and whether the integration is loaded, but never examines `call.context.user_id` or checks the caller's control permissions before invoking the coordinator.

An authenticated user without permission to control the device, but with its device ID, can submit schedule changes through the service API. Clearing starts or runtimes can disable watering; changing starts, weekdays, and runtimes can cause unwanted automatic watering. Runtime validation and readback do not enforce authorization.

**Evidence:** traced the handler through the coordinator to protocol writes. Also inspected the local Home Assistant Core WebSocket handler and service dispatcher: they forward the caller context and execute the registered handler without adding device-specific authorization. Home Assistant's [permission documentation](https://developers.home-assistant.io/docs/auth_permissions/) explicitly requires custom service handlers to perform permission checks; entity services receive automatic checks. A live restricted-user API test was not run.

**Remediation:** resolve the calling user and require control permission for the affected target entities before any BLE access or write. Reject unknown users and unauthorized targets. Preserve intended handling of trusted internal automation calls. If the intended policy is administrator-only schedule editing, use Home Assistant's administrator-service registration helper. Add regression cases for restricted users, authorized users, unknown users, and internal automation contexts.

## 2. High: assembly extraction permits arbitrary file writes

**Location:** `tools/unpack_assembly_store.py:81–93`.

Assembly names come directly from the input store and are joined to `output_dir` without containment validation. Names such as `../outside.txt` escape that directory; absolute paths also override the output directory. Existing files are overwritten with the privileges of the user running the tool. A malicious assembly store could therefore overwrite source code or other writable files when a developer extracts it. This affects the developer utility, not the integration's normal runtime.

**Evidence:** constructed a one-entry XABA store in a temporary directory with a harmless payload and the name `../outside.txt`. Running `unpack()` wrote the marker outside the requested output subdirectory. The temporary directory was automatically removed.

**Remediation:** reject absolute paths and traversal components; resolve the destination and require it to remain below the resolved output directory. Handle symlink destinations explicitly, preferably extracting into a fresh private directory and refusing existing outputs. Validate all entry destinations before writing any files. Cover traversal, absolute paths, and symlink escapes with tests.

## 3. Medium: Bluetooth notification buffers have no size limits

**Location:** `custom_components/hunter_node_bt/protocol.py:115`, `263–279`; similar buffering occurs in `tools/ble_probe.py`.

The PIN notification queue has no maximum size and accepts packets after authentication, even though there is no remaining consumer. The JSON response accumulator grows until it sees a NUL terminator, with no byte limit. A malicious or compromised connected peripheral can send repeated PIN notifications or distinct unterminated response fragments to grow memory usage and consume processing time in Home Assistant.

**Evidence:** an isolated session accepted 10,000 queued PIN notifications and 200,000 unterminated response bytes without rejecting either. This was a bounded callback-level check, not a demonstration of process exhaustion over a real Bluetooth link. Response timeouts and short-lived sessions limit exposure, so actual exhaustion depends on notification throughput and session duration.

**Remediation:** bound response bytes and authentication queue depth, reject invalid PIN packet lengths at ingress, and ignore PIN notifications after authentication. Fail the session promptly when a limit is exceeded. Establish limits from captured legitimate responses with appropriate headroom and test overflow handling.

## 4. High, inherited protocol weakness: login can disclose the controller PIN

**Location:** `custom_components/hunter_node_bt/protocol.py:71–89`, `121–148`; `PROTOCOL.md`, “Session and PIN authentication”.

The client transmits the challenge alongside `PIN XOR challenge`, using a fixed byte transform rather than cryptographic authentication. The server is not authenticated before this response is sent. A malicious peripheral that the client connects to can solicit a login response and recover the PIN or a small candidate set. A captured exchange on an unencrypted link exposes the same information. The transform's special handling of zero and `0xAC` is lossy, so decoding is not uniquely reversible for every byte combination.

**Evidence:** the existing fake BLE client supplied its challenge to a session using a synthetic non-default PIN. Decoding the client's response and XORing its two fields recovered that PIN exactly. No actual controller PIN was extracted. The project documents successful operation without OS pairing or bonding; this scan did not measure link-layer encryption on hardware.

An attacker needs access to an observable unencrypted exchange or to a peripheral connection accepted by the client, plus proximity to the real controller to reuse the credential. Changing the four-digit PIN does not repair this protocol weakness.

**Remediation:** document the limited protection supplied by the PIN and avoid treating advertised names, service UUIDs, or Bluetooth addresses as authenticated identity. Robust protection requires device support for authenticated encryption or secure pairing whose enforcement has been verified. An integration-only packet change cannot solve this while retaining compatibility. Investigate supported firmware/pairing options before changing connection behavior.

## Additional hardening observations

- `tools/unpack_assembly_store.py:29–48` allocates the input-controlled XALZ output size without a cap. Bound per-assembly and total output sizes, and validate descriptor offsets and lengths before processing untrusted stores. No large allocation was attempted.
- `.github/workflows/validate.yaml` uses mutable action references (`main`, `master`, and `v4`). Pin reviewed full commit hashes to reduce supply-chain exposure. The workflow already restricts token permissions to `contents: read`; no action compromise was observed.
- Published captures and documentation contain real device identifiers and user-assigned station names. Diagnostics redact the controller name and serial number but retain station/program names. Consider synthetic fixtures and consistent redaction where those labels identify private locations. No non-default credential was identified by the targeted working-tree text search; this was not an exhaustive secret scan or Git-history scan.

## Validation and limitations

- Used the PyCharm-configured Python 3.15.0rc2 environment.
- `python -m unittest discover -s tests -t .`: 40 tests discovered, 36 passed, 4 skipped because Home Assistant is not installed in that environment.
- Ran isolated, bounded checks for extraction traversal, notification-buffer growth, and synthetic PIN disclosure. They made no network or hardware connections.
- Reviewed declared dependency ranges and installed versions. Installed versions included Bleak 3.0.2, PyYAML 6.0.3, Jinja2 3.1.6, and Ruff 0.16.6. Bandit and pip-audit were not installed; no automated SAST engine or dependency vulnerability-database audit was run. This report does not assert that dependencies are free of known vulnerabilities.
- Did not test deployed Home Assistant access controls end to end, Bluetooth packet capture, device firmware security, firmware update services, or Git history.
- Existing safeguards include bounded watering durations, serialized controller sessions, strict schedule patch validation, persisted prewrite backups, readback verification, and no automatic retry of ambiguous station-start writes.

Prioritize the service authorization check and extraction containment fix, then bound Bluetooth inputs. Track the inherited PIN weakness separately because it requires protocol/device support to fully resolve.
