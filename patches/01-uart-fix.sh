#!/bin/bash
# 01-uart-fix.sh — Reachy Mini CM5 motor UART fix
#
# Original credit: Travid (Geerling issue #800, 2026-04-30)
#
# What it does:
#   1. Replace `dtoverlay=uart3` (CM4 syntax) with `dtoverlay=uart2-pi5` in
#      /boot/firmware/config.txt. CM5/BCM2712 maps the same physical GPIO
#      0+1 pads (which Pollen's PCB traces motor TTL to) to UART2, not UART3
#      as on CM4/BCM2711. With the wrong overlay, /dev/ttyAMA3 still gets
#      created but it's not connected to the motor pins.
#   2. Patch the SDK in /venvs/mini_daemon/.../site-packages/reachy_mini/ to
#      use /dev/ttyAMA2 instead of the hardcoded /dev/ttyAMA3 in three files.
#
# Idempotent — safe to re-run after Pollen daemon updates.
#
# Reboot is REQUIRED for config.txt changes to take effect. SDK changes take
# effect after `systemctl restart reachy-mini-daemon`.

set -euo pipefail

CONFIG_TXT=/boot/firmware/config.txt
SDK=/venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: must run as root (use sudo)" >&2
    exit 1
fi

# --- 1. config.txt ---
if grep -qE "^dtoverlay=uart2-pi5\b" "$CONFIG_TXT"; then
    echo "[skip] config.txt already has uart2-pi5"
elif grep -qE "^dtoverlay=uart3\b" "$CONFIG_TXT"; then
    cp "$CONFIG_TXT" "$CONFIG_TXT.bak-cm5patch.$(date +%s)"
    sed -i 's/^dtoverlay=uart3$/dtoverlay=uart2-pi5/' "$CONFIG_TXT"
    echo "[ok]   config.txt: uart3 -> uart2-pi5 (reboot required)"
else
    echo "[warn] config.txt has neither uart3 nor uart2-pi5; manual review needed:"
    grep -nE "uart" "$CONFIG_TXT" || true
fi

# --- 2. SDK files ---
for f in \
    "$SDK/tools/scan_motors.py" \
    "$SDK/tools/setup_motor_rpi.py" \
    "$SDK/daemon/utils.py"; do
    if [[ ! -f "$f" ]]; then
        echo "[warn] file not found, skipping: $f"
        continue
    fi
    if grep -q "/dev/ttyAMA3" "$f"; then
        sed -i 's|/dev/ttyAMA3|/dev/ttyAMA2|g' "$f"
        echo "[ok]   patched: $f"
    else
        echo "[skip] no ttyAMA3 references in: $f"
    fi
done

echo
echo "UART fix applied. Reboot to take effect:"
echo "    sudo reboot"
