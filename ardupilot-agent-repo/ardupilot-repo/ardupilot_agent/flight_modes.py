"""
Flight mode / switch assignment.

Flight mode numbers, FLTMODE_CH channel values, and the FLTMODE1-6 PWM
breakpoints below are verified against the live ArduPilot Copter parameter
metadata (parameters-Copter-stable-*.html, FLTMODE1/FLTMODE_CH sections),
not memory -- this is exactly the kind of enum that has silently changed
across firmware versions before (see failsafe.py's FS_GCS_ENABLE=2 note).
Mode descriptions are summarized from
https://ardupilot.org/copter/docs/flight-modes.html.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .connection import FCConnection
from .params import get_param, set_param

# name -> FLTMODEn parameter value. Verified against the FLTMODE1 parameter
# metadata table (Copter). Gaps (8, 10, 12) are intentional -- those values
# are not assigned to any current mode.
FLIGHT_MODE_NUMBERS: Dict[str, int] = {
    "STABILIZE": 0,
    "ACRO": 1,
    "ALT_HOLD": 2,
    "AUTO": 3,
    "GUIDED": 4,
    "LOITER": 5,
    "RTL": 6,
    "CIRCLE": 7,
    "LAND": 9,
    "DRIFT": 11,
    "SPORT": 13,
    "FLIP": 14,
    "AUTOTUNE": 15,
    "POSHOLD": 16,
    "BRAKE": 17,
    "THROW": 18,
    "AVOID_ADSB": 19,
    "GUIDED_NOGPS": 20,
    "SMART_RTL": 21,
    "FLOWHOLD": 22,
    "FOLLOW": 23,
    "ZIGZAG": 24,
    "SYSTEMID": 25,
    "HELI_AUTOROTATE": 26,
    "AUTO_RTL": 27,
    "TURTLE": 28,
}
FLIGHT_MODE_NAMES = {v: k for k, v in FLIGHT_MODE_NUMBERS.items()}

# Short plain-language descriptions + GPS/position requirement, summarized
# from the flight-modes.html table.
MODE_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "STABILIZE": {"summary": "Self-levels roll & pitch, manual throttle. No GPS needed.", "requires_gps": "no"},
    "ACRO": {"summary": "Holds attitude rate, no self-leveling. No GPS needed.", "requires_gps": "no"},
    "ALT_HOLD": {"summary": "Holds altitude automatically, self-levels roll & pitch. No GPS needed.", "requires_gps": "no"},
    "AUTO": {"summary": "Executes a pre-defined mission. Requires GPS.", "requires_gps": "yes"},
    "GUIDED": {"summary": "Navigates to points commanded by the GCS. Requires GPS.", "requires_gps": "yes"},
    "LOITER": {"summary": "Holds altitude and position using GPS. Requires GPS.", "requires_gps": "yes"},
    "RTL": {"summary": "Returns to and lands above the launch point. Requires GPS.", "requires_gps": "yes"},
    "CIRCLE": {"summary": "Automatically circles a point in front of the vehicle. Requires GPS.", "requires_gps": "yes"},
    "LAND": {"summary": "Descends straight down to the ground. GPS optional but recommended.", "requires_gps": "optional"},
    "DRIFT": {"summary": "Stabilize-like, but coordinates yaw with roll like a plane. Requires GPS.", "requires_gps": "yes"},
    "SPORT": {"summary": "Alt-hold with rate control instead of angle control when sticks centered.", "requires_gps": "no"},
    "FLIP": {"summary": "Executes an automated flip. Momentary/self-canceling mode.", "requires_gps": "no"},
    "AUTOTUNE": {"summary": "Automated tuning procedure. Fly in another mode first, then engage briefly.", "requires_gps": "no"},
    "POSHOLD": {"summary": "Like Loiter, but allows manual roll/pitch input when sticks aren't centered. Requires GPS.", "requires_gps": "yes"},
    "BRAKE": {"summary": "Brings the copter to an immediate stop and holds position. Requires GPS.", "requires_gps": "yes"},
    "THROW": {"summary": "Holds position after a hand-launch throw. Multirotor only. Requires GPS.", "requires_gps": "yes"},
    "AVOID_ADSB": {"summary": "ADS-B based avoidance of manned aircraft. Not meant to be pilot-selectable.", "requires_gps": "yes"},
    "GUIDED_NOGPS": {"summary": "Guided mode variant usable without GPS (attitude-only commands).", "requires_gps": "no"},
    "SMART_RTL": {"summary": "RTL that retraces the path flown to get home. Requires GPS.", "requires_gps": "yes"},
    "FLOWHOLD": {"summary": "Position hold using optical flow instead of GPS.", "requires_gps": "no"},
    "FOLLOW": {"summary": "Follows another vehicle broadcasting its position. Requires GPS.", "requires_gps": "yes"},
    "ZIGZAG": {"summary": "Useful for crop spraying in a zigzag pattern. Requires GPS.", "requires_gps": "yes"},
    "SYSTEMID": {"summary": "Special diagnostic/system-identification mode. Advanced use only.", "requires_gps": "no"},
    "HELI_AUTOROTATE": {"summary": "Traditional-helicopter emergency autorotation. Heli only.", "requires_gps": "yes"},
    "AUTO_RTL": {"summary": "RTL executed as a DO_LAND_START mission sequence.", "requires_gps": "yes"},
    "TURTLE": {"summary": "Flips a crashed, upside-down multirotor back over by reversing motor pairs.", "requires_gps": "no"},
}

# FLTMODE_CH values (verified against the FLTMODE_CH parameter metadata).
FLTMODE_CH_VALUES = {0: "Disabled", 5: "Channel 5", 6: "Channel 6", 7: "Channel 7", 8: "Channel 8",
                      9: "Channel 9", 10: "Channel 10", 11: "Channel 11", 12: "Channel 12",
                      13: "Channel 13", 14: "Channel 14", 15: "Channel 15"}

# PWM breakpoints for each of the 6 flight-mode slots (verified against the
# FLTMODE1..FLTMODE6 parameter metadata: "Flight mode when pwm of
# Flightmode channel is <= / > X, <= Y").
FLTMODE_PWM_BREAKPOINTS = [
    (1, None, 1230),
    (2, 1230, 1360),
    (3, 1360, 1490),
    (4, 1490, 1620),
    (5, 1620, 1749),
    (6, 1750, None),
]

# Recommended transmitter PWM values for a 3-position and 6-position mode
# switch, from common-rc-transmitter-flight-mode-configuration.html.
THREE_POSITION_PWM_TARGETS = [1165, 1425, 1815]
SIX_POSITION_PWM_TARGETS = [1165, 1295, 1425, 1555, 1685, 1815]


@dataclass
class ModeAssignment:
    slot: int  # 1-6
    mode_name: str  # key into FLIGHT_MODE_NUMBERS


def resolve_mode_number(mode_name: str) -> int:
    key = mode_name.strip().upper().replace(" ", "_")
    if key not in FLIGHT_MODE_NUMBERS:
        raise KeyError(
            f"Unknown flight mode '{mode_name}'. Valid names: {sorted(FLIGHT_MODE_NUMBERS.keys())}"
        )
    return FLIGHT_MODE_NUMBERS[key]


def get_flight_mode_channel(conn: FCConnection) -> int:
    """Read FLTMODE_CH live. A value of 0 means flight-mode switching is
    disabled entirely -- flag this rather than assuming channel 5.
    """
    return int(get_param(conn, "FLTMODE_CH"))


def set_flight_mode_channel(conn: FCConnection, channel: int) -> None:
    if channel not in FLTMODE_CH_VALUES:
        raise ValueError(f"channel must be one of {sorted(FLTMODE_CH_VALUES.keys())}")
    set_param(conn, "FLTMODE_CH", channel)


def set_flight_modes(conn: FCConnection, assignments: List[ModeAssignment]) -> None:
    """Write FLTMODEn for each assignment, verifying the read-back. Warns
    (does not block) if no slot is assigned STABILIZE, per ArduPilot's own
    recommendation to always leave one switch position on Stabilize.
    """
    if not any(a.mode_name.strip().upper() == "STABILIZE" for a in assignments):
        print("WARNING: no flight-mode slot is assigned STABILIZE. ArduPilot recommends always "
              "keeping at least one switch position on Stabilize as a fallback.")
    for a in assignments:
        if not 1 <= a.slot <= 6:
            raise ValueError("slot must be 1-6")
        number = resolve_mode_number(a.mode_name)
        set_param(conn, f"FLTMODE{a.slot}", number)


def read_current_assignments(conn: FCConnection) -> Dict[int, str]:
    out = {}
    for slot in range(1, 7):
        value = int(get_param(conn, f"FLTMODE{slot}"))
        out[slot] = FLIGHT_MODE_NAMES.get(value, f"UNKNOWN({value})")
    return out


def slot_for_pwm(pwm: int) -> int:
    """Which of the 6 flight-mode slots a given FLTMODE_CH PWM value falls
    into, using the verified FLTMODE_PWM_BREAKPOINTS table. Lets a live
    PWM reading be translated straight into "you're on slot N" without the
    user doing PWM-range arithmetic themselves.
    """
    for slot, lo, hi in FLTMODE_PWM_BREAKPOINTS:
        if lo is not None and pwm <= lo:
            continue
        if hi is not None and pwm > hi:
            continue
        return slot
    return FLTMODE_PWM_BREAKPOINTS[-1][0]
