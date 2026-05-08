#!/usr/bin/env python3
"""02-mediaserver-openh264.py — Reachy Mini CM5 WebRTC encoder fix

The BCM2712 (Pi 5 / CM5) SoC dropped the legacy V4L2 hardware H.264 encoder
that BCM2711 (Pi 4 / CM4) had. As a result, Gst.ElementFactory.make("v4l2h264enc")
returns None on CM5.

Pollen's media pipeline calls .set_property() on that result *before* checking
if it's None, raising AttributeError that kills media server init. The bug
exists in both Pollen daemon 1.2.x (in webrtc_daemon.py) and 1.7.x (in
media_server.py) — same logic, different file.

This patch adds a None-guard and falls back to openh264enc (software H.264
encoder, present in gstreamer1.0-plugins-bad). CM5's 4× A76 cores at 2.4 GHz
comfortably encode 1296×972 @ 30 fps at 5 Mbps in software with ~10–15% CPU.

Targets file: /venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/media_server.py
Falls back to:  /venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/webrtc_daemon.py
                (older Pollen daemon 1.2.x layout)

Idempotent — safe to re-run after Pollen daemon updates.
"""
import os
import shutil
import sys

CANDIDATES = [
    # Pollen daemon 1.7.x+
    "/venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/media_server.py",
    # Pollen daemon 1.2.x
    "/venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/webrtc_daemon.py",
]

# 1.7.x pattern (longer, includes h264_i_frame_period + video_gop_size)
OLD_17 = '''        v4l2h264enc = Gst.ElementFactory.make("v4l2h264enc")
        extra_controls_structure = Gst.Structure.new_empty("extra-controls")
        extra_controls_structure.set_value("repeat_sequence_header", 1)
        extra_controls_structure.set_value("video_bitrate", 5_000_000)
        extra_controls_structure.set_value("h264_i_frame_period", 60)
        extra_controls_structure.set_value("video_gop_size", 256)
        v4l2h264enc.set_property("extra-controls", extra_controls_structure)
'''

NEW_17 = '''        # CM5 patch: BCM2712 has no v4l2h264enc; fall back to openh264enc software encoder.
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
'''

# 1.2.x pattern (shorter, no h264_i_frame_period / video_gop_size)
OLD_12 = '''        v4l2h264enc = Gst.ElementFactory.make("v4l2h264enc")
        extra_controls_structure = Gst.Structure.new_empty("extra-controls")
        extra_controls_structure.set_value("repeat_sequence_header", 1)
        extra_controls_structure.set_value("video_bitrate", 5_000_000)
        v4l2h264enc.set_property("extra-controls", extra_controls_structure)
'''

NEW_12 = '''        # CM5 patch: BCM2712 has no v4l2h264enc; fall back to openh264enc software encoder.
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
'''

PATTERNS = [
    (OLD_17, NEW_17, "1.7.x"),
    (OLD_12, NEW_12, "1.2.x"),
]


def patch(path: str) -> bool:
    """Return True if patched (or already patched), False if pattern not found."""
    with open(path) as f:
        src = f.read()

    if "CM5 patch: BCM2712 has no v4l2h264enc" in src:
        print(f"[skip] already patched: {path}")
        return True

    for old, new, version in PATTERNS:
        if old in src:
            backup = path + ".bak-cm5patch"
            if not os.path.exists(backup):
                shutil.copy2(path, backup)
                print(f"[ok]   backup: {backup}")
            src2 = src.replace(old, new)
            with open(path, "w") as f:
                f.write(src2)
            print(f"[ok]   patched ({version} pattern): {path}")
            return True

    return False


def main() -> int:
    if os.geteuid() != 0:
        print("ERROR: must run as root (use sudo)", file=sys.stderr)
        return 1

    matched = False
    for path in CANDIDATES:
        if not os.path.exists(path):
            continue
        if patch(path):
            matched = True
            # Pollen ships exactly one of these two files; stop after first hit.
            break

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
    print("WebRTC encoder patch applied. Restart the daemon for it to take effect:")
    print("    sudo systemctl restart reachy-mini-daemon")
    return 0


if __name__ == "__main__":
    sys.exit(main())
