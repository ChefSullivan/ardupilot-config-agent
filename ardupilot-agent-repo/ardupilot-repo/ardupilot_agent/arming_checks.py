"""
ARMING_CHECK bitmask: what's safe to temporarily disable vs. never disable.

Bit table verified live against the ARMING_CHECK parameter metadata
(parameters-Copter-stable-*.html) -- values are 2**bit_position, confirmed
against the docs' own worked example ("to only allow arming when you have
GPS lock and no RC failsafe you would set ARMING_CHECK to 72" = GPS lock
(2**3=8) + RC Channels (2**6=64) = 72).

Important gotcha straight from the ArduPilot community docs: bit 0 ("All")
being set overrides individual bits -- if you want anything other than
every check enabled, you must clear bit 0 and then set only the specific
bits you want, or your other settings silently do nothing.
"""
from __future__ import annotations

from typing import Dict, Set

from .connection import FCConnection
from .params import get_param, set_param

# bit position -> name (verified against ARMING_CHECK parameter metadata)
ARMING_CHECK_BITS: Dict[int, str] = {
    0: "All",
    1: "Barometer",
    2: "Compass",
    3: "GPS lock",
    4: "INS",
    5: "Parameters",
    6: "RC Channels",
    7: "Board voltage",
    8: "Battery Level",
    10: "Logging Available",
    11: "Hardware safety switch",
    12: "GPS Configuration",
    13: "System",
    14: "Mission",
    15: "Rangefinder",
    16: "Camera",
    17: "AuxAuth",
    18: "VisualOdometry",
    19: "FFT",
}
NAME_TO_BIT = {name: bit for bit, name in ARMING_CHECK_BITS.items()}

# Guidance only -- not enforced in code. These checks exist to catch real
# hazards; disabling them is a deliberate tradeoff the human should make
# knowingly, not something this toolkit should do silently.
NEVER_RECOMMEND_DISABLING = {"RC Channels", "Board voltage", "System", "Parameters", "INS"}
OFTEN_DISABLED_FOR_BENCH_TESTING = {"GPS lock", "GPS Configuration", "Compass", "Battery Level",
                                     "Rangefinder", "Camera", "Barometer"}


def compute_value(enabled: Set[str]) -> int:
    """Compose the ARMING_CHECK value from a set of check names. If "All" is
    in the set, every other bit is redundant (and, per ArduPilot's own
    documented behavior, the individual bits are effectively ignored while
    "All" is set) -- this function still sets them for transparency, but
    warns.
    """
    if "All" in enabled and len(enabled) > 1:
        print('WARNING: "All" is set alongside individual checks. ArduPilot ignores the '
              'individual bits while "All" (bit 0) is set -- clear "All" if you want to '
              "enable only specific checks.")
    value = 0
    for name in enabled:
        if name not in NAME_TO_BIT:
            raise KeyError(f"Unknown arming check '{name}'. Valid names: {sorted(NAME_TO_BIT.keys())}")
        value |= 1 << NAME_TO_BIT[name]
    return value


def describe_value(value: int) -> str:
    active = [name for bit, name in ARMING_CHECK_BITS.items() if value & (1 << bit)]
    return f"ARMING_CHECK={value}: " + ("; ".join(active) if active else "no checks enabled (not recommended)")


def read_current(conn: FCConnection) -> Set[str]:
    value = int(get_param(conn, "ARMING_CHECK"))
    return {name for bit, name in ARMING_CHECK_BITS.items() if value & (1 << bit)}


def apply(conn: FCConnection, enabled: Set[str]) -> int:
    """Write ARMING_CHECK from an explicit set of check names. Applies
    live, no reboot needed -- arming checks are evaluated at arm time.
    """
    value = compute_value(enabled)
    set_param(conn, "ARMING_CHECK", value)
    print(describe_value(value))
    return value


# Per-check plain-language explanation + what hardware/equipment it relates
# to, so a user can make an informed decision about what to disable for
# bench testing vs. what to never touch. Verified against
# https://ardupilot.org/copter/docs/common-prearm-safety-checks.html
# (per-category failure-message descriptions) -- "GPS Configuration",
# "Camera", "AuxAuth", "VisualOdometry", and "FFT" aren't broken out with
# their own subsection on that page, so those five are written from the
# parameter's own short name/purpose rather than a quoted failure
# description; everything else below is grounded in that page's wording.
ARMING_CHECK_TOOLTIPS: Dict[str, str] = {
    "All": "Master switch. When checked, every individual check below runs regardless of "
           "its own checkbox -- uncheck All first if you want to enable only specific checks.",
    "Barometer": "Checks the barometer (altitude/pressure sensor) is reporting healthy data and "
                 "roughly agrees with the accelerometer-based altitude estimate. Hardware: the "
                 "autopilot's built-in barometer (all boards have one) -- no extra equipment needed.",
    "Compass": "Checks the compass/magnetometer is healthy, calibrated, and its reading is "
               "plausible for your location. Hardware: the autopilot's internal compass and/or "
               "any external compass (often built into a GPS module) -- irrelevant if you have "
               "no compass at all and rely on GPS-only heading, but most setups have one.",
    "GPS lock": "Requires a 3D GPS fix (and reasonable position accuracy/HDOP) before arming. "
                "Hardware: a GPS module. Only matters if you plan to use GPS-dependent modes "
                "(Loiter, RTL, Auto, PosHold, etc.) -- irrelevant for Stabilize/Acro-only flying "
                "with no GPS connected.",
    "INS": "Checks the accelerometers and gyros (the core IMU) are calibrated, healthy, and "
           "multiple sensors (if present) agree with each other. Hardware: the autopilot's "
           "built-in IMU -- every board has this, never optional.",
    "Parameters": "Checks for a handful of specific parameter misconfigurations that are known "
                  "to cause problems (e.g. two aux switches set to the same function, an unsafe "
                  "max lean angle, a failsafe PWM value too close to throttle minimum). No extra "
                  "hardware -- purely a configuration sanity check.",
    "RC Channels": "Checks valid RC input is being received. Hardware: your transmitter and "
                   "receiver, wired to the flight controller -- this will always fail if no RC "
                   "receiver is connected/bound, which is expected on a bench setup with no radio.",
    "Board voltage": "Checks the autopilot's own input voltage is in a safe range (roughly "
                      "4.3-5.8V). Hardware: your power module / BEC / USB supply -- on USB power "
                      "this can fail if the computer's USB port can't supply enough current.",
    "Battery Level": "Checks a connected battery monitor's voltage/remaining capacity is above "
                      "the failsafe and (if set) minimum-arming thresholds. Hardware: a power "
                      "module or other battery monitor -- irrelevant if none is configured.",
    "Logging Available": "Checks that logging is enabled and actually able to write (usually "
                          "means an SD card is present and working). Hardware: the autopilot's "
                          "SD card slot.",
    "Hardware safety switch": "Checks the physical safety switch (if your board has one) has "
                               "been pressed to the solid-on state. Hardware: boards with a "
                               "dedicated safety button/LED (many Pixhawk-family boards) -- "
                               "irrelevant on boards with no safety switch.",
    "GPS Configuration": "Checks that GPS-related setup is internally consistent -- e.g. multiple "
                          "configured GPS units / GPS blending settings make sense together. "
                          "Hardware: same as GPS lock -- only relevant if you have one or more "
                          "GPS modules connected.",
    "System": "Checks core system health: parameter storage readable, no internal firmware "
              "errors, and (if used) CAN-bus systems like DroneCAN/KDECAN are responding. "
              "Hardware: varies -- CAN-bus related failures need CAN peripherals connected.",
    "Mission": "If mission/rally-point checking is enabled, checks a valid mission (and rally "
               "points, if required) is actually loaded before allowing arming in an AUTO-style "
               "flow. No extra hardware -- a mission-content check.",
    "Rangefinder": "If a rangefinder (e.g. lidar/sonar distance sensor) is configured, checks "
                   "it's reporting without errors. Hardware: a rangefinder -- irrelevant if you "
                   "don't have one connected.",
    "Camera": "If a camera/gimbal trigger is configured, checks its setup is valid. Hardware: a "
              "camera mount/trigger or gimbal -- irrelevant without one.",
    "AuxAuth": "Lets an external system -- a companion computer or a Lua script -- veto arming "
               "over MAVLink until it reports ready. Hardware/software: only relevant if you're "
               "running a companion computer or auxiliary-authorization Lua script; otherwise "
               "this check trivially passes.",
    "VisualOdometry": "If a non-GPS vision positioning system is configured, checks it's healthy. "
                       "Hardware: a vision/odometry sensor (e.g. a tracking camera) -- irrelevant "
                       "without one.",
    "FFT": "If the gyro harmonic-notch/FFT-based vibration analysis feature is enabled, checks "
           "it's configured and running correctly. No extra hardware -- uses the existing gyros, "
           "purely a software/tuning feature.",
}
