#!/bin/sh
# Install Ate on an always-on Debian or Ubuntu server as a system service.
# Usage (as root): install-server.sh path/to/ate_cli-VERSION-py3-none-any.whl
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this installer as root.' >&2
    exit 1
fi
wheel=${1:?Usage: install-server.sh path/to/ate_cli-VERSION-py3-none-any.whl}
if [ ! -f "$wheel" ]; then
    echo "Wheel not found: $wheel" >&2
    exit 1
fi
if ! python3 -c 'import sys, venv; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
    echo 'Python 3.11 or newer with the venv module is required (apt install python3-venv).' >&2
    exit 1
fi

state_home=/var/lib/ate/state
id ate >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/ate --shell /usr/sbin/nologin ate
install -d -o ate -g ate -m 700 /var/lib/ate "$state_home"

python3 -m venv /opt/ate
/opt/ate/bin/pip install --quiet --upgrade --force-reinstall "$wheel"

# 'ate' and 'res' run as the service user so 'ate auth' over SSH edits the service's own state.
for name in ate res; do
    cat > "/usr/local/bin/$name" <<EOF
#!/bin/sh
exec runuser -u ate -- env XDG_STATE_HOME=$state_home /opt/ate/bin/ate "\$@"
EOF
    chmod 755 "/usr/local/bin/$name"
done

cat > /etc/systemd/system/ate.service <<EOF
[Unit]
Description=Ate meal reservations and Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=ate
Environment=XDG_STATE_HOME=$state_home
ExecStart=/opt/ate/bin/ate serve
Restart=always
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/ate

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable ate.service >/dev/null 2>&1

if [ -f "$state_home/ate/profile.bin" ]; then
    systemctl restart ate.service
    echo 'Ate updated and restarted.'
else
    echo 'Ate installed. Next: run "ate auth", then "ate telegram", then "systemctl start ate".'
fi
