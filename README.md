# Room

Indoor temperature and humidity on the Omarchy bar, from a local SwitchBot meter over Bluetooth LE. No cloud, no hub.

![Room temperature on the Omarchy bar](preview.png)

The pill sits in the **center** of the bar and shows something like `73.6°  52%`. Click it for both units, humidity, battery, RSSI, and last-seen. A dimmed pill means the last reading is older than two minutes.

Works with SwitchBot Meter, Meter Plus, Indoor/Outdoor Meter, Meter Pro, and Meter Pro CO2. One meter per install.

## Install

```bash
omarchy plugin add https://github.com/novique-ai/omarchy-room-sensor.git --enable
```

That clones the plugin into `~/.config/omarchy/plugins/novique.room/` and places **Room** in the center of the bar. Then install the local BLE reader (Python venv + user systemd unit, no sudo):

```bash
~/.config/omarchy/plugins/novique.room/install.sh
```

On a TTY with no meter bound yet, the installer scans for about 20 seconds and asks which MAC to use. If you already have `~/.config/room-sensor/config.json`, that address is kept.

## Bind a meter

```bash
room-temp --discover
room-temp --bind AA:BB:CC:DD:EE:FF
```

No pairing and no SwitchBot hub. The meter must be powered and in range.

## Use

| Action | How |
|---|---|
| Read | Look at the bar: `73.6°  52%` |
| Details | Click the pill |
| Notify | Right-click the pill |
| CLI | `room-temp` |

## Settings

| Setting | Default | Meaning |
|---|---|---|
| Temperature unit | `F` | Pill unit. The panel always lists °F and °C. |
| Stale after | `120` seconds | Dim the pill when advertisements stop. |
| Room name | empty | Panel title. Blank uses the meter model. |
| Show humidity on the pill | on | Hide it if you want a shorter pill. |

Move the pill if you want it somewhere else:

```bash
omarchy bar move novique.room --section right
```

## Remove

```bash
omarchy plugin remove novique.room
```

That only drops the bar plugin. To stop the reader:

```bash
~/.config/omarchy/plugins/novique.room/install.sh --uninstall
```

Add `--purge` to also delete config, last reading, and the venv.

## Requirements

Omarchy Quattro, a Bluetooth adapter, Python 3, and one supported SwitchBot T/H meter.

## Develop

```bash
node --test tests/*.test.js
python -m unittest discover -s sensor -v
omarchy plugin validate .
```

Edits under `~/.config/omarchy/plugins/novique.room/` reload the QML in the running shell. After changing `sensor/room_sensor.py`, re-run `install.sh` and `systemctl --user restart room-sensor.service`.
