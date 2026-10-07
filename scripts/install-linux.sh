#!/bin/sh
set -eu

if [ "$(uname -s)" != Linux ]; then
    echo 'This installer requires Linux.' >&2
    exit 1
fi
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run this installer as your regular user, without sudo.' >&2
    exit 1
fi
package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -f "$package_dir/ate" ] &&
    { ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; }; then
    echo 'Python 3.11 or newer, with venv, is required for the wheel archive.' >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
    echo 'A running systemd user session is required for background checks.' >&2
    exit 1
fi

wheel=''
if [ ! -f "$package_dir/ate" ]; then
    wheel=$(find "$package_dir" -maxdepth 1 -name 'ate_cli-*-py3-none-any.whl' -type f -print -quit)
fi
if [ ! -f "$package_dir/ate" ] && [ -z "$wheel" ]; then
    echo 'The Ate executable or Python wheel is missing from this archive.' >&2
    exit 1
fi

app_dir="$HOME/.local/share/ate"
bin_dir="$HOME/.local/bin"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
state_home="${XDG_STATE_HOME:-$HOME/.local/state}"
case "$state_home" in /*) ;; *) state_home="$HOME/.local/state" ;; esac
state_dir="$state_home/ate"
fresh_install=0
if [ ! -e "$app_dir" ]; then fresh_install=1; fi
created_app=0
cleanup() {
    status=$?
    trap - EXIT
    if [ "$status" -ne 0 ] && [ "$fresh_install" -eq 1 ] && [ "$created_app" -eq 1 ]; then
        for name in ate res; do
            link="$bin_dir/$name"
            if [ -L "$link" ] && [ "$(readlink "$link")" = "$app_dir/launcher/$name" ]; then
                rm -- "$link"
            fi
        done
        for name in ate.service ate.timer; do
            unit="$unit_dir/$name"
            if [ -f "$unit" ] && grep -q 'Ate meal reservation\|Check Ate meal reservations' "$unit"; then
                rm -- "$unit"
            fi
        done
        rm -rf -- "$app_dir"
        echo 'Installation did not finish; partial app files were removed.' >&2
    fi
    exit "$status"
}
trap cleanup EXIT

for name in ate res; do
    link="$bin_dir/$name"
    if [ -e "$link" ] || [ -L "$link" ]; then
        expected="$app_dir/launcher/$name"
        if [ ! -L "$link" ] || { [ "$(readlink "$link")" != "$expected" ] &&
            [ "$(readlink "$link")" != "$app_dir/venv/bin/$name" ]; }; then
            echo "$link already belongs to another installation." >&2
            exit 1
        fi
    fi
done
for name in ate.service ate.timer; do
    unit="$unit_dir/$name"
    if [ -f "$unit" ] && ! grep -q 'Ate meal reservation\|Check Ate meal reservations' "$unit"; then
        echo "$unit already belongs to another installation." >&2
        exit 1
    fi
done

umask 077
mkdir -p "$app_dir" "$bin_dir" "$unit_dir" "$state_dir"
created_app=1
mkdir -p "$app_dir/launcher"
if [ -f "$package_dir/ate" ]; then
    cp "$package_dir/ate" "$app_dir/ate"
    chmod 700 "$app_dir/ate"
    app_command="$app_dir/ate"
else
    python3 -m venv "$app_dir/venv"
    "$app_dir/venv/bin/python" -m pip install --upgrade "$wheel"
    app_command="$app_dir/venv/bin/ate"
fi
ln -sfn "$app_command" "$app_dir/launcher/ate"
ln -sfn "$app_command" "$app_dir/launcher/res"

if [ ! -f "$state_dir/profile.bin" ]; then
    "$app_command" auth
fi
if [ ! -f "$state_dir/order.bin" ]; then
    echo 'No standing order was configured. Run ate auth and try again.' >&2
    exit 1
fi
every_minutes=$("$app_command" config --minutes)

printf '%s\n' "$state_dir" > "$app_dir/state-path"
cat > "$app_dir/run-background" <<'EOF'
#!/bin/sh
set -eu
app_dir="$HOME/.local/share/ate"
state_dir=$(cat "$app_dir/state-path")
exec "$app_dir/launcher/ate" background --state-dir "$state_dir"
EOF
chmod 700 "$app_dir/run-background"
cp "$package_dir/uninstall.sh" "$app_dir/uninstall.sh"
chmod 700 "$app_dir/uninstall.sh"
ln -sfn "$app_dir/launcher/ate" "$bin_dir/ate"
ln -sfn "$app_dir/launcher/res" "$bin_dir/res"

cat > "$unit_dir/ate.service" <<'EOF'
[Unit]
Description=Ate meal reservation check

[Service]
Type=oneshot
ExecStart=%h/.local/share/ate/run-background
EOF
cat > "$unit_dir/ate.timer" <<EOF
[Unit]
Description=Check Ate meal reservations while signed in

[Timer]
OnStartupSec=1min
OnUnitInactiveSec=${every_minutes}min
Unit=ate.service

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now ate.timer
systemctl --user start ate.service || echo 'First check did not finish; the timer will retry.' >&2

echo "Ate installed at $app_dir."
echo 'Use res help. Add ~/.local/bin to PATH if res is not found.'
