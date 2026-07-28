"""
Arming check bitmask: what's safe to temporarily disable vs. never disable.

Two parameters, two opposite encodings
-------------------------------------
Copter 4.7.0 replaced ARMING_CHECK with ARMING_SKIPCHK, and the new
parameter is NOT a drop-in rename -- it inverts the meaning of every bit.

Release note (ArduCopter/ReleaseNotes.txt, Release 4.7.0-beta1, section
"5) Parameter scaling and/or renaming related changes"), verbatim:

    - ARMING_CHECK replaced with ARMING_SKIPCHK (@tpwrules, PR:31568)

The release note alone does not state the new bit semantics. Those come
from the parameter's own metadata in ArduPilot source at tag Copter-4.7.0
(libraries/AP_Arming/AP_Arming.cpp, "// @Param: SKIPCHK"):

    @DisplayName: Arm Checks to Skip (bitmask)
    @Description: Checks to skip prior to arming motor. This is a bitmask
      of checks before allowing arming that will be skipped. For most users
      it is recommended to leave this at the default of 0 (no checks
      skipped). In extreme circumstances, a value of -1 can be used to skip
      all non-mandatory current and future checks.
    @Bitmask: 1:Barometer,2:Compass,3:GPS lock,4:INS,5:Parameters,
      6:RC Channels,7:Board voltage,8:Battery Level,10:Logging Available,
      11:Hardware safety switch,12:GPS Configuration,13:System,14:Mission,
      15:Rangefinder,16:Camera,17:AuxAuth,18:VisualOdometry,19:FFT

    AP_GROUPINFO("SKIPCHK", 13, AP_Arming, checks_to_skip, 0),

So, concretely:

  * ARMING_CHECK   -- bit SET means "run this check". Bit 0 ("All") is a
    master switch that overrides the individual bits.
  * ARMING_SKIPCHK -- bit SET means "SKIP this check". There is no bit 0 /
    "All"; the default of 0 means nothing is skipped (i.e. everything
    runs). Bits 1..19 carry the same check names as before (verified
    against the @Bitmask line quoted above -- compare it to
    ARMING_CHECK_BITS below).

Writing an old-style value into ARMING_SKIPCHK would therefore disable
exactly the checks the user asked to keep. To keep that impossible, this
module never exposes a raw bitmask to callers: its public API is a set of
ENABLED check names, and it converts to whichever encoding the connected
FC actually uses (see resolve_check_param).

Legacy bit table verified live against the ARMING_CHECK parameter metadata
(parameters-Copter-stable-*.html) -- values are 2**bit_position, confirmed
against the docs' own worked example ("to only allow arming when you have
GPS lock and no RC failsafe you would set ARMING_CHECK to 72" = GPS lock
(2**3=8) + RC Channels (2**6=64) = 72).
"""
from __future__ import annotations

from typing import Dict, Set, Tuple

from .connection import FCConnection
from .params import get_param, set_param

LEGACY_PARAM = "ARMING_CHECK"
SKIP_PARAM = "ARMING_SKIPCHK"


class ArmingCheckParamMissing(RuntimeError):
    """Neither ARMING_CHECK nor ARMING_SKIPCHK exists on the connected FC.

    That means this firmware encodes arming checks in some way this toolkit
    has never seen, so it stops rather than guess at a bitmask.
    """


# bit position -> name, for the pre-4.7.0 ARMING_CHECK parameter (bit SET =
# check ENABLED). Bit 0 "All" is a master override that only exists here.
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

# bit position -> name, for the 4.7.0+ ARMING_SKIPCHK parameter (bit SET =
# check SKIPPED). Derived from ARMING_CHECK_BITS by dropping bit 0, because
# the two bit-to-name mappings are identical for bits 1..19 -- read the
# @Bitmask line quoted in this module's docstring against the table above
# if you need to re-verify that (they were equal as of Copter-4.7.0).
SKIP_CHECK_BITS: Dict[int, str] = {bit: name for bit, name in ARMING_CHECK_BITS.items() if bit != 0}
SKIP_NAME_TO_BIT = {name: bit for bit, name in SKIP_CHECK_BITS.items()}

# Every individually-controllable check, i.e. everything except the legacy
# "All" master switch.
INDIVIDUAL_CHECKS: Set[str] = set(SKIP_CHECK_BITS.values())

# Guidance only -- not enforced in code. These checks exist to catch real
# hazards; disabling them is a deliberate tradeoff the human should make
# knowingly, not something this toolkit should do silently.
NEVER_RECOMMEND_DISABLING = {"RC Channels", "Board voltage", "System", "Parameters", "INS"}
OFTEN_DISABLED_FOR_BENCH_TESTING = {"GPS lock", "GPS Configuration", "Compass", "Battery Level",
                                     "Rangefinder", "Camera", "Barometer"}


def resolve_check_param(conn: FCConnection) -> str:
    """Return whichever arming-check parameter this FC actually has.

    Probes the live FC rather than inferring from a reported firmware
    version string, because the version string is not always trustworthy
    (custom/dev builds) and the parameter's presence is the thing that
    actually matters.
    """
    try:
        get_param(conn, LEGACY_PARAM)
        return LEGACY_PARAM
    except TimeoutError:
        pass
    try:
        get_param(conn, SKIP_PARAM)
        return SKIP_PARAM
    except TimeoutError:
        raise ArmingCheckParamMissing(
            f"Neither {LEGACY_PARAM} nor {SKIP_PARAM} was found on this flight "
            "controller. This toolkit only knows those two encodings of the "
            "arming checks, so it will not read or write them here. Pull the "
            "live parameter list and look for the current arming-check "
            "parameter before configuring this by hand."
        )


def compute_value(enabled: Set[str]) -> int:
    """Compose a legacy ARMING_CHECK value from a set of ENABLED check names.

    If "All" is in the set, every other bit is redundant (and, per
    ArduPilot's own documented behavior, the individual bits are effectively
    ignored while "All" is set) -- this function still sets them for
    transparency, but warns.
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


def compute_skip_value(enabled: Set[str]) -> int:
    """Compose a 4.7.0+ ARMING_SKIPCHK value from a set of ENABLED check names.

    Inverts: anything the caller did NOT list as enabled gets its skip bit
    set. "All" is accepted for API compatibility with the legacy parameter
    and means "enable everything", i.e. skip nothing (value 0).

    Note this deliberately writes explicit skip bits rather than the -1
    ("skip all non-mandatory current and future checks") shortcut the
    metadata mentions -- -1 would also silently skip checks added by future
    firmware, which is exactly the kind of open-ended assumption this
    toolkit avoids.
    """
    unknown = enabled - INDIVIDUAL_CHECKS - {"All"}
    if unknown:
        raise KeyError(
            f"Unknown arming check(s) {sorted(unknown)}. "
            f"Valid names: {sorted(INDIVIDUAL_CHECKS)}"
        )
    if "All" in enabled:
        return 0
    value = 0
    for name in INDIVIDUAL_CHECKS - enabled:
        value |= 1 << SKIP_NAME_TO_BIT[name]
    return value


def describe_value(param_name: str, value: int) -> str:
    """Human-readable summary of a written value, in that parameter's own
    encoding -- the encoding is named explicitly so a skip-mask can never be
    read back as if it were an enable-mask.
    """
    if param_name == SKIP_PARAM:
        skipped = sorted(name for bit, name in SKIP_CHECK_BITS.items() if value & (1 << bit))
        if not skipped:
            return f"{SKIP_PARAM}={value}: no checks skipped (all arming checks run)"
        return f"{SKIP_PARAM}={value}: SKIPPING " + "; ".join(skipped)
    active = [name for bit, name in ARMING_CHECK_BITS.items() if value & (1 << bit)]
    return f"{LEGACY_PARAM}={value}: " + ("; ".join(active) if active else "no checks enabled (not recommended)")


def read_current(conn: FCConnection) -> Set[str]:
    """Return the set of currently ENABLED check names, whichever parameter
    this firmware uses."""
    param = resolve_check_param(conn)
    value = int(get_param(conn, param))
    if param == SKIP_PARAM:
        # Bit set = skipped, so enabled is the complement. A value of -1
        # ("skip everything") lands here correctly: in Python, -1 has every
        # bit set, so nothing comes back as enabled.
        skipped = {name for bit, name in SKIP_CHECK_BITS.items() if value & (1 << bit)}
        enabled = INDIVIDUAL_CHECKS - skipped
        if not skipped:
            # Nothing skipped is the exact equivalent of the legacy "All".
            enabled = enabled | {"All"}
        return enabled
    return {name for bit, name in ARMING_CHECK_BITS.items() if value & (1 << bit)}


def apply(conn: FCConnection, enabled: Set[str]) -> Tuple[str, int]:
    """Write the arming checks from an explicit set of ENABLED check names.

    Returns (parameter_name, written_value) -- the name is part of the
    return value so callers report which encoding was actually used rather
    than assuming ARMING_CHECK. Applies live, no reboot needed: arming
    checks are evaluated at arm time.
    """
    param = resolve_check_param(conn)
    value = compute_skip_value(enabled) if param == SKIP_PARAM else compute_value(enabled)
    set_param(conn, param, value)
    print(describe_value(param, value))
    return param, value


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
    "All": "Master switch meaning 'run every check'. On firmware using ARMING_CHECK "
           "(pre-4.7.0) this literally sets bit 0, which overrides the individual boxes -- "
           "uncheck All first if you want only specific checks. On Copter 4.7.0+ "
           "(ARMING_SKIPCHK) there is no All bit; checking this simply means nothing is "
           "skipped, which has the same effect.",
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
