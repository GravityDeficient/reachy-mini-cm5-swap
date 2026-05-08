# Changelog

## 0.2.0 — 2026-05-07

### Fixed
- **`02-mediaserver-openh264.py`**: encoder fallback was only half the fix.
  `openh264enc` requires `video/x-raw,format=I420` input but `libcamerasrc`
  on Pi outputs `YUY2`. v4l2h264enc on CM4 transparently accepted YUY2 (its
  silicon did the colour conversion); openh264enc does not. Without a
  `videoconvert + capsfilter(I420)` bridge, GStreamer's caps negotiation
  silently failed (`Gst.Element.link()` returns False), the pipeline ran
  with no data flowing to webrtcsink, and the WebRTC Producer never
  registered with the signalling server — symptom: desktop app's camera
  tile spins forever on "connecting".
- The patch now sets a `_cm5_uses_openh264` flag in the encoder selection
  block and conditionally injects `videoconvert + capsfilter(I420)` between
  `queue_webrtc` and the encoder when the openh264enc fallback is in use.
- **End-to-end WebRTC stream now confirmed working** through Pollen desktop
  app on CM5: Producer registers, SDP offer/answer completes, ICE
  candidates exchange, video flows.

## 0.1.0 — 2026-05-06

Initial public release.

### Patches
- **01-uart-fix.sh** — switches `dtoverlay=uart3` to `dtoverlay=uart2-pi5` and
  patches the SDK to use `/dev/ttyAMA2`. Original credit: Travid (Geerling
  issue #800, 2026-04-30).
- **02-mediaserver-openh264.py** — guards `Gst.ElementFactory.make("v4l2h264enc")`
  with a None-check and falls back to `openh264enc`. Handles both Pollen daemon
  1.2.x (`webrtc_daemon.py`) and 1.7.x (`media_server.py`) layouts.

### Scripts
- **cm5-fan-ctl.py** + **cm5-fan-ctl.service** — userspace fan thermostat.
  Bypasses Pollen's broken-on-CM5 dtoverlay and the missing kernel `emc2301`
  driver. Hysteretic bands 42–68 °C.

### Notes
- Camera (IMX708) requires the flex be plugged into the **secondary** CSI
  socket on the Pollen head PCB, not the primary. No software fix; physical
  change only. See `docs/empirical-findings.md`.
- Tested on CM5116064 + Reachy Mini wireless + OS image v0.2.3 + daemon 1.7.1.
- End-to-end WebRTC stream verification through the desktop app is pending
  at the time of this release.
