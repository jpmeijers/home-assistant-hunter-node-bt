# Hunter NODE-BT for Home Assistant

This custom integration controls Hunter NODE-BT battery irrigation controllers locally over Bluetooth. It was built
from the documented and hardware-verified protocol in [PROTOCOL.md](PROTOCOL.md).

The integration provides:

- automatic Bluetooth discovery through Home Assistant;
- support for local Bluetooth adapters and active-connection ESPHome Bluetooth proxies;
- four-digit PIN authentication (the factory default is `0000`);
- one water valve entity per physical station;
- a timed `hunter_node_bt.start_watering` action;
- a stop-all button;
- battery, moisture, controller-state, and daily-runtime sensors.
- stored program A/B/C sensors, per-station runtime numbers, start-time controls, weekday switches, and program names;
- a verified `hunter_node_bt.set_program` action for editing a program in one BLE session;
- an optional blueprint for uploading daily duration sensors, including Smart Irrigation outputs.

The controller receives a finite duration with every start command and owns the watering timer. A lost Bluetooth
connection or Home Assistant restart therefore does not leave Home Assistant responsible for eventually stopping the
water. Program edits are stored on the controller and continue to apply while HA or Bluetooth is unavailable.
See [schedule editing and device testing](SCHEDULES.md) before enabling automatic duration uploads.

## Requirements

- Home Assistant with the Bluetooth integration configured.
- The NODE-BT in Bluetooth range. For a controller in a valve box, an ESPHome Bluetooth proxy with active connections
  enabled will usually provide better coverage.
- The Hunter mobile app disconnected while Home Assistant connects. NODE-BT accepts one BLE client at a time.
- The controller's four-digit PIN.

The integration currently has hardware coverage for a two-station NODE-BT with controller firmware `2.2A`, bootloader
`1.00`, and Bluetooth firmware `1.02`. Home Assistant setup, both station starts, and a stop command were manually
validated with this controller and a local Bluetooth adapter. One- and four-station controllers use the same documented
protocol but still need physical validation.

## Install

### HACS custom repository

1. In HACS, open **Integrations**, choose the menu, then **Custom repositories**.
2. Add this repository URL and select the **Integration** category.
3. Install **Hunter NODE-BT** and restart Home Assistant.

### Manual installation

1. Copy `custom_components/hunter_node_bt` into the `custom_components` directory under your Home Assistant
   configuration directory.
2. Restart Home Assistant.

## Configure

1. Wake the NODE-BT if it is not advertising, and close the Hunter app.
2. In Home Assistant, go to **Settings → Devices & services**.
3. Select the discovered **Hunter NODE-BT** card, or choose **Add integration** and search for **Hunter NODE-BT**.
4. Enter the PIN as four digits. Use `0000` if no custom PIN was configured.

Initial setup connects to the controller and reads its identity, station names, and state. If setup cannot connect,
confirm that the controller is awake, in range, and not connected to the Hunter app.

Opening a valve uses a safe default run time of 600 seconds (10 minutes). To change it, open the integration from
**Settings → Devices & services**, select **Configure**, enter the new default run time, and save.

## Use

Opening a station valve starts that station for the configured default duration. Closing any station valve sends the
controller's global stop command because the NODE-BT protocol does not provide a per-station stop. The **Stop all
watering** button sends the same command.

For an explicit duration, call `hunter_node_bt.start_watering` and target a station valve:

```yaml
action: hunter_node_bt.start_watering
target:
  entity_id: valve.pots
data:
  duration: 300
```

Durations are in seconds and must be between 1 and 3600. To conserve the controller's battery, Home Assistant polls it
once per hour and refreshes immediately after acknowledged commands. Changes made by a stored schedule, the physical
buttons, or the Hunter app can therefore take up to an hour to appear. Between refreshes, the remaining-time attribute
is the last value read from the controller rather than a locally calculated countdown.

## Troubleshooting and current limits

- If the device is unavailable, wake it and make sure the Hunter app is disconnected. Home Assistant will retry on the
  next update.
- A Bluetooth proxy must support active connections; passive advertisement forwarding is insufficient.
- A start whose acknowledgement is lost is treated as ambiguous and is not sent again automatically. This avoids
  restarting or extending an already-running watering timer.
- Station state values seen on live hardware are currently limited to idle. Active-state meanings were recovered from
  the official app and should be checked during the next device test.
- The schedule library was tested on the controller on 8 September, including a 30-second scheduled run with BLE
  disconnected and verified restoration. Live HA service dispatch, backup storage, and reload also passed; browser
  interactions and ESPHome proxy transport remain untested. See
  [the results and test procedure](SCHEDULES.md#device-test-procedure).
- The controller sorts and compacts start times. Start-time and runtime edits must use separate actions because a
  combined-array write produced incorrect start times during hardware testing.
- Odd/even and interval schedules are displayed and preserved when editing runtimes/start times. Setting `weekdays`
  explicitly switches a program to weekday mode. Editing odd/even/interval rules, stored-program execution, temporary
  suspension, seasonal adjustment, and firmware update are not exposed yet.

Development notes, protocol evidence, and the captured response samples are in [INVESTIGATION.md](INVESTIGATION.md),
[PROTOCOL.md](PROTOCOL.md), and [`captures/`](captures/).
