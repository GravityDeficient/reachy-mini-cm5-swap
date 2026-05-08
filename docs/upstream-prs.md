# Upstream PRs (drafts)

The right long-term home for these fixes is `pollen-robotics/reachy_mini`
(and possibly `pollen-robotics/reachy-mini-os` for the dtoverlays). This
file tracks intent and draft messages.

## PR 1 — `media_server.py`: guard `v4l2h264enc` and fall back to `openh264enc`

**Repo:** `pollen-robotics/reachy_mini`
**File:** `reachy_mini/media/media_server.py`

### Status
Not yet submitted.

### Problem
Pi 5 / CM5 (BCM2712) dropped the legacy V4L2 hardware H.264 encoder.
`Gst.ElementFactory.make("v4l2h264enc")` returns `None` on CM5. The current
code calls `.set_property()` on the result before the `if not all([...])`
None-check runs, raising `AttributeError` and killing media server init.

### Proposed fix
None-guard around `v4l2h264enc` configuration. Fall back to `openh264enc`
software encoder (already provided by `gstreamer1.0-plugins-bad`) on hosts
where `v4l2h264enc` is absent. CPU cost on CM5: ~10–15% of one A76 core at
1296×972 / 30 fps / 5 Mbps.

See [`patches/02-mediaserver-openh264.py`](../patches/02-mediaserver-openh264.py)
for the patch shape.

### PR description draft

> ## Make Reachy Mini's media server work on Compute Module 5
>
> Pi 5 / CM5 (BCM2712) dropped the legacy V4L2 hardware H.264 encoder
> (`v4l2h264enc`). On a CM5-based Reachy Mini, `media_server.py` currently
> crashes media server initialization with:
>
> ```
> ERROR: Failed to initialize media server: 'NoneType' object has no
> attribute 'set_property'
> ```
>
> The crash is in the RPi H.264 encoder branch: `make("v4l2h264enc")` returns
> `None`, and `.set_property()` is called before the existing
> `if not all([...])` guard.
>
> This PR:
> - Adds a None-guard around the `v4l2h264enc` setup
> - Falls back to `openh264enc` (software H.264 encoder, available in
>   `gstreamer1.0-plugins-bad`, already installed in the Reachy Mini OS image)
> - Tested on `CM5116064` + Reachy Mini wireless + OS image v0.2.3.
>   Daemon now reaches `state: "running"` instead of `state: "error"`.
> - CPU cost of software encoding at 1296×972 / 30 fps / 5 Mbps is ~10–15%
>   of one A76 core — well within budget for the CM5's 4× A76 @ 2.4 GHz.

---

## PR 2 — config.txt: CM5-conditional UART overlay

**Repo:** `pollen-robotics/reachy-mini-os`
**File:** `stage1/00-boot-files/files/config.txt`

### Status
Not yet submitted.

### Problem
Pollen's stock `config.txt` declares `dtoverlay=uart3` in the `[all]` block.
On CM4 (BCM2711) this maps to GPIO 0+1 (Pollen's motor TTL traces). On CM5
(BCM2712), the `uart2-pi5` overlay maps to the same physical pins instead.

Original credit: Travid (Geerling issue #800).

### Proposed fix
Move the UART overlay out of `[all]` and into per-SoC conditionals:

```
[cm4]
dtoverlay=uart3
enable_uart=1
otg_mode=1

[cm5]
dtoverlay=uart2-pi5
enable_uart=1
dtoverlay=dwc2,dr_mode=host

[all]
# ... rest unchanged ...
```

The SDK's hardcoded `/dev/ttyAMA3` would also need a runtime detection step
(read `/proc/device-tree/model` and pick the right device), or the SDK could
walk both possibilities and use whichever opens.

---

## PR 3 — `i2c-fan` overlay: declare correct i2c bus on CM5

**Repo:** likely `pollen-robotics/reachy-mini-os` (or wherever the fan
overlay lives — may be a Pollen custom overlay shipped in the OS image)

### Status
Not yet submitted. Needs root-cause confirmation from Pollen on which bus
they intended.

### Problem
The fan controller (EMC2301 single-channel PWM) is physically wired to
i2c-10 0x2f on the head PCB, but Pollen's stock dtoverlay declares it on
i2c-0. The kernel never finds the chip on the declared bus, no driver
binds, EMC2301 defaults to 100% PWM as failsafe.

### Compounding
The Pi kernel `+rpt-rpi-2712` build does not include an `emc2301` hwmon
driver (only `emc2305`, which doesn't bind to `smsc,emc2301`). Even with
the right bus declaration, the chip would still be unmanaged on this
kernel.

This is two PRs:
1. (To Pollen) Fix the dtoverlay bus declaration.
2. (To upstream Pi kernel) Add `emc2301` to the hwmon module set in the
   `+rpt-rpi-2712` kernel build, OR teach `emc2305` to bind to
   `smsc,emc2301` compatibles.

The `cm5-fan-ctl.py` script in this repo is a userspace stopgap until both
of those land.

---

## PR 4 (optional) — IMX708 dtoverlay update

### Status
Empirically resolved by physically using the secondary CSI socket on the
head PCB. No software fix is needed; the existing dtoverlay declarations
work as-is once the camera is on the right port.

The publishable finding here is the **socket choice**, which doesn't go in
a PR — it goes in Pollen's documentation and/or assembly instructions.
Could be filed as a documentation PR or a GitHub Discussion entry.

A Discussion-style writeup might say:

> If you've upgraded to CM5 and your camera's CSI streaming times out
> (`Camera frontend has timed out!` from libcamera), try plugging the
> camera CSI flex into the *secondary* CSI socket on the head PCB instead
> of the primary. The two sockets have different trace topologies; on CM5,
> only the secondary one carries the CSI data lanes correctly to the SoC.
> No software config changes needed — the existing `dtoverlay=imx708,cam0`
> and `dtoverlay=imx708,cam1` lines cover both ports.
