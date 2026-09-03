#!/usr/bin/env python3
"""Local SwitchBot Meter Plus reader: BLE advertisements → CLI + HTTP /status and /history."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from bleak import BleakScanner
from switchbot.adv_parsers.meter import process_wosensorth, process_wosensorth_c

def _xdg_dir(env_name: str, fallback: str) -> Path:
    value = os.environ.get(env_name) or ""
    if value:
        return Path(value).expanduser()
    return Path.home() / fallback


CONFIG_PATH = _xdg_dir("XDG_CONFIG_HOME", ".config") / "room-sensor" / "config.json"
STATE_PATH = _xdg_dir("XDG_STATE_HOME", ".local/state") / "room-sensor" / "status.json"
HISTORY_PATH = _xdg_dir("XDG_STATE_HOME", ".local/state") / "room-sensor" / "history.jsonl"

DEFAULT_CONFIG = {
    "address": "",
    "listen": "127.0.0.1",
    "port": 18787,
    "stale_seconds": 120,
    "scanner_restart_seconds": 90,
    "http": False,
    "history": True,
    "history_interval_seconds": 60,
    "history_retention_hours": 168,
}

FD3D = "0000fd3d-0000-1000-8000-00805f9b34fb"
SWITCHBOT_COMPANY_ID = 0x0969


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    cfg["address"] = str(cfg.get("address") or "").upper()
    cfg["http"] = bool(cfg.get("http", False))
    cfg["history"] = bool(cfg.get("history", True))
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        CONFIG_PATH,
        {
            "address": str(cfg.get("address") or "").upper(),
            "listen": cfg.get("listen", DEFAULT_CONFIG["listen"]),
            "port": int(cfg.get("port", DEFAULT_CONFIG["port"])),
            "stale_seconds": int(cfg.get("stale_seconds", DEFAULT_CONFIG["stale_seconds"])),
            "scanner_restart_seconds": int(
                cfg.get("scanner_restart_seconds", DEFAULT_CONFIG["scanner_restart_seconds"])
            ),
            "http": bool(cfg.get("http", False)),
            "history": bool(cfg.get("history", True)),
            "history_interval_seconds": int(
                cfg.get("history_interval_seconds", DEFAULT_CONFIG["history_interval_seconds"])
            ),
            "history_retention_hours": int(
                cfg.get("history_retention_hours", DEFAULT_CONFIG["history_retention_hours"])
            ),
        },
    )


def bind_address(address: str, path: Path | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    target = path or CONFIG_PATH
    if target.exists():
        cfg.update(json.loads(target.read_text()))
    cfg["address"] = str(address).strip().upper()
    if path is None:
        save_config(cfg)
        return cfg
    atomic_write_json(
        target,
        {
            "address": cfg["address"],
            "listen": cfg.get("listen", DEFAULT_CONFIG["listen"]),
            "port": int(cfg.get("port", DEFAULT_CONFIG["port"])),
            "stale_seconds": int(cfg.get("stale_seconds", DEFAULT_CONFIG["stale_seconds"])),
            "scanner_restart_seconds": int(
                cfg.get("scanner_restart_seconds", DEFAULT_CONFIG["scanner_restart_seconds"])
            ),
            "http": bool(cfg.get("http", False)),
            "history": bool(cfg.get("history", True)),
            "history_interval_seconds": int(
                cfg.get("history_interval_seconds", DEFAULT_CONFIG["history_interval_seconds"])
            ),
            "history_retention_hours": int(
                cfg.get("history_retention_hours", DEFAULT_CONFIG["history_retention_hours"])
            ),
        },
    )
    return cfg


def now_local() -> datetime:
    return datetime.now().astimezone()


def round_temp(value: float) -> float:
    return round(float(value) * 10) / 10


TH_TYPES: dict[int, tuple[str, bool]] = {
    0x54: ("Meter", False),
    0x74: ("Meter", False),
    0x69: ("Meter Plus", False),
    0x49: ("Meter Plus", False),
    0x77: ("Indoor/Outdoor Meter", False),
    0x57: ("Indoor/Outdoor Meter", False),
    0x34: ("Meter Pro", False),
    0x14: ("Meter Pro", False),
    0x35: ("Meter Pro CO2", True),
    0x15: ("Meter Pro CO2", True),
}


def decode_advertisement(
    address: str,
    rssi: int | None,
    service_data: dict[str, bytes],
    manufacturer_data: dict[int, bytes],
) -> dict[str, Any] | None:
    """Decode a SwitchBot T/H advertisement. Returns None if it is not one."""
    sd = None
    for uuid, data in service_data.items():
        if uuid.lower().endswith("fd3d") or uuid.lower().endswith("0d00"):
            sd = data
            break
    if sd is None and service_data:
        sd = next(iter(service_data.values()))

    mfr = manufacturer_data.get(SWITCHBOT_COMPANY_ID)
    if mfr is None:
        mfr = manufacturer_data.get(2409)

    if not sd and not mfr:
        return None

    model = "Meter"
    has_co2 = False
    if sd:
        mapped = TH_TYPES.get(sd[0] & 0b01111111)
        if mapped is None:
            return None
        model, has_co2 = mapped

    parsed = process_wosensorth_c(sd, mfr) if has_co2 else process_wosensorth(sd, mfr)
    if not parsed:
        return None

    reading = {
        "address": address.upper(),
        "model": model,
        "temperature_c": round_temp(parsed["temperature"]),
        "temperature_f": round_temp(parsed["temp"]["f"]),
        "humidity": int(parsed["humidity"]),
        "battery": int(parsed["battery"]) if parsed.get("battery") is not None else None,
        "rssi": int(rssi) if rssi is not None else None,
        "fahrenheit_display": bool(parsed.get("fahrenheit")),
        "last_seen": now_local().isoformat(timespec="seconds"),
        "reader_state": "ok",
    }
    if parsed.get("co2") is not None:
        reading["co2"] = int(parsed["co2"])
    return reading


def is_target(address: str, configured_address: str | None = None) -> bool:
    configured = str(configured_address or "").strip().upper()
    if not configured:
        return True
    return address.upper() == configured


def _parse_last_seen(reading: dict[str, Any]) -> datetime | None:
    raw = reading.get("last_seen")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def is_stale(reading: dict[str, Any], now: datetime, stale_seconds: int) -> bool:
    seen = _parse_last_seen(reading)
    if seen is None:
        return True
    return (now - seen).total_seconds() > stale_seconds


def format_cli(reading: dict[str, Any], now: datetime | None = None, stale_seconds: int = 120) -> str:
    now = now or now_local()
    stale = is_stale(reading, now, stale_seconds)
    lines = [
        f"Temperature: {reading['temperature_f']:.1f}°F / {reading['temperature_c']:.1f}°C",
        f"Humidity:    {reading['humidity']}%",
    ]
    if reading.get("co2") is not None:
        lines.append(f"CO2:         {reading['co2']} ppm")
    if reading.get("battery") is not None:
        lines.append(f"Battery:     {reading['battery']}%")
    if reading.get("rssi") is not None:
        lines.append(f"RSSI:        {reading['rssi']} dBm")
    if reading.get("model"):
        lines.append(f"Model:       {reading['model']}")
    if reading.get("address"):
        lines.append(f"Address:     {reading['address']}")
    if reading.get("last_seen"):
        lines.append(f"Last seen:   {reading['last_seen']}")
    if stale:
        lines.append("Status:      STALE")
    return "\n".join(lines) + "\n"


def format_status_json(
    reading: dict[str, Any],
    now: datetime | None = None,
    stale_seconds: int = 120,
    trend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or now_local()
    body: dict[str, Any] = {
        "temperature_f": reading.get("temperature_f"),
        "temperature_c": reading.get("temperature_c"),
        "humidity": reading.get("humidity"),
        "battery": reading.get("battery"),
        "rssi": reading.get("rssi"),
        "last_seen": reading.get("last_seen"),
        "stale": is_stale(reading, now, stale_seconds),
        "address": reading.get("address"),
        "model": reading.get("model"),
        "reader_state": reading.get("reader_state") or "ok",
    }
    if reading.get("co2") is not None:
        body["co2"] = reading["co2"]
    if trend:
        body["trend"] = trend
    return body


def format_discover_table(readings: list[dict[str, Any]]) -> str:
    if not readings:
        return "no SwitchBot T/H meters found\n"
    header = f"{'ADDRESS':<17}  {'MODEL':<22}  {'TEMP':<7}  {'HUM':<4}  {'RSSI'}"
    lines = [header]
    for reading in readings:
        temp = reading.get("temperature_f")
        temp_s = f"{temp:.1f}°F" if isinstance(temp, (int, float)) else "—"
        hum = reading.get("humidity")
        hum_s = f"{hum}%" if hum is not None else "—"
        rssi = reading.get("rssi")
        rssi_s = str(rssi) if rssi is not None else "—"
        lines.append(
            f"{reading.get('address', ''):<17}  {str(reading.get('model') or ''):<22}  {temp_s:<7}  {hum_s:<4}  {rssi_s}"
        )
    return "\n".join(lines) + "\n"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="status.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return None


HISTORY_FIELDS = ("temperature_c", "temperature_f", "humidity", "battery", "co2")
HISTORY_PRUNE_EVERY = 500
SPARK_CHARS = "▁▂▃▄▅▆▇█"
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
LABEL_WIDTH = 13
INDENT = " " * LABEL_WIDTH
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)([smhd])")
_DURATION_FULL = re.compile(r"(?:\d+(?:\.\d+)?[smhd])+")
_BARE_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def parse_duration(text: str) -> timedelta:
    """Read 45s / 90m / 2h / 3d / 1h30m. A bare number means minutes."""
    raw = str(text or "").strip().lower().replace(" ", "")
    if not raw:
        raise ValueError("empty duration; try 45s, 90m, 2h, 3d, or 1h30m")
    if _BARE_NUMBER.fullmatch(raw):
        seconds = float(raw) * 60
    elif _DURATION_FULL.fullmatch(raw):
        seconds = sum(float(v) * DURATION_UNITS[u] for v, u in _DURATION_PART.findall(raw))
    else:
        raise ValueError(f"cannot read duration {text!r}; try 45s, 90m, 2h, 3d, or 1h30m")
    if seconds <= 0:
        raise ValueError(f"duration {text!r} must be positive")
    return timedelta(seconds=seconds)


def window_label(text: str) -> str:
    """Echo the user's own --since text, giving a bare number its implied unit."""
    raw = str(text or "").strip().lower().replace(" ", "")
    return f"{raw}m" if _BARE_NUMBER.fullmatch(raw) else raw


def history_row(reading: dict[str, Any], when: datetime | None = None) -> dict[str, Any]:
    stamp = reading.get("last_seen") or (when or now_local()).isoformat(timespec="seconds")
    row: dict[str, Any] = {"time": stamp}
    for key in HISTORY_FIELDS:
        value = reading.get(key)
        if value is not None:
            row[key] = value
    return row


def row_time(row: Any) -> datetime | None:
    raw = row.get("time") if isinstance(row, dict) else None
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.astimezone()


def _numeric(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def append_history(row: dict[str, Any], path: Path | None = None) -> None:
    target = path or HISTORY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def read_history(
    since: timedelta | None = None,
    path: Path | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Every recorded row inside the window, oldest first. Junk lines are skipped."""
    target = path or HISTORY_PATH
    if not target.exists():
        return []
    cutoff = ((now or now_local()) - since) if since is not None else None
    rows: list[dict[str, Any]] = []
    with target.open() as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            stamp = row_time(row)
            if stamp is None:
                continue
            if cutoff is not None and stamp < cutoff:
                continue
            rows.append(row)
    rows.sort(key=row_time)
    return rows


def latest_history_time(path: Path | None = None) -> datetime | None:
    rows = read_history(path=path)
    return row_time(rows[-1]) if rows else None


def atomic_write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="history.", suffix=".jsonl", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def prune_history(
    retention: timedelta,
    path: Path | None = None,
    now: datetime | None = None,
) -> int:
    """Drop rows older than the retention window. Returns how many lines went."""
    target = path or HISTORY_PATH
    if not target.exists():
        return 0
    cutoff = (now or now_local()) - retention
    kept: list[str] = []
    dropped = 0
    with target.open() as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                dropped += 1
                continue
            stamp = row_time(row)
            if stamp is None or stamp < cutoff:
                dropped += 1
                continue
            kept.append(stripped)
    if dropped:
        atomic_write_lines(target, kept)
    return dropped


def _tidy(value: float) -> float | int:
    rounded = round(float(value), 1)
    return int(rounded) if rounded.is_integer() else rounded


def _ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((r for r in rows if row_time(r) is not None), key=row_time)


def summarize_history(
    rows: list[dict[str, Any]],
    window: timedelta | None = None,
) -> dict[str, Any] | None:
    ordered = _ordered(rows)
    if not ordered:
        return None
    summary: dict[str, Any] = {
        "samples": len(ordered),
        "first_time": row_time(ordered[0]).isoformat(timespec="seconds"),
        "last_time": row_time(ordered[-1]).isoformat(timespec="seconds"),
        "series": {},
    }
    if window is not None:
        summary["window_seconds"] = int(window.total_seconds())
    for key in HISTORY_FIELDS:
        values = [r[key] for r in ordered if _numeric(r, key)]
        if not values:
            continue
        summary["series"][key] = {
            "first": values[0],
            "last": values[-1],
            "delta": _tidy(values[-1] - values[0]),
            "min": _tidy(min(values)),
            "max": _tidy(max(values)),
            "avg": _tidy(sum(values) / len(values)),
            "samples": len(values),
        }
    return summary


def _window_tag(window: timedelta) -> str:
    seconds = int(window.total_seconds())
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def trend_block(
    rows: list[dict[str, Any]],
    window: timedelta,
    spark_width: int = 24,
) -> dict[str, Any] | None:
    """Pre-computed panel payload: summary + a short °F sparkline."""
    summary = summarize_history(rows, window)
    if not summary:
        return None
    ordered = _ordered(rows)
    temps = [float(r["temperature_f"]) for r in ordered if _numeric(r, "temperature_f")]
    block: dict[str, Any] = {
        "window": _window_tag(window),
        "window_seconds": summary.get("window_seconds"),
        "samples": summary["samples"],
        "first_time": summary["first_time"],
        "last_time": summary["last_time"],
        "series": summary["series"],
    }
    if temps:
        block["spark_f"] = sparkline(temps, spark_width)
    return block


def current_trend(window: timedelta | None = None, spark_width: int = 24) -> dict[str, Any] | None:
    span = window or timedelta(hours=1)
    return trend_block(read_history(since=span), span, spark_width=spark_width)


def history_payload(
    since_text: str,
    rows: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], int]:
    """JSON body + HTTP status for GET /history?since=… (same object as --since --json)."""
    try:
        window = parse_duration(since_text)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if rows is None:
        rows = read_history(since=window, now=now)
    summary = summarize_history(rows, window)
    if summary is None:
        return {
            "error": f"no readings recorded in the last {window_label(since_text)}",
            "window": window_label(since_text),
        }, 404
    return summary, 200


def _resample(values: list[float], width: int) -> list[float]:
    if len(values) <= width:
        return [float(v) for v in values]
    step = len(values) / width
    out: list[float] = []
    for i in range(width):
        low = int(i * step)
        high = max(low + 1, int((i + 1) * step))
        chunk = values[low:high]
        out.append(sum(chunk) / len(chunk))
    return out


def sparkline(values: list[float], width: int = 48) -> str:
    numbers = [float(v) for v in values]
    if not numbers:
        return ""
    points = _resample(numbers, width)
    low, high = min(points), max(points)
    if high - low < 1e-9:
        return SPARK_CHARS[3] * len(points)
    span = high - low
    top = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[min(top, int((v - low) / span * len(SPARK_CHARS)))] for v in points)


def _num(value: Any) -> str:
    if value is None:
        return "—"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _delta(value: float, unit: str = "") -> str:
    number = float(value)
    if number > 0:
        return f"+{_num(number)}{unit}"
    if number < 0:
        return f"{_num(number)}{unit}"
    return f"±0{unit}"


def _label(text: str) -> str:
    return f"{text:<{LABEL_WIDTH}}"


def _clock(first: datetime, last: datetime) -> str:
    if first.date() == last.date():
        return f"{first:%H:%M} → {last:%H:%M}"
    return f"{first:%b %d %H:%M} → {last:%b %d %H:%M}"


def _series_block(name: str, values: list[float], unit: str, width: int) -> list[str]:
    average = sum(values) / len(values)
    return [
        "",
        f"{_label(name + ':')}{_num(values[0])}{unit} → {_num(values[-1])}{unit}"
        f"  ({_delta(values[-1] - values[0], unit)})",
        f"{INDENT}min {_num(min(values))}{unit}  max {_num(max(values))}{unit}"
        f"  avg {_num(_tidy(average))}{unit}",
        f"{INDENT}{sparkline(values, width)}",
    ]


def format_history(rows: list[dict[str, Any]], label: str = "", width: int = 48) -> str:
    ordered = _ordered(rows)
    if not ordered:
        return ""
    first, last = row_time(ordered[0]), row_time(ordered[-1])
    count = len(ordered)
    head = f"Last {label}" if label else "History"
    noun = "sample" if count == 1 else "samples"
    lines = [f"{head} — {count} {noun}, {_clock(first, last)}"]

    def series(key: str) -> list[float]:
        return [r[key] for r in ordered if _numeric(r, key)]

    if count < 2:
        row = ordered[0]
        lines.append("no earlier reading in this window")
        lines.append("")
        if row.get("temperature_f") is not None or row.get("temperature_c") is not None:
            lines.append(
                f"{_label('Temperature:')}{_num(row.get('temperature_f'))}°F"
                f" / {_num(row.get('temperature_c'))}°C"
            )
        if row.get("humidity") is not None:
            lines.append(f"{_label('Humidity:')}{_num(row['humidity'])}%")
        if row.get("co2") is not None:
            lines.append(f"{_label('CO2:')}{_num(row['co2'])} ppm")
        return "\n".join(lines) + "\n"

    temps_f, temps_c = series("temperature_f"), series("temperature_c")
    if temps_f:
        block = _series_block("Temperature", temps_f, "°F", width)
        if temps_c:
            both = f"{_delta(temps_f[-1] - temps_f[0], '°F')} / {_delta(temps_c[-1] - temps_c[0], '°C')}"
            block[1] = (
                f"{_label('Temperature:')}{_num(temps_f[0])}°F → {_num(temps_f[-1])}°F"
                f"  ({both})"
            )
        lines.extend(block)

    humidity = series("humidity")
    if humidity:
        lines.extend(_series_block("Humidity", humidity, "%", width))

    co2 = series("co2")
    if co2:
        lines.extend(_series_block("CO2", co2, " ppm", width))

    battery = series("battery")
    if battery and battery[-1] != battery[0]:
        lines.append("")
        lines.append(
            f"{_label('Battery:')}{_num(battery[0])}% → {_num(battery[-1])}%"
            f"  ({_delta(battery[-1] - battery[0], '%')})"
        )

    return "\n".join(lines) + "\n"


def history_command(
    since_text: str,
    as_json: bool = False,
    path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> int:
    cfg = config if config is not None else load_config()
    try:
        window = parse_duration(since_text)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    rows = read_history(since=window, path=path)
    if not rows:
        if not cfg.get("history", True):
            print(
                f'history recording is off; set "history": true in {CONFIG_PATH}',
                file=sys.stderr,
            )
        else:
            print(
                f"no readings recorded in the last {window_label(since_text)}"
                " (is room-sensor.service running?)",
                file=sys.stderr,
            )
        return 1
    if as_json:
        json.dump(summarize_history(rows, window), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    sys.stdout.write(format_history(rows, label=window_label(since_text)))
    return 0


class RoomSensor:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.reading: dict[str, Any] | None = read_state()
        self._last_packet_monotonic = 0.0
        self._lock = asyncio.Lock()
        self._history_at = latest_history_time() if config.get("history", True) else None
        self._history_appends = 0

    def consider(self, address: str, rssi: int | None, service_data, manufacturer_data) -> dict[str, Any] | None:
        decoded = decode_advertisement(address, rssi, service_data, manufacturer_data)
        if decoded is None:
            return None
        if not is_target(address, self.config.get("address")):
            return None
        return decoded

    async def update(self, reading: dict[str, Any]) -> None:
        async with self._lock:
            if not str(self.config.get("address") or "").strip():
                self.config["address"] = reading["address"]
                save_config(self.config)
            if not is_target(reading["address"], self.config.get("address")):
                return
            self.reading = reading
            self._last_packet_monotonic = asyncio.get_running_loop().time()
            atomic_write_json(STATE_PATH, with_trend(reading))
            self.record_history(reading)

    def record_history(self, reading: dict[str, Any]) -> bool:
        """Append one sample, no more often than history_interval_seconds."""
        if not self.config.get("history", True):
            return False
        stamp = row_time({"time": reading.get("last_seen")}) or now_local()
        interval = timedelta(
            seconds=int(
                self.config.get(
                    "history_interval_seconds", DEFAULT_CONFIG["history_interval_seconds"]
                )
            )
        )
        if self._history_at is not None:
            gap = stamp - self._history_at
            if timedelta(0) <= gap < interval:
                return False
        append_history(history_row(reading))
        self._history_at = stamp
        self._history_appends += 1
        if self._history_appends >= HISTORY_PRUNE_EVERY:
            self._history_appends = 0
            prune_history(retention_window(self.config))
        return True

    def status_payload(self) -> tuple[dict[str, Any] | None, int]:
        if not self.reading:
            return {"error": "no reading yet"}, 503
        body = format_status_json(
            self.reading,
            stale_seconds=int(self.config["stale_seconds"]),
            trend=current_trend() if self.config.get("history", True) else None,
        )
        return body, 200


def retention_window(config: dict[str, Any]) -> timedelta:
    return timedelta(
        hours=int(
            config.get("history_retention_hours", DEFAULT_CONFIG["history_retention_hours"])
        )
    )


def with_trend(reading: dict[str, Any]) -> dict[str, Any]:
    payload = dict(reading)
    trend = current_trend()
    if trend:
        payload["trend"] = trend
    else:
        payload.pop("trend", None)
    return payload


def write_reader_state(sensor: RoomSensor, state: str) -> None:
    payload = dict(sensor.reading or {})
    payload["reader_state"] = state
    if sensor.reading:
        sensor.reading = payload
    atomic_write_json(STATE_PATH, with_trend(payload) if payload else payload)


async def run_scanner(sensor: RoomSensor, stop: asyncio.Event) -> None:
    restart_after = float(sensor.config["scanner_restart_seconds"])

    def callback(device, adv) -> None:
        try:
            reading = sensor.consider(
                device.address,
                adv.rssi,
                adv.service_data or {},
                adv.manufacturer_data or {},
            )
        except Exception as exc:
            print(f"decode error: {exc}", file=sys.stderr)
            return
        if reading is None:
            return
        asyncio.get_running_loop().create_task(sensor.update(reading))

    while not stop.is_set():
        scanner = BleakScanner(callback)
        try:
            await scanner.start()
            print("scanning for SwitchBot T/H advertisements", flush=True)
            while not stop.is_set():
                await asyncio.sleep(1)
                loop_time = asyncio.get_running_loop().time()
                if sensor._last_packet_monotonic and (loop_time - sensor._last_packet_monotonic) > restart_after:
                    print("no advertisements recently; restarting scanner", flush=True)
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"scanner error: {exc}", file=sys.stderr)
            err = str(exc).lower()
            if "adapter" in err or "bluetooth" in err:
                write_reader_state(sensor, "no_adapter")
        finally:
            try:
                await scanner.stop()
            except Exception:
                pass
        if not stop.is_set():
            await asyncio.sleep(2)


async def run_http(sensor: RoomSensor, stop: asyncio.Event) -> None:
    try:
        from aiohttp import web
    except ImportError:
        print("http enabled but aiohttp is not installed; skipping status server", file=sys.stderr)
        await stop.wait()
        return

    async def status(_request: web.Request) -> web.Response:
        body, code = sensor.status_payload()
        return web.json_response(body, status=code)

    async def history(request: web.Request) -> web.Response:
        since = request.query.get("since", "")
        if not since:
            return web.json_response(
                {"error": "missing since query parameter; try /history?since=1h"},
                status=400,
            )
        body, code = history_payload(since)
        return web.json_response(body, status=code)

    app = web.Application()
    app.router.add_get("/status", status)
    app.router.add_get("/", status)
    app.router.add_get("/history", history)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, sensor.config["listen"], int(sensor.config["port"]))
    await site.start()
    print(f"http://{sensor.config['listen']}:{sensor.config['port']}/status", flush=True)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


async def run_daemon() -> None:
    config = load_config()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(config)
    sensor = RoomSensor(config)
    if config.get("history", True):
        prune_history(retention_window(config))
    if not str(config.get("address") or "").strip() and not sensor.reading:
        write_reader_state(sensor, "unbound")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    tasks = [run_scanner(sensor, stop)]
    if config.get("http"):
        tasks.append(run_http(sensor, stop))
    await asyncio.gather(*tasks)


def print_cli() -> int:
    config = load_config()
    reading = read_state()
    if not reading:
        print("no reading yet (is room-sensor.service running?)", file=sys.stderr)
        return 1
    sys.stdout.write(format_cli(reading, stale_seconds=int(config["stale_seconds"])))
    if is_stale(reading, now_local(), int(config["stale_seconds"])):
        return 2
    return 0


async def scan_once(timeout: float = 20.0) -> int:
    config = load_config()
    sensor = RoomSensor(config)
    got = asyncio.Event()

    def callback(device, adv) -> None:
        reading = sensor.consider(
            device.address,
            adv.rssi,
            adv.service_data or {},
            adv.manufacturer_data or {},
        )
        if reading is None:
            return
        atomic_write_json(STATE_PATH, reading)
        sensor.reading = reading
        got.set()

    scanner = BleakScanner(callback)
    await scanner.start()
    try:
        try:
            await asyncio.wait_for(got.wait(), timeout=timeout)
        except TimeoutError:
            print("no SwitchBot T/H advertisement in time", file=sys.stderr)
            return 1
    finally:
        await scanner.stop()
    sys.stdout.write(format_cli(sensor.reading, stale_seconds=int(config["stale_seconds"])))
    return 0


async def run_discover(timeout: float = 20.0) -> int:
    found: dict[str, dict[str, Any]] = {}

    def callback(device, adv) -> None:
        reading = decode_advertisement(
            device.address,
            adv.rssi,
            adv.service_data or {},
            adv.manufacturer_data or {},
        )
        if reading is None:
            return
        found[reading["address"]] = reading

    scanner = BleakScanner(callback)
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()
    sys.stdout.write(format_discover_table(list(found.values())))
    return 0 if found else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SwitchBot T/H room sensor")
    parser.add_argument("--print", action="store_true", help="print last reading and exit")
    parser.add_argument(
        "--since",
        metavar="DURATION",
        help="summarize recorded history over this window (45s, 90m, 2h, 3d, 1h30m)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable --since output")
    parser.add_argument("--once", action="store_true", help="scan until one reading, then print")
    parser.add_argument("--discover", action="store_true", help="list nearby SwitchBot T/H meters")
    parser.add_argument("--bind", metavar="MAC", help="bind this meter MAC and write config")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    if args.since:
        return history_command(args.since, as_json=args.json)
    if args.print:
        return print_cli()
    if args.bind:
        cfg = bind_address(args.bind)
        print(f"bound {cfg['address']}")
        return 0
    if args.discover:
        return asyncio.run(run_discover(args.timeout))
    if args.once:
        return asyncio.run(scan_once(args.timeout))
    asyncio.run(run_daemon())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
