"""
Failsafe composition helper.

FS_GCS_ENABLE / FS_THR_ENABLE set the DEFAULT failsafe action. FS_OPTIONS is
a separate bitmask that determines whether an autonomous mission actually
survives a link loss. "Continue the mission regardless of link" and "return
home on link loss" are NOT the same setting and must be composed correctly
together -- get explicit user intent on both axes before writing anything.

Bit values below verified live against
https://ardupilot.org/copter/docs/gcs-failsafe.html (Copter 4.0+, fetched
directly rather than trusted from memory):

  bit 0: Continue if in auto mode on Radio Failsafe
  bit 1: Continue if in auto mode on GCS Failsafe
  bit 2: Continue if in guided mode on Radio Failsafe
  bit 3: Continue if landing, on any failsafe
  bit 4: Continue in pilot control on GCS Failsafe
  bit 5: Release gripper during failsafe handling

Only bits 0, 2, 3, 5 affect Radio failsafe behavior.
Only bits 1, 3, 4, 5 affect GCS failsafe behavior.

FS_GCS_ENABLE value 2 ("Enabled Continue with Mission in Auto Mode") was
REMOVED as a functioning value in Copter 4.0+ and replaced by FS_OPTIONS
bit 1. Setting FS_GCS_ENABLE=2 on 4.0+ firmware gets silently auto-converted
to 1 (Always RTL) plus FS_OPTIONS bit 1 set. Do not assume FS_GCS_ENABLE=2
still means "continue mission" -- this is exactly the kind of stale-enum
trap this toolkit exists to avoid. Always re-verify against the live
firmware's parameter metadata/docs for the version in use.
"""
from __future__ import annotations

from dataclasses import dataclass

from .connection import FCConnection
from .params import set_param

BIT_CONTINUE_AUTO_ON_RADIO_FS = 0
BIT_CONTINUE_AUTO_ON_GCS_FS = 1
BIT_CONTINUE_GUIDED_ON_RADIO_FS = 2
BIT_CONTINUE_LANDING_ON_ANY_FS = 3
BIT_CONTINUE_PILOT_CONTROL_ON_GCS_FS = 4
BIT_RELEASE_GRIPPER_ON_FS = 5

FS_GCS_ENABLE_VALUES = {
    0: "Disabled",
    1: "Enabled Always RTL",
    2: "REMOVED in Copter 4.0+ (auto-converted to 1 + FS_OPTIONS bit1) -- do not set on 4.0+",
    3: "Enabled SmartRTL or RTL",
    4: "Enabled SmartRTL or Land",
    5: "Enabled Always Land",
    6: "Auto DO_LAND_START or RTL",
    7: "BRAKE or LAND",
}


@dataclass
class FailsafeIntent:
    """Explicit, unambiguous statement of what the user wants. Fill every
    field from an actual conversation with the user -- do not guess or
    default silently on anything safety-relevant.
    """
    continue_auto_mission_on_radio_loss: bool
    continue_auto_mission_on_gcs_loss: bool
    continue_guided_on_radio_loss: bool = False
    continue_landing_on_any_failsafe: bool = True  # sane default: don't abort an active landing
    continue_pilot_control_on_gcs_loss: bool = False
    release_gripper_on_failsafe: bool = False
    fs_gcs_enable_value: int = 1  # default action when no "continue" bit applies: Always RTL


def compute_fs_options(intent: FailsafeIntent) -> int:
    """Compose the FS_OPTIONS bitmask from explicit intent."""
    value = 0
    if intent.continue_auto_mission_on_radio_loss:
        value |= 1 << BIT_CONTINUE_AUTO_ON_RADIO_FS
    if intent.continue_auto_mission_on_gcs_loss:
        value |= 1 << BIT_CONTINUE_AUTO_ON_GCS_FS
    if intent.continue_guided_on_radio_loss:
        value |= 1 << BIT_CONTINUE_GUIDED_ON_RADIO_FS
    if intent.continue_landing_on_any_failsafe:
        value |= 1 << BIT_CONTINUE_LANDING_ON_ANY_FS
    if intent.continue_pilot_control_on_gcs_loss:
        value |= 1 << BIT_CONTINUE_PILOT_CONTROL_ON_GCS_FS
    if intent.release_gripper_on_failsafe:
        value |= 1 << BIT_RELEASE_GRIPPER_ON_FS
    return value


def describe_fs_options(value: int) -> str:
    bits = {
        BIT_CONTINUE_AUTO_ON_RADIO_FS: "continue auto mission on RADIO failsafe",
        BIT_CONTINUE_AUTO_ON_GCS_FS: "continue auto mission on GCS failsafe",
        BIT_CONTINUE_GUIDED_ON_RADIO_FS: "continue guided mode on RADIO failsafe",
        BIT_CONTINUE_LANDING_ON_ANY_FS: "continue landing on any failsafe",
        BIT_CONTINUE_PILOT_CONTROL_ON_GCS_FS: "continue pilot control on GCS failsafe",
        BIT_RELEASE_GRIPPER_ON_FS: "release gripper on failsafe",
    }
    active = [desc for bit, desc in bits.items() if value & (1 << bit)]
    return f"FS_OPTIONS={value} (0b{value:06b}): " + ("; ".join(active) if active else "no bits set")


def apply_failsafe_intent(conn: FCConnection, intent: FailsafeIntent, fs_thr_enable_value: int = 1) -> None:
    """Write FS_OPTIONS, FS_GCS_ENABLE, and FS_THR_ENABLE together so the
    composed behavior is applied atomically rather than left half-configured.
    """
    conn.require_disarmed()
    fs_options = compute_fs_options(intent)
    set_param(conn, "FS_OPTIONS", fs_options)
    set_param(conn, "FS_GCS_ENABLE", intent.fs_gcs_enable_value)
    set_param(conn, "FS_THR_ENABLE", fs_thr_enable_value)
    print(describe_fs_options(fs_options))


# -- EKF / position (the modern "GPS failsafe") -----------------------------
#
# The dedicated "GPS failsafe" mechanism referenced in old ArduPilot docs is
# now archived (https://ardupilot.org/copter/docs/archived-gps-failsafe.html).
# Its modern equivalent is the EKF failsafe, verified against
# https://ardupilot.org/copter/docs/ekf-inav-failsafe.html : it monitors the
# EKF's confidence in position/velocity/compass (not just raw GPS lock) and
# reacts the same way a lost-GPS event would in GPS-dependent modes.

EKF_ACTION_VALUES = {
    0: "Report only (no mode change)",
    1: "Land (default) -- pilot-controlled descent, then disarm",
    2: "AltHold (hover in place)",
    3: "Land, even if currently in Stabilize",
}

# FS_EKF_THRESH is a continuous 0-1 value but ArduPilot's own docs only
# describe these specific waypoints -- treated as a preset dropdown rather
# than a free-form number so the meaning stays attached to the value.
EKF_THRESH_PRESETS = {
    0.0: "Disabled (EKF failsafe never triggers)",
    0.6: "Strict (triggers sooner, more false positives during aggressive flying)",
    0.8: "Default (recommended starting point)",
    1.0: "Relaxed (triggers later -- vehicle flies further before LAND kicks in)",
}


def apply_ekf_failsafe(conn: FCConnection, action_value: int, thresh_value: float) -> None:
    """Write FS_EKF_ACTION and FS_EKF_THRESH together. Applies live, no
    reboot needed -- still routed through require_disarmed() as defense in
    depth since this affects in-flight failsafe behavior.
    """
    conn.require_disarmed()
    set_param(conn, "FS_EKF_ACTION", action_value)
    set_param(conn, "FS_EKF_THRESH", thresh_value)
    print(f"FS_EKF_ACTION={action_value} ({EKF_ACTION_VALUES.get(action_value, 'unknown')}), "
          f"FS_EKF_THRESH={thresh_value}")
