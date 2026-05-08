#!/bin/bash
# reapply.sh — apply (or reapply) all CM5 patches.
#
# Run this:
#   - First time, after flashing Reachy Mini OS to the CM5
#   - Every time after Pollen's daemon auto-update overwrites the in-venv files
#
# Run as the `pollen` user on the robot. The script uses sudo internally.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "============================================================"
echo "  Reachy Mini CM5 patches — reapply.sh"
echo "============================================================"
echo

# --- 1. UART fix ---
echo "[1/3] UART (motors)"
sudo bash patches/01-uart-fix.sh
echo

# --- 2. Media server / WebRTC encoder ---
echo "[2/3] Media server (WebRTC H.264 encoder)"
sudo python3 patches/02-mediaserver-openh264.py
echo

# --- 3. Fan controller ---
echo "[3/3] Fan controller (EMC2301 stopgap)"
SCRIPT_DST=/usr/local/sbin/cm5-fan-ctl.py
UNIT_DST=/etc/systemd/system/cm5-fan-ctl.service

if ! cmp -s scripts/cm5-fan-ctl.py "$SCRIPT_DST" 2>/dev/null; then
    sudo install -m 0755 scripts/cm5-fan-ctl.py "$SCRIPT_DST"
    echo "[ok]   installed: $SCRIPT_DST"
else
    echo "[skip] already current: $SCRIPT_DST"
fi

if ! cmp -s scripts/cm5-fan-ctl.service "$UNIT_DST" 2>/dev/null; then
    sudo install -m 0644 scripts/cm5-fan-ctl.service "$UNIT_DST"
    sudo systemctl daemon-reload
    echo "[ok]   installed: $UNIT_DST"
else
    echo "[skip] already current: $UNIT_DST"
fi

if ! systemctl is-enabled cm5-fan-ctl.service >/dev/null 2>&1; then
    sudo systemctl enable cm5-fan-ctl.service
    echo "[ok]   enabled cm5-fan-ctl.service"
fi

if ! systemctl is-active cm5-fan-ctl.service >/dev/null 2>&1; then
    sudo systemctl start cm5-fan-ctl.service
    echo "[ok]   started cm5-fan-ctl.service"
else
    sudo systemctl restart cm5-fan-ctl.service
    echo "[ok]   restarted cm5-fan-ctl.service"
fi

echo
echo "============================================================"
echo "  All patches applied."
echo
echo "  Next steps:"
echo "    1. If config.txt was changed (uart3 -> uart2-pi5),"
echo "       reboot now:        sudo reboot"
echo "    2. Otherwise, restart the daemon:"
echo "                          sudo systemctl restart reachy-mini-daemon"
echo "    3. Verify motors:    /api/daemon/status -> backend_status.ready"
echo "    4. Verify camera:    rpicam-still -n -t 1500 -o /tmp/test.jpg"
echo "                          (camera flex must be in the SECONDARY CSI"
echo "                           socket on the head PCB — not the primary)"
echo "============================================================"
