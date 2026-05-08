#!/usr/bin/env python3
"""02-mediaserver-openh264.py — Reachy Mini CM5 WebRTC encoder fix.

The BCM2712 (Pi 5 / CM5) SoC dropped the legacy V4L2 hardware H.264 encoder
that BCM2711 (Pi 4 / CM4) had. As a result, Gst.ElementFactory.make("v4l2h264enc")
returns None on CM5.

This script applies two CM5-specific fixes to the RPi encoder branch in Pollen's
media pipeline:

1. **None-guard around v4l2h264enc**: Pollen's code calls .set_property() on the
   result of make("v4l2h264enc") before the existing `if not all([...])` guard.
   On CM5 that's an immediate AttributeError that kills media server init.

2. **YUY2 → I420 conversion before openh264enc**: openh264enc only accepts
   video/x-raw,format=I420 input. v4l2h264enc on CM4 transparently accepted
   YUY2 (its silicon did the colour conversion). libcamerasrc on Pi outputs
   YUY2. Without inserting a videoconvert + I420 capsfilter, GStreamer can't
   negotiate caps; the link silently fails (Gst.Element.link returns False),
   the pipeline runs with no data flowing to webrtcsink, and the WebRTC
   Producer never registers — symptom: desktop app's camera tile spins
   forever on "connecting".

Targets file: /venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/media_server.py
Falls back to:  /venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/webrtc_daemon.py
                (older Pollen daemon 1.2.x layout)

Idempotent — safe to re-run after Pollen daemon updates.
"""
import os
import shutil
import sys

# Pollen daemon 1.7.x layout: the RPi encoder branch lives in media_server.py
# and is split across two locations (encoder selection + element linking).
# Pollen daemon 1.2.x layout: same logic in webrtc_daemon.py with a slightly
# shorter encoder chunk (no h264_i_frame_period / video_gop_size).

CANDIDATES = [
    "/venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/media_server.py",
    "/venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/webrtc_daemon.py",
]

# ---------------------------------------------------------------------------
# Encoder-selection chunk (the part that decides v4l2h264enc vs openh264enc).
# Each pattern has a 1.7.x and 1.2.x form.
# ---------------------------------------------------------------------------
OLD_ENC_17 = '''        v4l2h264enc = Gst.ElementFactory.make("v4l2h264enc")
        extra_controls_structure = Gst.Structure.new_empty("extra-controls")
        extra_controls_structure.set_value("repeat_sequence_header", 1)
        extra_controls_structure.set_value("video_bitrate", 5_000_000)
        extra_controls_structure.set_value("h264_i_frame_period", 60)
        extra_controls_structure.set_value("video_gop_size", 256)
        v4l2h264enc.set_property("extra-controls", extra_controls_structure)
'''

NEW_ENC_17 = '''        # CM5 patch: BCM2712 has no v4l2h264enc; fall back to openh264enc.
        # openh264enc requires I420 input (v4l2h264enc accepted YUY2), so we
        # set _cm5_uses_openh264 here and inject videoconvert+capsfilter into
        # the linking chain below.
        _cm5_uses_openh264 = False
        v4l2h264enc = Gst.ElementFactory.make("v4l2h264enc")
        if v4l2h264enc is not None:
            extra_controls_structure = Gst.Structure.new_empty("extra-controls")
            extra_controls_structure.set_value("repeat_sequence_header", 1)
            extra_controls_structure.set_value("video_bitrate", 5_000_000)
            extra_controls_structure.set_value("h264_i_frame_period", 60)
            extra_controls_structure.set_value("video_gop_size", 256)
            v4l2h264enc.set_property("extra-controls", extra_controls_structure)
        else:
            v4l2h264enc = Gst.ElementFactory.make("openh264enc")
            if v4l2h264enc is not None:
                v4l2h264enc.set_property("bitrate", 5_000_000)
                v4l2h264enc.set_property("complexity", 0)
                v4l2h264enc.set_property("gop-size", 60)
                _cm5_uses_openh264 = True
'''

OLD_ENC_12 = '''        v4l2h264enc = Gst.ElementFactory.make("v4l2h264enc")
        extra_controls_structure = Gst.Structure.new_empty("extra-controls")
        extra_controls_structure.set_value("repeat_sequence_header", 1)
        extra_controls_structure.set_value("video_bitrate", 5_000_000)
        v4l2h264enc.set_property("extra-controls", extra_controls_structure)
'''

NEW_ENC_12 = '''        # CM5 patch: BCM2712 has no v4l2h264enc; fall back to openh264enc.
        # openh264enc requires I420 input (v4l2h264enc accepted YUY2), so we
        # set _cm5_uses_openh264 here and inject videoconvert+capsfilter into
        # the linking chain below.
        _cm5_uses_openh264 = False
        v4l2h264enc = Gst.ElementFactory.make("v4l2h264enc")
        if v4l2h264enc is not None:
            extra_controls_structure = Gst.Structure.new_empty("extra-controls")
            extra_controls_structure.set_value("repeat_sequence_header", 1)
            extra_controls_structure.set_value("video_bitrate", 5_000_000)
            v4l2h264enc.set_property("extra-controls", extra_controls_structure)
        else:
            v4l2h264enc = Gst.ElementFactory.make("openh264enc")
            if v4l2h264enc is not None:
                v4l2h264enc.set_property("bitrate", 5_000_000)
                v4l2h264enc.set_property("complexity", 0)
                v4l2h264enc.set_property("gop-size", 30)
                _cm5_uses_openh264 = True
'''

# ---------------------------------------------------------------------------
# Linking chunk (the part that adds elements to the pipeline and wires them).
# Same pattern in both 1.7.x and 1.2.x.
# ---------------------------------------------------------------------------
OLD_LINK = '''        pipeline.add(v4l2h264enc)
        pipeline.add(capsfilter_h264)

        queue_webrtc.link(v4l2h264enc)
        v4l2h264enc.link(capsfilter_h264)
        capsfilter_h264.link(webrtcsink)
'''

NEW_LINK = '''        pipeline.add(v4l2h264enc)
        pipeline.add(capsfilter_h264)

        if _cm5_uses_openh264:
            # openh264enc only accepts video/x-raw,format=I420; libcamerasrc
            # outputs YUY2. Insert videoconvert + capsfilter to bridge.
            _cm5_videoconvert = Gst.ElementFactory.make("videoconvert", "cm5_yuy2_to_i420")
            _cm5_caps_i420 = Gst.ElementFactory.make("capsfilter", "cm5_i420_caps")
            _cm5_caps_i420.set_property(
                "caps", Gst.Caps.from_string("video/x-raw,format=I420")
            )
            pipeline.add(_cm5_videoconvert)
            pipeline.add(_cm5_caps_i420)
            queue_webrtc.link(_cm5_videoconvert)
            _cm5_videoconvert.link(_cm5_caps_i420)
            _cm5_caps_i420.link(v4l2h264enc)
        else:
            queue_webrtc.link(v4l2h264enc)
        v4l2h264enc.link(capsfilter_h264)
        capsfilter_h264.link(webrtcsink)
'''


def patch_file(path: str) -> bool:
    """Apply both encoder + link patches. Idempotent. Returns True on success."""
    with open(path) as f:
        src = f.read()

    if "_cm5_uses_openh264" in src:
        print(f"[skip] already patched: {path}")
        return True

    # Encoder chunk (try 1.7.x first, then 1.2.x)
    if OLD_ENC_17 in src:
        src = src.replace(OLD_ENC_17, NEW_ENC_17)
        version = "1.7.x"
    elif OLD_ENC_12 in src:
        src = src.replace(OLD_ENC_12, NEW_ENC_12)
        version = "1.2.x"
    else:
        return False

    # Linking chunk (same pattern in both versions)
    if OLD_LINK not in src:
        print(
            f"WARNING: encoder chunk patched but link chunk pattern not found in {path}",
            file=sys.stderr,
        )
        return False
    src = src.replace(OLD_LINK, NEW_LINK)

    backup = path + ".bak-cm5patch"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f"[ok]   backup: {backup}")

    with open(path, "w") as f:
        f.write(src)
    print(f"[ok]   patched ({version}): {path}")
    return True


def main() -> int:
    if os.geteuid() != 0:
        print("ERROR: must run as root (use sudo)", file=sys.stderr)
        return 1

    matched = False
    for path in CANDIDATES:
        if not os.path.exists(path):
            continue
        if patch_file(path):
            matched = True
            break  # Pollen ships exactly one of these two files.

    if not matched:
        print(
            "ERROR: no Pollen media-pipeline file found at the expected paths,",
            "or the v4l2h264enc block is not in the expected shape.",
            "Inspect manually:",
            "    grep -rn v4l2h264enc /venvs/mini_daemon/.../reachy_mini/media/",
            sep="\n",
            file=sys.stderr,
        )
        return 2

    print()
    print("Encoder + caps-conversion patch applied. Restart the daemon:")
    print("    sudo systemctl restart reachy-mini-daemon")
    return 0


if __name__ == "__main__":
    sys.exit(main())
