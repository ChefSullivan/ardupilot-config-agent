"""
Curated presets for failsafe behavior and arming checks, grouped by what
the vehicle is being used for right now. These are sensible starting
points based on the tradeoffs ArduPilot's own docs describe -- not a
substitute for the user reviewing/adjusting the individual checkboxes
after picking one, especially for the Autonomous preset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set

from .arming_checks import NEVER_RECOMMEND_DISABLING
from .failsafe import FailsafeIntent


@dataclass
class FailsafePreset:
    label: str
    description: str
    intent_kwargs: dict


FAILSAFE_PRESETS: Dict[str, FailsafePreset] = {
    "testing": FailsafePreset(
        label="Bench / Ground Testing",
        description=(
            "Props off or the vehicle is restrained -- not actually flying missions. Nothing "
            "here is set to “keep going” on link loss, since there's no autonomous "
            "flight for a failsafe to continue."
        ),
        intent_kwargs=dict(
            continue_auto_mission_on_radio_loss=False, continue_auto_mission_on_gcs_loss=False,
            continue_guided_on_radio_loss=False, continue_landing_on_any_failsafe=True,
            continue_pilot_control_on_gcs_loss=False, release_gripper_on_failsafe=False,
            fs_gcs_enable_value=1,
        ),
    ),
    "manual": FailsafePreset(
        label="Manual / Sport Flying (line-of-sight, no missions)",
        description=(
            "You're always holding the sticks. On radio loss, the safest default is to come "
            "home (RTL) rather than keep flying blind -- nothing here continues on its own."
        ),
        intent_kwargs=dict(
            continue_auto_mission_on_radio_loss=False, continue_auto_mission_on_gcs_loss=False,
            continue_guided_on_radio_loss=False, continue_landing_on_any_failsafe=True,
            continue_pilot_control_on_gcs_loss=False, release_gripper_on_failsafe=False,
            fs_gcs_enable_value=1,
        ),
    ),
    "semi_auto": FailsafePreset(
        label="Semi-Autonomous (assisted missions, GCS usually connected)",
        description=(
            "Runs Auto/Guided missions with a GCS link most of the time. If only the GCS/"
            "telemetry link drops but RC is still fine, it's reasonable to keep flying the "
            "mission -- but losing the RC link (the pilot's own control) still triggers RTL, "
            "since that's a more serious loss of control authority."
        ),
        intent_kwargs=dict(
            continue_auto_mission_on_radio_loss=False, continue_auto_mission_on_gcs_loss=True,
            continue_guided_on_radio_loss=False, continue_landing_on_any_failsafe=True,
            continue_pilot_control_on_gcs_loss=True, release_gripper_on_failsafe=False,
            fs_gcs_enable_value=1,
        ),
    ),
    "autonomous": FailsafePreset(
        label="Full Autonomous Mission (no pilot standing by with a live link)",
        description=(
            "The mission is expected to complete even if links drop -- this is the most "
            "permissive preset and assumes you've deliberately decided the mission should "
            "finish rather than abort. Only choose this if you understand and accept that "
            "tradeoff for your specific mission."
        ),
        intent_kwargs=dict(
            continue_auto_mission_on_radio_loss=True, continue_auto_mission_on_gcs_loss=True,
            continue_guided_on_radio_loss=True, continue_landing_on_any_failsafe=True,
            continue_pilot_control_on_gcs_loss=True, release_gripper_on_failsafe=False,
            fs_gcs_enable_value=1,
        ),
    ),
}


def build_intent(preset_key: str) -> FailsafeIntent:
    return FailsafeIntent(**FAILSAFE_PRESETS[preset_key].intent_kwargs)


@dataclass
class ArmingPreset:
    label: str
    description: str
    enabled: Set[str] = field(default_factory=set)


ARMING_PRESETS: Dict[str, ArmingPreset] = {
    "bench": ArmingPreset(
        label="Bench / Indoor Testing (no GPS, no props / restrained)",
        description=(
            "Keeps the checks that catch a genuinely broken/misconfigured vehicle (RC, board "
            "voltage, system, parameters, INS) but drops GPS-related checks so you can arm "
            "indoors or on the bench without a GPS lock."
        ),
        enabled={"RC Channels", "Board voltage", "System", "Parameters", "INS", "Compass",
                 "Barometer", "Hardware safety switch"},
    ),
    "manual_outdoor": ArmingPreset(
        label="Manual / Sport Flying Outdoors",
        description=(
            "Standard recommended set for line-of-sight flying: every check ArduPilot enables "
            "by default, including GPS lock -- so RTL/Loiter will actually work if you need "
            "them mid-flight, even if you're mostly flying Stabilize/Acro."
        ),
        enabled={"All"},
    ),
    "autonomous": ArmingPreset(
        label="Autonomous / Mission Flying",
        description=(
            "Strictest set -- every check enabled. This is the profile where GPS Configuration "
            "and Mission checks matter most, since the vehicle will navigate and act on its own."
        ),
        enabled={"All"},
    ),
    "none": ArmingPreset(
        label="No Checks (arm-anywhere -- bench testing only)",
        description=(
            "Disables every arming check, including the ones normally never recommended to "
            "disable (RC Channels, Board voltage, System, Parameters, INS). This is for cases "
            "like arming from a script with no RC bound yet, or bench-testing motors with "
            "nothing else connected. Do not fly like this -- re-enable the standard checks "
            "before any real flight."
        ),
        enabled=set(),
    ),
}


# -- Vehicle Profile: one answer on the Welcome step, used to pre-fill both
# the Failsafe and Arming Checks presets downstream, and to drive the
# one-click "Apply Recommended Now" shortcut. Keys match FAILSAFE_PRESETS
# directly; PROFILE_TO_ARMING_PRESET maps the same profile to the arming
# preset that best fits it (not always a 1:1 name match).

# Short labels for the Welcome-step dropdown -- the full FAILSAFE_PRESETS
# labels/descriptions are shown separately once a profile is picked, since
# they're too long to render inside a combobox without truncating.
PROFILE_OPTIONS = [
    ("testing", "Bench / Ground Testing"),
    ("manual", "Manual / Sport Flying"),
    ("semi_auto", "Semi-Autonomous"),
    ("autonomous", "Full Autonomous Mission"),
]

PROFILE_TO_ARMING_PRESET = {
    "testing": "bench",
    "manual": "manual_outdoor",
    "semi_auto": "autonomous",
    "autonomous": "autonomous",
}
