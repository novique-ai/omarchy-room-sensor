#!/usr/bin/env bash
set -euo pipefail

plugin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/room-sensor"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/room-sensor"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/room-sensor"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
bin_dir="$HOME/.local/bin"
venv_dir="$data_dir/.venv"
python_bin="$venv_dir/bin/python"
unit_path="$unit_dir/room-sensor.service"
bindir_link="$bin_dir/room-temp"
config_file="$config_dir/config.json"

usage() {
  printf 'Usage: %s [--uninstall] [--purge] [--non-interactive] [--timeout N]\n' "$(basename "$0")"
}

uninstall=false
purge=false
non_interactive=false
timeout=20

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall) uninstall=true; shift ;;
    --purge) purge=true; shift ;;
    --non-interactive) non_interactive=true; shift ;;
    --timeout) timeout="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if $purge && ! $uninstall; then
  printf '%s\n' '--purge requires --uninstall' >&2
  exit 2
fi

if $uninstall; then
  systemctl --user disable --now room-sensor.service 2>/dev/null || true
  rm -f "$unit_path" "$bindir_link"
  systemctl --user daemon-reload 2>/dev/null || true
  if $purge; then
    rm -rf "$data_dir" "$config_dir" "$state_dir"
  fi
  printf '%s\n' 'room-sensor stopped.'
  exit 0
fi

if ! command -v python3 >/dev/null; then
  printf '%s\n' 'python3 is required.' >&2
  exit 1
fi
if [[ ! -d /sys/class/bluetooth ]]; then
  printf '%s\n' 'No Bluetooth adapter found under /sys/class/bluetooth.' >&2
  exit 1
fi

mkdir -p "$data_dir" "$config_dir" "$state_dir" "$unit_dir" "$bin_dir"
cp "$plugin_dir/sensor/room_sensor.py" "$data_dir/room_sensor.py"
cp "$plugin_dir/sensor/requirements.txt" "$data_dir/requirements.txt"
cp "$plugin_dir/sensor/room-sensor.service" "$unit_path"

if [[ ! -x $python_bin ]]; then
  python3 -m venv "$venv_dir"
fi
"$python_bin" -m pip install -q -r "$data_dir/requirements.txt"

cat > "$bindir_link" <<EOF
#!/usr/bin/env bash
if [[ \$# -eq 0 ]]; then
  exec "$python_bin" "$data_dir/room_sensor.py" --print
fi
exec "$python_bin" "$data_dir/room_sensor.py" "\$@"
EOF
chmod +x "$bindir_link"

have_mac=false
if [[ -f $config_file ]] && grep -qE '"address": *"[A-Fa-f0-9:]{17}"' "$config_file"; then
  have_mac=true
fi

if ! $have_mac && [[ -t 0 ]] && ! $non_interactive; then
  printf '%s\n' "Scanning ${timeout}s for SwitchBot T/H meters…"
  "$python_bin" "$data_dir/room_sensor.py" --discover --timeout "$timeout" || true
  printf '%s' 'MAC to bind (blank = first meter seen): '
  read -r mac
  if [[ -n ${mac:-} ]]; then
    "$python_bin" "$data_dir/room_sensor.py" --bind "$mac"
  fi
fi

systemctl --user daemon-reload
systemctl --user enable --now room-sensor.service
printf '%s\n' "room-sensor.service is running. CLI: room-temp"
