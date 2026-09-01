# Room sensor V1 — marketplace-ready SwitchBot T/H pill

Date: 2026-09-01
Status: draft for review
Repo: [novique-ai/omarchy-room-sensor](https://github.com/novique-ai/omarchy-room-sensor)
Plugin id: `novique.room`
Version: `1.1.0`

## Goal

Ship a stranger-installable Omarchy bar plugin that shows indoor temperature and humidity from **one** local SwitchBot thermo-hygrometer over Bluetooth LE. No cloud, no hub, no pairing.

V1 is approach A: one bound MAC, the whole SwitchBot T/H advertisement family. V2 (not built here) is a second Meter Plus from the same 2-pack on the same machine.

## Non-goals (V1)

- Multiple meters on the bar, `allowMultiple`, or a room list
- Per-widget MAC picker in Omarchy settings
- Hub 2, Weather Station, Govee, Xiaomi, Aqara, or any other BLE encoding
- Temperature-threshold alerts, charts, history
- `omarchy plugin add` running `install.sh` (the marketplace installer never runs hooks)
- HTTP status server on by default

## Architecture

Two processes. The bar stays inside `omarchy-shell`. BLE stays in a user systemd unit. Quickshell never talks to BlueZ.

```
SwitchBot Meter / Plus / Outdoor / Pro / Pro CO2
        │  BLE advertisement (UUID 0xFD3D, company 0x0969)
        ▼
room-sensor.service          # bleak + pyswitchbot, user unit
        │  atomic write
        ▼
~/.local/state/room-sensor/status.json
        │  FileView watch
        ▼
novique.room Service.qml  →  bar pill + details panel
```

Runtime paths stay where they already are on this machine, so V1 is an upgrade, not a reinstall:

| What | Where |
|---|---|
| Plugin (QML) | `~/.config/omarchy/plugins/novique.room/` |
| Reader + venv | `~/.local/share/room-sensor/` |
| Config | `~/.config/room-sensor/config.json` |
| Latest reading | `~/.local/state/room-sensor/status.json` |
| User unit | `~/.config/systemd/user/room-sensor.service` |
| CLI | `~/.local/bin/room-temp` |

`omarchy plugin update` must not trash the venv or the running unit. `install.sh` copies the reader *out* of the plugin folder into XDG data. The plugin tree is the source; `~/.local/share/room-sensor/` is the runtime.

## Repository layout

```
omarchy-room-sensor/
  BarWidget.qml
  Panel.qml
  Service.qml
  Model.js
  manifest.json
  LICENSE
  README.md
  preview.png                 # from /home/clayton/Pictures/RoomTemp.png
  install.sh                  # user-run, no sudo
  sensor/
    room_sensor.py
    test_room_sensor.py
    requirements.txt          # bleak, pyswitchbot. aiohttp is a lazy extra, not required to start.
    room-sensor.service
  tests/
    load.js
    model.test.js
  docs/superpowers/specs/
```

The Python currently living only at `~/.local/share/room-sensor/` moves into `sensor/` in git. `install.sh` installs it to XDG data.

## Decoder and device family

Use pyswitchbot’s `process_wosensorth` / `process_wosensorth_c`. Stop rejecting every device type except Meter Plus (`i` / `I`).

Accepted BLE types (UUID `0xFD3D`, company `0x0969`):

| Product | Type byte | Parser | Extra |
|---|---|---|---|
| Meter | `T` / `t` | `process_wosensorth` | temp, humidity, battery |
| Meter Plus | `i` / `I` | same | same |
| Indoor/Outdoor Meter | `w` / `W` | same | same |
| Meter Pro | `4` / `0x14` | same | same |
| Meter Pro CO2 | `5` / `0x15` | `process_wosensorth_c` | + `co2` ppm |

Bind **one** address. Last-wins across every Meter Plus in range is a bug: once a MAC is configured, ignore every other advertisement.

If config has no MAC, persist the first matching T/H advertisement and use only that afterwards.

## Config and status.json

`~/.config/room-sensor/config.json`:

```json
{
  "address": "C8:92:04:06:1C:2C",
  "stale_seconds": 120,
  "scanner_restart_seconds": 90,
  "http": false,
  "listen": "127.0.0.1",
  "port": 18787
}
```

- `address` is the bound MAC. Empty or missing means “bind the first matching meter, then write it back.”
- `http` defaults to `false`. When `true`, serve `/status` on `listen:port` (localhost only). `aiohttp` is imported lazily inside the HTTP path; the default unit starts with only `bleak` and `pyswitchbot`. If HTTP is enabled and `aiohttp` is missing, log an error and keep scanning.
- V2 will add `sensors: [{ "address", "label" }]`. A bare `address` remains valid and means a one-item list. Do not introduce `sensors` in V1.

`status.json` stays **one object**. Add optional `co2`. Keep current keys so the live widget does not break mid-upgrade:

```json
{
  "address": "C8:92:04:06:1C:2C",
  "model": "Meter Plus",
  "temperature_c": 22.5,
  "temperature_f": 72.5,
  "humidity": 51,
  "battery": 100,
  "rssi": -55,
  "co2": null,
  "fahrenheit_display": true,
  "last_seen": "2026-09-01T07:53:44-05:00"
}
```

Omit `co2` or set it `null` when the meter has none. Plugin treats it as optional. `battery` and `rssi` may be `null`; CLI and panel must not crash.

V2 may add a `sensors` array *beside* these keys, not instead of them, so a V1 plugin still shows the primary reading.

## Install, bind, remove

Marketplace users type:

```bash
omarchy plugin add https://github.com/novique-ai/omarchy-room-sensor.git --enable
```

`--enable` places the pill from the manifest: section `center`, `allowMultiple: false`. No `omarchy bar put --after omarchy.clock`. That is this desktop’s layout, not the product.

Then:

```bash
~/.config/omarchy/plugins/novique.room/install.sh
```

`install.sh` (idempotent, no sudo):

1. Require `python3` and a Bluetooth stack. Fail with a short message if either is missing.
2. Create `~/.local/share/room-sensor/.venv` and install `sensor/requirements.txt`.
3. Copy `sensor/room_sensor.py` into `~/.local/share/room-sensor/`.
4. Install `sensor/room-sensor.service` as a user unit.
5. Symlink `room-temp` to `~/.local/bin/room-temp` (`python … --print` remains the default invocation).
6. Bind a MAC (below).
7. `systemctl --user enable --now room-sensor.service`.

Bind:

1. Config already has a MAC → keep it (this machine’s upgrade path).
2. TTY and no MAC → 20s scan, print address / model / temp / humidity / RSSI, user picks one, write config.
3. Non-interactive and no MAC → start the unit anyway; first matching advertisement is persisted.

Later:

```bash
room-temp --discover
room-temp --bind AA:BB:CC:DD:EE:FF
```

No pairing. The meter must be powered and in range.

Remove:

```bash
omarchy plugin remove novique.room
install.sh --uninstall              # stop unit, leave config + last reading + venv
install.sh --uninstall --purge      # also drop config, state, venv, symlink
```

Optional configure note in the README, not a required install step:

```bash
omarchy bar move novique.room --section right
```

## Bar and panel

Pill: compact text, e.g. `72.5°  51%`. Unit from settings (`F` / `C`). Dimmed when stale. No icon, no color-by-temperature.

| Surface | Behavior |
|---|---|
| Hover | Existing `Model.tooltip()` (both units, humidity, battery, last-seen). `tooltipText` is no longer empty. |
| Right-click | Notification from the in-process reading. Do not shell out to `room-temp`. |
| Panel title | Settings label if set, otherwise the model name (`Meter Plus`, …). |
| Temp | `72.5°F  /  22.5°C` |
| Humidity | `Humidity  51%` |
| CO2 | `CO₂  842 ppm` only when present |
| Battery / RSSI | Omit the row when the value is null |
| Last seen | Relative (`12s ago`) plus a short clock, not the raw ISO stamp |
| Bound MAC | Muted caption so the user can confirm which meter |
| Empty / error | Distinct copy: Bluetooth off, no meter bound, waiting for an advertisement, stale |
| Low battery | Panel warning when battery ≤ 15%. No notification spam. |

Right-click and the panel both use `Service.qml`’s reading, so a marketplace install does not depend on `~/.local/bin` being on the bar’s PATH.

Widget settings (manifest schema):

| Key | Type | Default | Purpose |
|---|---|---|---|
| `unit` | enum `F` / `C` | `F` | Pill unit. Panel always lists both. |
| `staleSeconds` | integer 30–600 | `120` | Dim when `last_seen` is older than this. |
| `label` | string | `""` | Panel title. Empty → model name. |
| `showHumidity` | boolean | `true` | Include humidity on the pill. |

No MAC field in the widget schema for V1. Binding stays CLI / `install.sh`.

## README and marketplace

`/home/clayton/Pictures/RoomTemp.png` is the catalog image:

- `preview.png` at the repo root (marketplace card)
- README hero immediately under the one-line description

Opening line:

> Indoor temperature and humidity on the Omarchy bar, from a local SwitchBot meter over Bluetooth LE. No cloud, no hub.

README order: hero screenshot, what it shows, install (the two commands above), bind a meter, use, settings, remove, requirements, develop.

Manifest description: “Indoor temperature and humidity from a local SwitchBot BLE meter.” Aliases keep `switchbot` and add `ble`. Version `1.1.0`.

Marketplace submit: category **Info**; tags **bar**, **temperature**, **bluetooth**. Maintainer notes: user-level systemd unit, BLE scan via BlueZ D-Bus, no sudo, `install.sh` is manual because `omarchy plugin add` never runs hooks.

Requirements: Omarchy Quattro, Bluetooth, Python 3, one supported SwitchBot T/H meter.

## Testing

Python, against captured advertisements (not a live scan in CI):

- Existing Meter Plus frame (`C8:92:04:06:1C:2C`)
- Meter (`T` / `t`)
- Indoor/Outdoor (`w` / `W`)
- Meter Pro CO2 (`5`) including optional `co2`
- Non-T/H SwitchBot ad ignored
- Configured MAC wins; a second Plus in range does not overwrite
- CLI does not crash when `battery` or `rssi` is null
- Stale flag

JavaScript (`Model.js`):

- Existing parse / stale / bar-label tests
- Optional `co2` round-trips
- Humidity omitted from the pill when `showHumidity` is false
- Tooltip non-empty
- Relative last-seen lives in `Model.js` (`formatLastSeen(iso, nowMs)` → e.g. `12s ago`) so the panel and tests share one helper

Live check on this machine: existing Plus at `C8:92:04:06:1C:2C` still paints the bar after upgrade. Do not bind the second 2-pack meter in V1.

Also: `omarchy plugin validate .` and `qmllint` on the QML entry points.

## V2 (not built)

The second device is another Meter Plus from the same 2-pack — same advertisements, different MAC.

- Config grows `sensors: [{ address, label }]`. V1’s bare `address` remains a one-item list.
- `status.json` may add `sensors: [ ... ]` beside the current keys so a V1 plugin still shows the primary meter.
- Manifest may then set `allowMultiple: true` (one pill per meter) or keep one pill and list rooms in the panel. Decide when both devices are live.
- Discovery already lists every T/H meter; V2 is “use more than one of those rows.”

## Migration on this machine

`config.json` already has `address: "C8:92:04:06:1C:2C"`. `install.sh` must keep it. The running `room-sensor.service` is replaced in place (same unit name, same ExecStart path under XDG data). After V1, the pill, CLI, and status file still work without re-binding.
