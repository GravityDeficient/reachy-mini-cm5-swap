# reachy-mini-cm5-swap

Patches and notes for upgrading a Pollen Robotics **Reachy Mini (wireless)** from
the stock Compute Module 4 to a Compute Module 5.

> **Status:** working at the hardware/driver/libcamera level on a CM5116064 (16GB
> RAM / 64GB eMMC) with Reachy Mini OS v0.2.3 + Pollen daemon 1.7.1. The stock
> IMX708 camera streams frames via `rpicam-still`. End-to-end verification
> through Pollen's desktop-app WebRTC pipeline is **not yet confirmed**; see
> [Verification status](#verification-status) below.

## Why this exists

Reachy Mini ships with a CM4. Some owners want to upgrade to CM5 for the extra
CPU, RAM, and especially headroom for local AI workloads. The community started
this work in [Geerling issue #800](https://github.com/geerlingguy/raspberry-pi-pcie-devices/issues/800),
where user `Travid` documented the procedure on 2026-04-30 and got the OS to
boot and motors to work — but explicitly noted the camera was "still working
on it" and never published a follow-up. Nobody else has either.

This repo closes the gap with four CM5-specific fixes plus the empirical
finding that resolves the camera issue.

## TL;DR for someone with a CM5 in hand

1. Flash the stock Reachy Mini OS image to the CM5 eMMC via
   `rpiboot` + `bmaptool` (see [docs/procedure.md](docs/procedure.md)).
2. **Plug the camera CSI flex into the *secondary* CSI socket** on the head
   PCB, not the primary one. The two sockets have different trace topologies
   on Pollen's carrier; only the secondary works on CM5.
3. Run `./reapply.sh` to apply the four CM5 patches.
4. Reboot. Done.

## What's wrong on stock CM5

| # | Subsystem | Root cause | Fix in this repo |
|---|---|---|---|
| 1 | **Motor UART** | Pollen's stock `dtoverlay=uart3` references a CM4 IP block that maps to different CM5 pads; the SDK hardcodes `/dev/ttyAMA3` which on CM5 with CM4-style overlay points at the wrong physical pins. | [`patches/01-uart-fix.sh`](patches/01-uart-fix.sh) — switch overlay to `uart2-pi5` and patch SDK to use `/dev/ttyAMA2`. Original Travid's fix; included for completeness. |
| 2 | **Camera (IMX708) CSI** | The primary CSI socket on Pollen's head PCB has trace routing that doesn't carry CSI data lanes correctly to BCM2712. i2c works (chip ID readable) but `Camera frontend has timed out!` — no pixel data. | **Hardware fix only**: physically move camera flex to the *secondary* CSI socket. No software patch needed. See [docs/empirical-findings.md](docs/empirical-findings.md). |
| 3 | **Fan controller (EMC2301)** | Pollen's dtoverlay declares the chip on i2c-0 but on CM5 it's physically wired to i2c-10. Compounding: the `+rpt-rpi-2712` kernel build doesn't ship an `emc2301` driver. With no host control, EMC2301 runs at 100% PWM as failsafe. | [`scripts/cm5-fan-ctl.py`](scripts/cm5-fan-ctl.py) + [`scripts/cm5-fan-ctl.service`](scripts/cm5-fan-ctl.service) — userspace thermostat that writes the EMC2301 directly via `/dev/i2c-10`. Hysteretic bands 42–68 °C. |
| 4 | **WebRTC media pipeline** | Two compounding bugs: (a) `media_server.py` calls `Gst.ElementFactory.make("v4l2h264enc")` then immediately calls `.set_property()` *before* the None-check, raising `AttributeError` because BCM2712 dropped the legacy V4L2 hardware H.264 encoder; (b) `openh264enc` (the software encoder we fall back to) requires `video/x-raw,format=I420` input while `libcamerasrc` outputs `YUY2`, so the pipeline link silently fails to negotiate caps and no frames flow to webrtcsink. Affects both Pollen daemon 1.2.x (`webrtc_daemon.py`) and 1.7.x (`media_server.py`). | [`patches/02-mediaserver-openh264.py`](patches/02-mediaserver-openh264.py) — None-guarded fallback to `openh264enc` AND conditionally injects `videoconvert` + `capsfilter(I420)` before the encoder. CM5's 4× A76 cores at 2.4 GHz comfortably encode 1296×972 @ 30 fps at 5 Mbps in software. |

## Verification status

Tested on:
- Compute Module 5 (`CM5116064`: 16 GB LPDDR4X, 64 GB eMMC, wireless)
- Pollen Reachy Mini wireless variant
- Reachy Mini OS image v0.2.3 (2026-01-14)
- Kernel `6.12.62+rpt-rpi-2712`
- Pollen daemon `1.7.1`

| What | Verified? |
|---|---|
| OS boots cleanly on CM5 | ✅ |
| WiFi associates, SSH works | ✅ |
| `vcgencmd get_throttled = 0x0` under motor + WiFi load | ✅ |
| Motors enumerate via Dynamixel Protocol 2.0 (broadcast PING returns 5+ XL-330s) | ✅ |
| Pollen daemon reaches `state: "running"`, motors initialized with PID gains | ✅ |
| Fan controller stopgap holds CPU at idle without thermal events | ✅ |
| **Camera captures via `rpicam-still`** (1296×972 JPEG, valid EXIF, sharp colors) | ✅ |
| **Camera streams end-to-end through desktop-app WebRTC pipeline** | ✅ |
| Microphone audio captures end-to-end | ✅ (conversation app responds to voice) |

End-to-end WebRTC video + audio confirmed working with Pollen's desktop app
talking to a CM5 robot running the bundled `reachy_mini_conversation_app`.
Producer registers with the signalling server, SDP offer/answer completes,
ICE candidates exchange, and video flows. Reports from other hardware
configurations welcome.

## What's NOT addressed here

- **Pi AI Camera (IMX500) swap** — an alternative camera path discussed in the
  research notes but not used here, since the stock IMX708 works on the
  secondary CSI socket. If you don't have a working IMX708, IMX500 is a viable
  capability upgrade with a 3D-printed mount; not in scope for this repo.
- **IMU on CM5** — the stock dtoverlay points at `/dev/i2c-4` which doesn't
  enumerate on this kernel build (warning at daemon startup). Not blocking
  anything tested so far. Likely the same wrong-bus pattern as the fan
  controller and a similar fix; not yet diagnosed.
- **mDNS service discovery from desktop app** — `/etc/avahi/services/` is
  empty in the stock Pollen image, so the desktop app can't auto-discover
  the robot. Connecting via direct IP works. Cosmetic, not blocking.

## Durability

All four fixes touch files inside `/venvs/mini_daemon/lib/python3.12/site-packages/`,
which Pollen's daemon auto-update will overwrite. Run `./reapply.sh` after
any daemon update until upstream lands these fixes.

## Acknowledgments

- **Travid** — opened the trail in [Geerling #800](https://github.com/geerlingguy/raspberry-pi-pcie-devices/issues/800)
  and documented the UART fix.
- **darkseed** — mentioned "the unused CSI port in the head" in the same thread,
  which was the lead that ultimately solved the camera issue.
- **Jeff Geerling** — for hosting the broader CM5/Pi-PCIe ecosystem
  conversation.
