"""
Plain-English descriptions for the parameters this toolkit already touches
elsewhere (frame, RC, modes, motors, ESC, failsafe, arming). NOT a
replacement for ArduPilot's full parameter metadata (thousands of entries)
-- that's out of scope here. This is a small curated set for the
Parameters tab so the params most people touch during first-time setup
aren't just bare names. Anything not in this dict still works in the
Parameters tab exactly as before; this only adds a friendlier label when
we happen to already know one from elsewhere in this toolkit.
"""
from __future__ import annotations

PARAM_DESCRIPTIONS = {
    "FRAME_CLASS": "Overall vehicle frame category (Quad/Hexa/Octa/etc). See the Setup Wizard's Frame step for a human-readable value.",
    "FRAME_TYPE": "Motor layout/rotation convention for your frame class (X/Plus/BetaFlightX/etc).",
    "MOT_PWM_TYPE": "ESC signal protocol. 0/1/2 = analog PWM/OneShot/OneShot125 (need ESC calibration). Anything else = DShot/digital (no calibration needed).",
    "MOT_SPIN_MIN": "Minimum motor output (0-1) below which a motor may not spin at all -- test throttles below this can look like a dead motor when it isn't.",
    "RCMAP_ROLL": "Which physical RC channel controls Roll.",
    "RCMAP_PITCH": "Which physical RC channel controls Pitch.",
    "RCMAP_THROTTLE": "Which physical RC channel controls Throttle.",
    "RCMAP_YAW": "Which physical RC channel controls Yaw.",
    "FLTMODE_CH": "Which RC channel selects the flight mode (0 = disabled).",
    "FLTMODE1": "Flight mode assigned to switch position 1 (lowest PWM range).",
    "FLTMODE2": "Flight mode assigned to switch position 2.",
    "FLTMODE3": "Flight mode assigned to switch position 3.",
    "FLTMODE4": "Flight mode assigned to switch position 4.",
    "FLTMODE5": "Flight mode assigned to switch position 5.",
    "FLTMODE6": "Flight mode assigned to switch position 6 (highest PWM range).",
    "FS_OPTIONS": "Bitmask of what keeps running during a failsafe (continue mission, continue landing, etc). See the Setup Wizard's Failsafe step for a plain-language preset picker.",
    "FS_GCS_ENABLE": "What happens by default when the GCS/telemetry link is lost.",
    "FS_THR_ENABLE": "What happens by default when the RC/radio link is lost.",
    "ARMING_CHECK": "Bitmask of pre-arm safety checks. See the Setup Wizard's Arming Checks step for a plain-language preset picker.",
    "ESC_CALIBRATION": "Set to 3 to arm semi-automatic ESC calibration on next power-up (battery only, no USB).",
    "SERVO_BLH_RVMASK": "Per-output bitmask of which DShot-driven motors are commanded to spin in reverse (requires SERVO_DSHOT_ESC set).",
    "SERVO_DSHOT_ESC": "DShot command-set type. Must be set (e.g. 1) for DShot commands like LED/buzzer/reverse-direction to be sent at all.",
}

# A short, curated jump-list for the Parameters tab's "Common searches"
# quick-pick -- these are substrings that reliably surface the params most
# people are actually looking for during first-time setup.
COMMON_SEARCHES = [
    "FRAME", "RCMAP", "RC1_", "FLTMODE", "MOT_PWM", "SERVO1_FUNCTION",
    "FS_", "ARMING_CHECK", "ESC_CALIBRATION", "SERVO_BLH", "SERVO_DSHOT",
]


def describe_param(name: str) -> str:
    return PARAM_DESCRIPTIONS.get(name.strip().upper(), "")


def describe_param_full(name: str) -> str:
    """Best available explanation for a parameter name: the specific
    curated description if this toolkit already knows one (describe_param),
    otherwise a decoded prefix/jargon breakdown (decode_param_name), so the
    Parameters tab always shows *something* useful instead of "common
    params only" -- what's common differs by what the user is doing.
    """
    specific = describe_param(name)
    if specific:
        return specific
    return decode_param_name(name)


# Prefix/jargon glossary -- ArduPilot parameter names are built from a
# subsystem prefix (often an abbreviation) plus an optional instance number
# plus a specific setting name, e.g. RNGFND1_GNDCLEAR = Rangefinder,
# instance 1, ground-clearance offset. This decodes the PREFIX part of any
# parameter name into plain English, so a param this toolkit has no specific
# curated description for (see PARAM_DESCRIPTIONS above) is still less
# opaque -- this is deliberately general instead of a fixed "common params"
# list, since what's "common" differs by what the user is actually doing.
PREFIX_GLOSSARY = {
    "AHRS": "Attitude and Heading Reference System -- the core orientation estimator.",
    "ARMING": "Arming checks and behavior (see the Setup Wizard's Arming Checks step).",
    "ATC": "Attitude Control -- rate/angle controller tuning (how aggressively it corrects roll/pitch/yaw).",
    "AUTO": "Auto (mission) mode behavior.",
    "AVOID": "Obstacle/fence avoidance behavior.",
    "BARO": "Barometer -- the altitude/air-pressure sensor.",
    "BATT": "Battery monitor (voltage/current/capacity sensing).",
    "BRD": "Board-level hardware settings (safety switch, IMU orientation, PWM output config, etc).",
    "CAN": "CAN bus -- used by DroneCAN peripherals (some GPS/ESC/sensor setups).",
    "COMPASS": "Compass/magnetometer -- used for heading.",
    "EK2": "EKF2 -- an older Extended Kalman Filter core (position/velocity/attitude estimator fusing GPS, IMU, compass, baro).",
    "EK3": "EKF3 -- the current default Extended Kalman Filter core (position/velocity/attitude estimator fusing GPS, IMU, compass, baro).",
    "EKF": "Extended Kalman Filter -- the estimator that fuses GPS, IMU, compass, and barometer into a position/velocity/attitude estimate.",
    "FENCE": "Geofence -- boundary the vehicle isn't supposed to cross.",
    "FLTMODE": "Flight mode switch assignment (see the Setup Wizard's Flight Modes step).",
    "FRAME": "Vehicle frame class/type (see the Setup Wizard's Frame Class step).",
    "FS": "Failsafe behavior (see the Setup Wizard's Failsafe step).",
    "GPS": "GPS receiver settings.",
    "GUID": "Guided mode behavior.",
    "INS": "Inertial Sensor -- accelerometers and gyros.",
    "LAND": "Landing behavior.",
    "LOG": "Onboard dataflash logging.",
    "LOIT": "Loiter mode tuning.",
    "MNT": "Camera mount / gimbal.",
    "MOT": "Motor output and mixing.",
    "NTF": "Notify -- LEDs and buzzer.",
    "OSD": "On-screen display (FPV video overlay).",
    "PSC": "Position/velocity controller tuning (used by Loiter, Auto, RTL, etc).",
    "RALLY": "Rally points (alternate return-to-launch locations).",
    "RC": "Radio control input channel settings.",
    "RCMAP": "Which physical RC channel controls which axis (roll/pitch/throttle/yaw).",
    "RNGFND": "Rangefinder -- a distance sensor (lidar/sonar/radar).",
    "RSSI": "Radio signal strength indicator input.",
    "RTL": "Return-to-Launch behavior.",
    "SCHED": "Task scheduler / loop timing -- advanced/developer tuning, rarely touched.",
    "SCR": "Lua scripting.",
    "SERIAL": "Serial ports (UARTs) -- used for telemetry radios, GPS, companion computers, etc.",
    "SERVO": "A specific output channel's function/range (which physical output does what).",
    "SIM": "Simulation-only (SITL) settings -- not used on real hardware.",
    "TELEM": "Telemetry radio link.",
    "TERRAIN": "Terrain-following elevation data.",
    "VISO": "Visual odometry -- a non-GPS, camera-based position source.",
    "WP": "Waypoint handling.",
    "WPNAV": "Waypoint navigation tuning (speed/acceleration used in Auto/Guided).",
    "WVANE": "Weathervaning -- turning the nose into the wind when loitering.",
}


def decode_param_name(name: str) -> str:
    """Translate a parameter name's subsystem prefix into plain English,
    e.g. "RNGFND1_GNDCLEAR" -> "RNGFND = Rangefinder -- a distance sensor...".
    Matches the longest known prefix first (so RCMAP isn't mistaken for
    RC), and tolerates an instance number between the prefix and the
    underscore (RNGFND1_..., BATT2_..., SERIAL0_...).
    """
    import re
    upper = name.strip().upper()
    for prefix in sorted(PREFIX_GLOSSARY, key=len, reverse=True):
        if re.match(rf"^{re.escape(prefix)}\d*(_|$)", upper):
            return f"{prefix} = {PREFIX_GLOSSARY[prefix]}"
    return ""
