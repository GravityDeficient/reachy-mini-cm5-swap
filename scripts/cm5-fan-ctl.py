#!/usr/bin/env python3
"""cm5-fan-ctl.py — Reachy Mini CM5 fan controller stopgap.

The Pollen Reachy Mini head PCB has an EMC2301 single-channel PWM fan
controller wired to i2c-10 at address 0x2f. Two problems on CM5:

  1. Pollen's stock dtoverlay declares the chip on i2c-0 (probably correct
     for CM4 routing). On CM5 the chip is physically wired to i2c-10. The
     kernel never finds the chip on the declared bus.
  2. The +rpt-rpi-2712 kernel build does not include an `emc2301` driver
     (only `emc2305`, the 5-channel sibling, which doesn't bind to the
     `smsc,emc2301` compatible string).

Result: no host ever talks to the chip, and EMC2301 defaults to 100% PWM
as a hardware failsafe ("the host crashed, ramp the fan to protect the SoC").
The fan runs at full speed continuously regardless of CPU temp.

This script is a userspace stopgap. Polls /sys/class/thermal/thermal_zone0/temp
every 5 seconds and writes the EMC2301 FAN_SETTING register (0x30) directly
via /dev/i2c-10. Hysteretic temperature bands prevent oscillation.

Run as root (needs /dev/i2c-10 access). Persist via the systemd unit in this
repo, cm5-fan-ctl.service.

Long-term proper fixes:
  - Pollen ships an updated dtoverlay declaring i2c-10 (and a CM5 conditional)
  - Upstream Pi kernel ships an emc2301 hwmon driver
  - Either of those would make this script obsolete.
"""
import fcntl
import time

I2C_BUS = 10
EMC_ADDR = 0x2F
REG_FAN_SETTING = 0x30
THERM_PATH = "/sys/class/thermal/thermal_zone0/temp"
POLL_S = 5

# Hysteretic temperature bands. Going up: cross HEAT threshold to enter higher
# band. Going down: drop below COOL threshold to leave. Deadband ≈ 3°C wider
# than typical short-term thermal noise.
BANDS = [
    # heat,cool, pwm    description
    (   0,   0, 0x00),  # off (below 42°C — entry threshold = 0 since this is the bottom band)
    (  45,  42, 0x40),  # 25%
    (  52,  49, 0x80),  # 50%
    (  60,  57, 0xC0),  # 75%
    (  68,  65, 0xFF),  # 100%
]

I2C_SLAVE = 0x0703  # ioctl number for setting i2c slave address


def read_temp_c() -> float:
    with open(THERM_PATH) as f:
        return int(f.read()) / 1000.0


def i2c_write(bus: int, addr: int, reg: int, val: int) -> None:
    with open(f"/dev/i2c-{bus}", "wb") as f:
        fcntl.ioctl(f, I2C_SLAVE, addr)
        f.write(bytes([reg, val]))


def pick_band(t: float, current_idx: int) -> int:
    """Step up to highest band whose heat threshold has been crossed,
    or step down to the band below current if we've dropped below its cool
    threshold. Step at most one band at a time per poll."""
    # Step up as far as needed
    for i in range(current_idx + 1, len(BANDS)):
        if t >= BANDS[i][0]:
            current_idx = i
        else:
            break
    # Step down one band if appropriate
    while current_idx > 0 and t < BANDS[current_idx][1]:
        current_idx -= 1
    return current_idx


def main() -> None:
    idx = 0
    last_pwm = -1
    while True:
        t = read_temp_c()
        idx = pick_band(t, idx)
        pwm = BANDS[idx][2]
        if pwm != last_pwm:
            try:
                i2c_write(I2C_BUS, EMC_ADDR, REG_FAN_SETTING, pwm)
                last_pwm = pwm
                print(f"temp={t:.1f}C pwm=0x{pwm:02x} band={idx}", flush=True)
            except Exception as e:
                print(f"i2c write failed: {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
