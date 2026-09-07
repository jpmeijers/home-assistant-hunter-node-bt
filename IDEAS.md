Assuming this is the Hunter NODE-BT, the best architecture is controller-authoritative:

> The NODE-BT stores and executes schedules and enforces every watering timeout. Home Assistant provides visibility, temporary overrides, and manual commands—but is never responsible for eventually switching the water off.

That gives you both safety during communication failures and reliable summer watering when Home Assistant is unavailable.

## What existing integrations establish

Home Assistant does not have a dedicated irrigation-controller entity type. Existing integrations combine normal entity platforms:

* Modern Hunter Hydrawise exposes every irrigation zone as a water `ValveEntity`; opening it uses a controller-side automatic shutoff duration. [Hunter Hydrawise integration](https://www.home-assistant.io/integrations/hydrawise/)
* Rachio explicitly recommends configuring a maximum failsafe run time so the controller stops watering even if Home Assistant, an automation, or the API fails. [Rachio integration](https://www.home-assistant.io/integrations/rachio/)
* Rain Bird exposes zone controls plus a `start_irrigation` action requiring a duration, and shows controller schedules through calendars. [Rain Bird integration](https://www.home-assistant.io/integrations/rainbird/)
* RainMachine similarly uses a default zone duration and separate start/stop actions. [RainMachine integration](https://www.home-assistant.io/integrations/rainmachine)
* Melnor Bluetooth stores manual-watering duration and schedule settings in the device, exposed through switch, number, and time entities. [Melnor Bluetooth integration](https://www.home-assistant.io/integrations/melnor/)

Some older integrations use switches, but for a new integration the semantically correct primary entity is `ValveEntity` with `ValveDeviceClass.WATER`. [Home Assistant valve model](https://developers.home-assistant.io/docs/core/entity/valve/)

## Recommended Home Assistant model

Register one controller device. For multi-station models, make each station a child device so it can have its own name, entities, and Home Assistant area.

| Capability               | Home Assistant representation                     | Notes                                                             |
| ------------------------ | ------------------------------------------------- | ----------------------------------------------------------------- |
| Station manual control   | `valve`                                           | `WATER`, `OPEN` and `CLOSE`; no position support                  |
| Default manual duration  | `number`                                          | Per station, configuration category                               |
| Precise timed run        | `hunter_node_bt.start_watering` action            | Requires station and duration                                     |
| Stop everything          | `button.stop_all` plus `stop_all` action          | Idempotent and safe to retry                                      |
| Run stored Program A/B/C | Integration action or disabled-by-default buttons | Uses stored controller runtimes                                   |
| Program schedules        | Read-only `calendar` per program                  | Show expanded upcoming station runs                               |
| Remaining run time       | Duration `sensor`                                 | Controller-reported where possible                                |
| Next watering            | Timestamp `sensor`                                | Useful on dashboards and in automations                           |
| Battery                  | Battery percentage `sensor`                       | Add low-battery repair/notification                               |
| Rain/soil inhibit        | `binary_sensor`                                   | Only when fitted and reported                                     |
| Seasonal adjustment      | `number`, 10–300%                                 | Controller-side setting                                           |
| Temporary suspension     | Action with required expiry                       | Prefer this over an indefinite “off” switch                       |
| System Auto/Off state    | Diagnostic/config switch or sensor                | Avoid putting an easy permanent-off control on the main dashboard |
| Firmware                 | `update` eventually                               | Not in the first release                                          |

For schedules, calendars are suitable for displaying generated events, but they are not a natural editing interface for Hunter’s program matrix. Home Assistant calendars model events and recurring-event expansion, whereas NODE-BT programs contain start times, watering-day modes, station runtimes, sequencing, Cycle & Soak, and seasonal adjustment. [Calendar entity documentation](https://developers.home-assistant.io/docs/core/entity/calendar/)

The NODE-BT has three programs, up to eight start times per program, and runs enabled stations sequentially. [Hunter schedule documentation](https://www.hunterirrigation.com/support/node-bt-schedule)

## The safety contract

These should be hard invariants in both the Bluetooth library and integration:

1. **No indefinite start command**

   Every start must include a positive finite controller-side duration. The NODE-BT supports manual station runs from one second to twelve hours, but the integration should apply a much lower user-configurable safety ceiling. [Hunter manual operation](https://www.hunterirrigation.com/support/node-bt-manual-operation)

2. **Standard valve opening is still timed**

   `valve.open_valve` has no duration argument, so it must use the station’s configured default manual duration—perhaps initially 10 minutes. The custom `start_watering` action accepts an explicit duration but rejects anything above that station’s safety maximum.

3. **The timer must exist in the controller before water starts**

   If the protocol has one atomic “run station for N seconds” command, use it. If it uses multiple writes, write and verify the duration first, then issue start. Do not expose actuation until this behavior has been conclusively established.

4. **Never blindly retry an ambiguous start**

   If Bluetooth disappears immediately after sending start, the command may have succeeded. Reconnect and query state before retrying; otherwise a retry could restart or extend the countdown.

5. **Stop commands are different**

   Stop should be idempotent and may be retried with backoff. Home Assistant can also schedule a best-effort stop at the expected deadline, but this is merely supervision—the device timer remains the actual protection.

6. **Unknown is not closed**

   When communication fails, do not display the valve as closed. Preserve the last known state and deadline for diagnostic purposes, but mark the entity unavailable until the controller can be queried again.

7. **Keep schedules on the controller**

   Home Assistant automations should not be the primary scheduler. Weather-based logic can set a controller-side rain delay, suspension expiry, or seasonal adjustment in advance; the controller should still decide when each scheduled run begins.

There is also a useful NODE-BT hardware safeguard: Hunter states that its DC-latching solenoids unlatch when the batteries are depleted. [Hunter NODE-BT product guide](https://www.hunterirrigation.com/videos/node-bt-bluetoothr-enabled-wireless-valve-controller-product-guide) That does not protect against a mechanically stuck valve, so where uncontrolled water would cause serious damage, an independent flow meter and master shutoff remains worthwhile.

## Handling schedules safely

I would implement schedule support in two stages.

First release:

* Read all controller programs.
* Show upcoming runs in read-only calendars.
* Show next start and today’s expected watering duration.
* Permit only temporary, self-expiring suspension and seasonal adjustment.
* Leave program editing in the Hunter app.

Later release, after the protocol is well understood:

* Read the latest complete schedule immediately before editing.
* Preserve fields the integration does not understand.
* Detect phone-app changes using a snapshot hash or generation counter.
* Validate the complete schedule locally.
* Write atomically if the protocol supports it.
* Read everything back and compare field-for-field.
* Retain the previous snapshot for recovery.
* Refuse automated schedule rewrites if a partial Bluetooth transaction can leave a program in an unsafe or indeterminate state.

Hunter’s own offline scheduling follows a similar “edit a saved copy, then deploy it when connected” pattern. [NODE-BT offline scheduling](https://www.hunterirrigation.com/support/node-bt-offline-scheduling)

## Bluetooth implementation

Put the protocol in a separate asynchronous Python package, for example `hunter-node-bt`, and keep the Home Assistant integration as an adapter around that library. Home Assistant expects device/API-specific communication in a separately versioned dependency. [Integration development checklist](https://developers.home-assistant.io/docs/creating_component_code_review/)

For Home Assistant:

* Use Bluetooth discovery and a UI config flow.
* Use the controller serial number as the stable unique ID, not its Bluetooth address.
* Prompt for the NODE-BT passcode when necessary and redact it from logs and diagnostics. Hunter supports adding a controller passcode. [Controller settings](https://www.hunterirrigation.com/support/node-bt-controller-settings)
* Declare `bluetooth_adapters` as a dependency.
* Obtain the shared scanner from Home Assistant.
* Use `bleak-retry-connector`, a connection timeout of at least ten seconds, and a fresh `BleakClient` for each connection.
* Serialize all activity through one lock per controller.
* Connect, transact, verify, and disconnect; do not hold a permanent connection to a battery controller.
* Treat the phone app occupying the connection as a temporary communication failure and back off.

These are Home Assistant’s current Bluetooth recommendations. [Bluetooth integration development](https://developers.home-assistant.io/docs/bluetooth/)

Coordinator choice depends on what protocol capture reveals:

* If advertisements include useful status and active connections are only needed for reading/writing settings, use `ActiveBluetoothDataUpdateCoordinator`.
* If the NODE-BT communicates only through connected GATT operations, use an ordinary `DataUpdateCoordinator`. [Bluetooth data fetching](https://developers.home-assistant.io/docs/core/bluetooth/bluetooth_fetching_data)

Use adaptive updates rather than aggressive continuous polling:

* Immediately read back after a command.
* Poll dynamic state roughly every 30–60 seconds while idle if advertisements are insufficient.
* Poll more frequently during an expected run.
* Refresh static schedules and battery much less frequently.
* Back off after connection failures and recover automatically when the device reappears.

Because the controller may be in a buried valve box and Hunter quotes approximately 15 m Bluetooth range, an active-connection-capable ESPHome Bluetooth proxy near the controller will probably be more reliable than the Home Assistant host’s built-in adapter. Home Assistant officially supports active connections through suitable remote proxies. [Home Assistant Bluetooth documentation](https://www.home-assistant.io/integrations/bluetooth/)

## Recommended development order

1. Reverse-engineer authentication, complete state reads, timed station start, stop, and acknowledgement semantics.
2. Build the standalone async library with a fake transport and recorded-packet tests.
3. Build the Home Assistant MVP: discovery, passcode, battery/status sensors, timed valves, explicit run action, and stop-all.
4. Add read-only schedules and calendars.
5. Add suspension, seasonal adjustment, rain/soil status, and stored-program execution.
6. Only then consider schedule writing.
7. Target at least Home Assistant’s Silver quality level initially: automatic recovery, correct unavailable states, translations, diagnostics, and comprehensive failure tests. [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)

The critical test cases are lost communication after start, lost acknowledgement, duplicate start requests, Home Assistant restarting mid-run, phone-app contention, controller clock drift, low battery, physical-button watering, and interruption halfway through schedule programming.

The central design decision is therefore clear: **Home Assistant may request watering, but only the NODE-BT may own an active watering deadline.**
