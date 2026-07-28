"""
Compatibility check against the connected FC's actual live firmware.

The core risk this toolkit has always tried to manage is stale assumptions
-- parameter names/enum values that ArduPilot has renamed, removed, or
changed the meaning of between firmware versions (this already happened
once historically: FS_GCS_ENABLE=2 was removed in Copter 4.0+, see
failsafe.py). Hardcoded parameter names can't detect that kind of drift by
themselves. What CAN detect it: asking the live FC, every time, whether
each parameter this toolkit relies on actually still exists under that
name. A missing parameter here is a direct, concrete signal that a
firmware update has moved past what this toolkit was written against --
much more reliable than silently trusting the code is still correct.

Firmware version decoding verified against
https://mavlink.io/en/messages/common.html (AUTOPILOT_VERSION.flight_sw_version
-- packed as (major<<24)|(minor<<16)|(patch<<8)|FIRMWARE_VERSION_TYPE).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from pymavlink import mavutil

from .connection import FCConnection
from .params import get_param

# Every parameter this toolkit reads or writes anywhere, grouped by the
# wizard step / module that relies on it. If a firmware update removes or
# renames one of these, that step (and only that step) is what's affected
# -- this list is what makes that visible instead of a confusing generic
# failure deep inside a specific step.
CRITICAL_PARAMS: Dict[str, List[str]] = {
    "Frame Class Review": ["FRAME_CLASS", "FRAME_TYPE"],
    "RC Calibration": ["RCMAP_ROLL", "RCMAP_PITCH", "RCMAP_THROTTLE", "RCMAP_YAW",
                        "RC1_MIN", "RC1_MAX", "RC1_TRIM", "RC1_REVERSED"],
    "Flight Modes": ["FLTMODE_CH", "FLTMODE1", "FLTMODE2", "FLTMODE3",
                      "FLTMODE4", "FLTMODE5", "FLTMODE6"],
    "Motor Order & Direction": ["SERVO1_FUNCTION", "SERVO_BLH_RVMASK", "SERVO_DSHOT_ESC"],
    "ESC Calibration": ["MOT_PWM_TYPE", "ESC_CALIBRATION"],
    "Failsafe": ["FS_OPTIONS", "FS_GCS_ENABLE", "FS_THR_ENABLE", "FS_EKF_ACTION", "FS_EKF_THRESH"],
    "Arming Checks": ["ARMING_CHECK"],
}

# Known parameter renames discovered via release-note monitoring, newer than
# the firmware this toolkit's param names/enums were originally verified
# against (Copter 4.6.3, stable 04-Nov-2025). When a CRITICAL_PARAMS entry
# goes missing, this maps it to its successor so the report can say "renamed
# to X" instead of just "gone".
#
# Copter 4.7.0 (stable, 21-Jul-2026) replaced ARMING_CHECK with
# ARMING_SKIPCHK (ArduCopter/ReleaseNotes.txt, section "5) Parameter scaling
# and/or renaming related changes": "ARMING_CHECK replaced with
# ARMING_SKIPCHK (@tpwrules, PR:31568)").
#
# The bit semantics are INVERTED (set bit = skip that check, where
# ARMING_CHECK's set bit = run that check) and bit 0 "All" no longer exists.
# That was confirmed against the parameter's own metadata in ArduPilot
# source at tag Copter-4.7.0 (libraries/AP_Arming/AP_Arming.cpp,
# "// @Param: SKIPCHK" -- "Arm Checks to Skip (bitmask)"), and
# arming_checks.py now handles both encodings explicitly. See that module's
# docstring for the quoted metadata.
KNOWN_RENAMES: Dict[str, str] = {
    "ARMING_CHECK": "ARMING_SKIPCHK",
}


@dataclass
class ParamCheckResult:
    step: str
    name: str
    exists: bool
    renamed_to: Optional[str] = None  # set only when `name` is missing AND
    # `renamed_to` was confirmed present on this live FC -- see KNOWN_RENAMES.


@dataclass
class CompatibilityReport:
    firmware_version: Optional[str]
    results: List[ParamCheckResult]

    @property
    def missing(self) -> List[ParamCheckResult]:
        return [r for r in self.results if not r.exists]

    @property
    def all_ok(self) -> bool:
        return len(self.missing) == 0


def get_firmware_version_string(conn: FCConnection, timeout: float = 4.0) -> Optional[str]:
    """Request AUTOPILOT_VERSION via MAV_CMD_REQUEST_MESSAGE and decode
    flight_sw_version into a "major.minor.patch (type)" string. Returns
    None if the FC doesn't answer in time -- treated as "unknown", not an
    error, since some very old firmware may not support the request.
    """
    conn.master.mav.command_long_send(
        conn.master.target_system,
        conn.master.target_component,
        mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
        0,
        mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION,
        0, 0, 0, 0, 0, 0,
    )
    msg = conn.master.recv_match(type="AUTOPILOT_VERSION", blocking=True, timeout=timeout)
    if msg is None:
        return None
    v = msg.flight_sw_version
    major = (v >> 24) & 0xFF
    minor = (v >> 16) & 0xFF
    patch = (v >> 8) & 0xFF
    version_type = v & 0xFF
    type_entry = mavutil.mavlink.enums.get("FIRMWARE_VERSION_TYPE", {}).get(version_type)
    type_name = type_entry.name.replace("FIRMWARE_VERSION_TYPE_", "") if type_entry else str(version_type)
    return f"{major}.{minor}.{patch} ({type_name})"


def check_param_exists(conn: FCConnection, name: str, timeout: float = 2.0) -> bool:
    try:
        get_param(conn, name, timeout=timeout)
        return True
    except TimeoutError:
        return False


def run_compatibility_check(conn: FCConnection) -> CompatibilityReport:
    """Query the live FC for its firmware version and check every
    parameter this toolkit relies on. This is the mechanism for detecting
    when a future ArduPilot update has moved past what this toolkit was
    written against -- run it any time something in the wizard behaves
    unexpectedly, or just after updating firmware.
    """
    firmware_version = get_firmware_version_string(conn)
    results: List[ParamCheckResult] = []
    for step, names in CRITICAL_PARAMS.items():
        for name in names:
            exists = check_param_exists(conn, name)
            renamed_to = None
            if not exists and name in KNOWN_RENAMES:
                successor = KNOWN_RENAMES[name]
                if check_param_exists(conn, successor):
                    renamed_to = successor
            results.append(ParamCheckResult(step=step, name=name, exists=exists, renamed_to=renamed_to))
    return CompatibilityReport(firmware_version=firmware_version, results=results)
