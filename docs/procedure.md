# CM4 → CM5 swap procedure

A condensed reference for the hardware swap. Read this in conjunction with
the [parent README](../README.md) and the [empirical findings](empirical-findings.md).

## Prerequisites

- A Compute Module 5 (any RAM/eMMC/wireless config; `CM5116064` was tested).
- A USB cable that fits the head PCB's "USB2" port (USB-C on most variants)
  and the host computer that will run `rpiboot`.
- A host computer with Linux + Python 3 + ability to install `bmap-tools` and
  build `usbboot` from source. A Raspberry Pi 4 / 5 works fine. ~10 GB of
  free disk for the OS image and the CM4 backup.
- Phillips #00 driver, anti-static surface, and ~1 hour.

## Phase 0 — backup the CM4 (optional but strongly recommended)

Lets you roll back if anything goes wrong. The image is for a CM4; do *not*
restore it onto a CM5 (different SoC, different bootloader).

```bash
# On the host, NOT on the robot
ssh pollen@<robot-ip> "sudo dd if=/dev/mmcblk0 bs=4M status=progress" \
    | gzip > ~/cm4-emmc-$(date +%Y-%m-%d).img.gz
```

Streaming over SSH avoids tmpfs traps. The result will be ~3 GB compressed
for a stock 16 GB eMMC.

## Phase 1 — mechanical swap

1. Power off the robot. Unplug the battery if equipped.
2. Open the case. Disconnect, in this order: motor TTL → mic-array USB →
   speaker → camera CSI flex (flip the latch up first, then pull). Photograph
   anything you might forget.
3. Unscrew the CM4 retention screws. Lift the CM4 evenly from the 100-pin
   socket — both ends together, no rocking.
4. Seat the CM5 in the same socket, same orientation. Press straight down on
   both ends until both click. Do not rock.
5. Screw retention back, **but** leave the camera CSI flex disconnected for
   now (we'll plug it into the secondary socket in Phase 4).
6. Reconnect motor TTL, mic-array USB, speaker.

## Phase 2 — flash Reachy Mini OS to the CM5 eMMC

The CM5 ships with empty eMMC. Use the official Pollen reflash procedure:

1. Find the `SW1` switch on the head PCB. Set it to **DOWNLOAD**.
2. Connect a USB cable from the head PCB's "USB2" port to your host.
3. Power on the robot. (Fan will spin; nothing else happens — CM5 is in
   download mode waiting for `rpiboot`.)

On the host:

```bash
# Build rpiboot (one-time)
sudo apt install -y bmap-tools git build-essential libusb-1.0-0-dev pkg-config
git clone https://github.com/raspberrypi/usbboot.git
cd usbboot && make

# Push the mass-storage-gadget firmware. CM5 eMMC enumerates as /dev/sda
sudo ./rpiboot -d mass-storage-gadget64

# Verify (should show ~58 GiB USB block device named "Raspberry Pi multi-function USB device")
lsblk

# Download Reachy Mini OS (use latest release from pollen-robotics/reachy-mini-os)
mkdir -p ~/reachy-mini-os && cd ~/reachy-mini-os
gh release download v0.2.3 --repo pollen-robotics/reachy-mini-os \
    --pattern '*.zip' --pattern '*.bmap'

# Flash
sudo bmaptool copy --bmap 2026-01-14-reachyminios-v0.2.3.bmap \
    image_2026-01-14-reachyminios-v0.2.3.zip /dev/sda

# Sync + eject
sync && sudo eject /dev/sda
```

Expect ~3–5 minutes for the flash. A `funzip error: invalid compressed data`
warning at the end is benign (bmaptool closes the zip stream after the last
mapped block; verify with `gzip -t` and `fsck.ext4 -nf` if paranoid).

## Phase 3 — first boot + first-time setup

1. Power off the robot.
2. Unplug the flashing USB cable.
3. Set `SW1` back to **DEBUG**.
4. Power on normally. First boot takes ~2–3 minutes (resize2fs runs, EEPROM
   may auto-update, SSH host keys generate).
5. Use the Pollen Reachy Mini desktop app's first-time-setup flow to provide
   WiFi credentials over Bluetooth. After this, the robot will be on your
   LAN.
6. SSH in (default credentials: `pollen` / `root`):
   ```bash
   ssh-copy-id pollen@reachy-mini.local
   # then change the password
   ssh pollen@reachy-mini.local "passwd"
   ```

## Phase 4 — connect the camera to the SECONDARY CSI socket

This is the empirical fix at the heart of this repo. The two CSI sockets
on Pollen's head PCB have different trace topologies; only the secondary
works on CM5. Plug the camera CSI flex into the **secondary** socket — the
one you weren't using before. No software config change needed (Pollen's
overlay declares both `cam0` and `cam1` so either works at the kernel
level; only one has a physically connected camera).

## Phase 5 — apply CM5 patches

```bash
# On your dev machine, push this repo to the robot
scp -r /path/to/reachy-mini-cm5-swap pollen@reachy-mini.local:~/

# Run the reapply script
ssh pollen@reachy-mini.local "cd ~/reachy-mini-cm5-swap && ./reapply.sh"
```

The script applies:
1. UART overlay + SDK ttyAMA path
2. Media server openh264enc fallback
3. Fan controller stopgap (script + systemd unit)

Reboot to pick up the UART overlay change:
```bash
ssh pollen@reachy-mini.local "sudo reboot"
```

## Phase 6 — verify

```bash
ssh pollen@reachy-mini.local

# 1. Power health (should be 0x0)
vcgencmd get_throttled

# 2. UART + motors
ls -la /dev/ttyAMA*  # should show ttyAMA2
sudo journalctl -u reachy-mini-daemon -b 0 | grep "Setting PID gains"
# should see all 6 stewart motors + 2 antennas

# 3. Camera (stop daemon temporarily so libcamera is free)
sudo systemctl stop reachy-mini-daemon
systemctl --user stop pipewire wireplumber pipewire-pulse  # release if grabbed
rpicam-still -n -t 1500 -o /tmp/test.jpg --width 1296 --height 972
# should produce a real JPEG; if "Camera frontend has timed out!" you're
# on the WRONG CSI socket — power off, swap to the other socket
sudo systemctl start reachy-mini-daemon
systemctl --user start pipewire pipewire-pulse wireplumber

# 4. Fan controller
sudo i2cget -y 10 0x2f 0x30
# should return 0x00 at idle (or whatever band the thermostat picked)
sudo systemctl status cm5-fan-ctl

# 5. Daemon WebRTC init (no longer fails)
sudo journalctl -u reachy-mini-daemon -b 0 | grep -iE "webrtc|media|error"
# should NOT contain "'NoneType' object has no attribute 'set_property'"

# 6. Daemon overall
curl -s http://localhost:8000/api/daemon/status
# state should be "running", error should be null
```

## Phase 7 — durability after Pollen daemon updates

Pollen's daemon auto-updates will overwrite the in-venv files (UART sed and
media_server.py patch). The `reapply.sh` script is idempotent; just re-run
it after each daemon update until upstream fixes land.

A more durable solution is a systemd oneshot that re-applies the patches at
boot. Not yet implemented in this repo; PRs welcome.
