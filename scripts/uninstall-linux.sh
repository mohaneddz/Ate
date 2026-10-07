#!/bin/sh
set -eu

if [ "$(uname -s)" != Linux ] || [ "$(id -u)" -eq 0 ]; then
    echo 'Run this uninstaller on Linux as your regular user.' >&2
    exit 1
fi
if [ "${1:-}" != '' ] && [ "${1:-}" != '--purge-data' ]; then
    echo 'Usage: ./uninstall.sh [--purge-data]' >&2
    exit 1
fi

app_dir="$HOME/.local/share/ate"
bin_dir="$HOME/.local/bin"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
state_home="${XDG_STATE_HOME:-$HOME/.local/state}"
case "$state_home" in /*) ;; *) state_home="$HOME/.local/state" ;; esac
state_dir="$state_home/ate"
if [ -f "$app_dir/state-path" ]; then
    state_dir=$(cat "$app_dir/state-path")
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now ate.timer 2>/dev/null || true
fi
for name in ate res; do
    link="$bin_dir/$name"
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$app_dir/venv/bin/$name" ]; then
        rm -- "$link"
    fi
done
rm -f -- "$unit_dir/ate.service" "$unit_dir/ate.timer"
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
fi

if [ "$app_dir" != "$HOME/.local/share/ate" ] || [ ! -f "$app_dir/run-background" ]; then
    echo 'The Ate installation folder was not recognized; leaving it in place.' >&2
    exit 1
fi
rm -rf -- "$app_dir"
if [ "${1:-}" = '--purge-data' ]; then
    if [ "$state_dir" = "$state_home/ate" ] && [ -d "$state_dir" ]; then
        rm -rf -- "$state_dir"
    else
        echo 'Custom state folder was left in place; remove it manually if needed.' >&2
    fi
fi
echo 'Ate removed.'
