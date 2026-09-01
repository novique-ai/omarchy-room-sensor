# Room

Indoor temperature and humidity on the [Omarchy](https://omarchy.org/) bar,
read from a local SwitchBot Meter Plus. No cloud, no hub.

The pill sits in the **center** of the bar, next to the clock, and shows
something like `73.4°  47%`. Click it for battery, RSSI, and last-seen.

It reads `~/.local/state/room-sensor/status.json`, which the
`room-sensor.service` user unit keeps current from BLE advertisements.

## Install

```bash
omarchy plugin add https://github.com/novique-ai/omarchy-room-sensor.git --enable
omarchy bar put novique.room --after omarchy.clock --section center
```

The local reader must already be running:

```bash
systemctl --user enable --now room-sensor.service
room-temp
```

## Use

| Action | How |
|---|---|
| Read | Look at the bar: `73.4°  47%` |
| Details | Click the pill |
| Notify | Right-click the pill |
| CLI | `room-temp` |
| HTTP | `curl -s http://127.0.0.1:18787/status` |

A dimmed pill means the last reading is older than two minutes.

## Remove

```bash
omarchy plugin remove novique.room
```

That only drops the bar plugin. The BLE reader (`room-sensor.service`) is
separate.

## Develop

```bash
node --test tests/*.test.js
omarchy plugin validate .
```

Edits under `~/.config/omarchy/plugins/novique.room/` reload in the running
shell.
