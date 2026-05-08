# Empirical findings — CM5 on Pollen Reachy Mini

These are the diagnostic observations behind each patch in the parent README,
preserved for anyone validating on different hardware or pursuing upstream PRs.

Tested on:
- Compute Module 5 `CM5116064` (16 GB LPDDR4X, 64 GB eMMC, wireless)
- Pollen Reachy Mini wireless variant
- Reachy Mini OS image v0.2.3 (build date 2026-01-14)
- Kernel `6.12.62+rpt-rpi-2712`
- Pollen daemon `1.7.1` (and earlier `1.2.11` — see version notes)

---

## 1. UART (motors)

### Symptom
Motors do not respond. SDK on stock CM5 hits a generic
`No serial port found. Please check your USB connection and permissions.`

### Diagnosis
- The Pollen stock `config.txt` ships `dtoverlay=uart3`. On CM4 (BCM2711),
  the `uart3` overlay maps internal UART3 to GPIO 0+1 (Pollen's PCB traces
  motor TTL there).
- On CM5 (BCM2712), the same internal UART numbering exists but the
  alternate-function map for GPIO 0+1 routes those pads to UART2, not UART3.
- The kernel still creates `/dev/ttyAMA3` from the overlay, but it's not
  connected to GPIO 0+1.
- The SDK's `find_serial_port()` for the wireless variant hard-codes
  `pi_uart="/dev/ttyAMA3"`.

### Verification of fix
After `dtoverlay=uart2-pi5` + SDK sed to `/dev/ttyAMA2`:

```
$ ls -la /sys/class/tty/ttyAMA2
lrwxrwxrwx 1 root root 0 May  6 03:24 /sys/class/tty/ttyAMA2 ->
  ../../devices/platform/axi/1000120000.pcie/1f00038000.serial/...

$ python3 -c "
import serial, time
s = serial.Serial('/dev/ttyAMA2', 1000000, timeout=0.2)
s.write(b'\xff\xff\xfd\x00\xfe\x03\x00\x01\x31\x42')  # Dynamixel broadcast PING
time.sleep(0.1); print(s.read(64).hex())
"
fffffd000a07005580b00435b264   # motor ID 10, model 0x0480 (XL-330)
fffffd000b07005580b00435b474   # motor ID 11
fffffd000c07005580b00435a604   # motor ID 12
fffffd000d07005580b00435a014   # motor ID 13
fffffd000e070055...            # motor ID 14
```

Five+ XL-330 motor responses. PCIe address `1f00038000.serial` is the
BCM2712 UART2 IP block.

---

## 2. Camera (IMX708) CSI socket

### Symptom
i2c control plane works (kernel reads chip ID = 0x0302):
```
[ 6.293172] imx708 0-001a: camera module ID 0x0302
[ 6.294017] rp1-cfe 1f00128000.csi: Using sensor imx708_wide for capture
```
But streaming fails with no pixel data:
```
$ rpicam-still -n -t 1500 -o /tmp/test.jpg --width 1296 --height 972
WARN V4L2 v4l2_videodevice.cpp:2100 /dev/video4[14:cap]:
  Dequeue timer of 1000000.00us has expired!
ERROR RPI pipeline_base.cpp:1350 Camera frontend has timed out!
ERROR RPI pipeline_base.cpp:1351 Please check that your camera sensor
  connector is attached securely.
```
Retries indefinitely. CSI controller configures at 900 Mbps link rate, but
no frame ever arrives.

### What did NOT fix it
- Cable reseat at both ends (multiple times, both flex orientations checked)
- `link-frequency=447000000` override
- Removing one of the two `dtoverlay=imx708,...,cam0/cam1` lines (either
  direction)

### What DID fix it
**Physically moving the camera CSI flex from the primary CSI socket on the
Pollen head PCB to the secondary CSI socket.** After move:
```
[ 6.151076] imx708 10-001a: camera module ID 0x0302
[ 6.152082] rp1-cfe 1f00110000.csi: Using sensor imx708_wide for capture

$ rpicam-still -n -t 1500 -o /tmp/test.jpg --width 1296 --height 972
Still capture image received
$ file /tmp/test.jpg
JPEG image data, Exif standard ..., 1296x972, components 3
```

A real 315 KB JPEG, valid EXIF, sharp colors.

### Root cause hypothesis
The two CSI sockets on Pollen's head PCB have different trace topologies, not
mirror-image. The secondary socket happens to use BCM2712 alternate-function
pads compatible with what IMX708 needs (MCLK source GPIO, CSI lane mapping).
The primary socket uses a layout that worked on CM4 (BCM2711) but doesn't on
CM5 — most likely the master clock (MCLK) from the SoC isn't reaching the
sensor on the primary path because the pin's alternate function moved between
BCM2711 and BCM2712.

This hypothesis explains everything observed:
- i2c works on both ports because i2c is a separate, low-speed signal path
  on different pins
- CSI lane configuration succeeds (kernel-side state machine doesn't depend
  on sensor MCLK)
- Sensor never produces frames because its internal PLL has no master clock
- Cable reseat doesn't help because the trace itself isn't the problem

Confirming the hypothesis would require either Pollen's PCB schematic or
oscilloscope probing of the camera flex on both sockets. We have neither;
the empirical workaround is sufficient.

### Pollen overlay-name reversal
On the test hardware, with the camera in the **primary** CSI socket, the
chip answers via the `cam1` overlay (i2c@70000, kernel bus 0). With the
camera in the **secondary** socket, it answers via the `cam0` overlay
(i2c@88000, kernel bus 10). Counterintuitive. If you ever decide to drop
one overlay entry to silence the spurious i2c probe failure on the unused
port, the right answer depends on which physical socket has the camera —
not on the overlay name.

---

## 3. Fan controller (EMC2301)

### Symptom
Fan runs at 100% PWM continuously regardless of CPU temp. CPU idle at 33 °C.

### Diagnosis
- Pollen's stock `config.txt`: `dtoverlay=i2c-fan,emc2301,i2c_csi_dsi,midtemp=45000,maxtemp=65000`.
- This declares an EMC2301 device on i2c-0 in the kernel device tree.
- `ls /sys/bus/i2c/devices/` shows `0-002f` exists (the declared device entry),
  but `i2cdetect -y 0` shows no chip responding at 0x2f.
- `i2cdetect -y 10` shows the chip at 0x2f. The chip is physically wired
  to i2c-10, not i2c-0.
- `modprobe emc2301` returns `Module emc2301 not found`. The CM5 kernel
  build (`6.12.62+rpt-rpi-2712`) does not include an emc2301 hwmon driver.
  It does include `emc2305` (5-channel), but that driver doesn't bind to
  the `smsc,emc2301` compatible string.
- With no driver bound and no host writes, EMC2301 powers up at register
  0x30 = 0xFF (100% duty cycle) — its hardware failsafe behavior.

### Verification of fix
Manual write to register 0x30 on i2c-10 0x2f changes fan speed:
```
$ sudo i2cget -y 10 0x2f 0x30
0xff                            # before any write — failsafe state

$ sudo i2cset -y 10 0x2f 0x30 0x40
$ sudo i2cget -y 10 0x2f 0x30
0x40                            # 25% duty — fan goes silent at idle
```

Userspace stopgap (`cm5-fan-ctl.py` in this repo) polls `/sys/class/thermal/
thermal_zone0/temp` every 5 s and writes register 0x30 directly via
`/dev/i2c-10`. Hysteretic bands prevent oscillation at band boundaries.

### Long-term fix paths
- Pollen ships a CM5-conditional dtoverlay declaring i2c-10 (and contributes
  upstream)
- Pi kernel ships an emc2301 hwmon driver

Either of those would obviate this script.

---

## 4. WebRTC media pipeline

### Symptom
Daemon log:
```
ERROR:reachy_mini.daemon.daemon:Failed to initialize media server:
  'NoneType' object has no attribute 'set_property'
```
Or in older Pollen 1.2.x:
```
ERROR:reachy_mini.daemon.daemon:Failed to initialize WebRTC:
  'NoneType' object has no attribute 'set_property'
```

Camera tile in desktop app shows perpetual "connecting" spinner because the
daemon's WebRTC pipeline never instantiates.

### Diagnosis
In `media/media_server.py` (Pollen daemon 1.7.x) — same pattern as
`media/webrtc_daemon.py` in 1.2.x:

```python
v4l2h264enc = Gst.ElementFactory.make("v4l2h264enc")
extra_controls_structure = Gst.Structure.new_empty("extra-controls")
extra_controls_structure.set_value("repeat_sequence_header", 1)
extra_controls_structure.set_value("video_bitrate", 5_000_000)
v4l2h264enc.set_property("extra-controls", extra_controls_structure)  # <-- crash here
```

`Gst.ElementFactory.make("v4l2h264enc")` returns `None` because the BCM2712
SoC does not expose a V4L2 m2m H.264 encoder device. Pi 5 / CM5 dropped the
legacy BCM2711-style hardware H.264 encoder entirely; encoding on Pi 5 is
expected to be done in software (or on the GPU via VideoCore VII features
not yet exposed via libcamera).

The `if not all([v4l2h264enc, capsfilter_h264])` guard further down in the
function would catch the None — but it's after the `.set_property()` call,
so the AttributeError fires first.

### v1 (initial) fix and the silent-failure follow-up
First-pass patch: None-guard around `make("v4l2h264enc")` and fall back to
`openh264enc`. After applying:
- Daemon `state` transitions from `error` to `running`. ✅
- Signaling server on 8443 listens, accepts Listener connections. ✅
- Camera registers cleanly: `Registered camera ... using PiSP variant BCM2712_D0`. ✅
- **But Producer never registers, no video flows, desktop app's camera tile
  spins forever**. ❌

Why? `openh264enc`'s sink template explicitly requires
`video/x-raw,format=I420`. `v4l2h264enc` on CM4 was a hardware accelerator
that did colour-space conversion as a silicon side-effect — it transparently
accepted YUY2 from `libcamerasrc`. `openh264enc` doesn't. With the original
linking chain (`queue_webrtc.link(v4l2h264enc)` then v4l2h264enc → caps →
webrtcsink), GStreamer's caps negotiator returns False from `link()` because
YUY2 ↔ I420 is not a passthrough. Pollen never checks the return value, so
the failure is silent.

### Verification of v2 fix
v2 inserts `videoconvert ! video/x-raw,format=I420` between `queue_webrtc`
and the encoder when openh264enc is in use. After applying v2 + restarting
daemon:

```
07:37:37 ... gst_plugin_webrtc_signalling::handlers: registered as [Producer]
              peer_id=49a89f0b-...
07:37:37 ... started a session id=a6de04cd-...
              producer_id=49a89f0b-... consumer_id=18cb6d9c-...
07:37:37 ... Received message Ok(Text(...sdp.offer...H264/90000...
              profile-level-id=42c01f...))
07:37:38 ... Received message Ok(Text(...sdp.answer...recvonly...))
07:37:38 ... ICE candidates exchanged (host + srflx via STUN)
07:37:40 ... Pipeline latency (live=True, min_latency=84000000,
              max_latency=1010232000)
```

Producer registers, session opens, SDP offer (H.264 baseline + OPUS audio +
datachannel) is sent and answered, ICE candidates exchange, pipeline goes
live. End-to-end WebRTC working.

### CPU cost of openh264enc software encoding
At 1296×972 @ 30 fps and 5 Mbps, openh264enc with `complexity=0` on a CM5's
4× A76 cores runs at ~10–15% of one core. Acceptable for telepresence; well
below the threshold where it'd starve other tasks. If quality is insufficient,
`complexity=1` or `complexity=2` (medium / high) trade more CPU for better
rate-distortion at the same bitrate.

### Benign warning to ignore
After the fix, journal includes:
```
The `rtpgccbwe` element is not available not doing any congestion control:
BoolError { ... Failed to find element factory with name 'rtpgccbwe' ... }
```
That's `rtpgccbwe` (Google Congestion Control for WebRTC) being unavailable.
It's part of `gstreamer1.0-plugins-rs` extras, not in the Pollen image. Without
it, the stream runs at fixed 5 Mbps with no auto-bandwidth-adaptation. Fine
for LAN. If you want wide-area streaming with adaptive bitrate later, install
the relevant package — but you don't need it for typical Reachy Mini use.

### CPU cost of openh264enc software encoding
At 1296×972 @ 30 fps and 5 Mbps, openh264enc with `complexity=0` on a CM5's
4× A76 cores runs at ~10–15% of one core. Acceptable for telepresence; well
below the threshold where it'd starve other tasks. If quality is insufficient,
`complexity=1` or `complexity=2` (medium / high) trade more CPU for better
rate-distortion at the same bitrate.

---

## Things tested but not in scope

### Power regulator
`vcgencmd get_throttled` reports `0x0` (no throttling, no undervoltage)
across boot + motor enumeration + WiFi association. Buck regulator on
Pollen's CM5 carrier is sized adequately for at least the no-camera-load
workload. Re-check under sustained camera + motion load when reachy-blip /
conversation app is running.

### IMU
Daemon warning at boot: `Failed to initialize IMU: [Errno 2] No such file
or directory: '/dev/i2c-4'`. The IMU's i2c bus declared by Pollen's
overlay (i2c-4 via `dtoverlay=i2c4,pins_8_9=1`) doesn't enumerate on this
kernel build. Likely the same wrong-bus pattern as the fan controller and
similar fix. Not yet diagnosed — IMU not blocking anything tested so far.

### mDNS service discovery
`/etc/avahi/services/` is empty in the Pollen image. The Pollen daemon
source code has no avahi/mdns service registration. Desktop app can't
auto-discover the robot via service browse; connecting via direct IP
works fine. Cosmetic, not in scope here.
