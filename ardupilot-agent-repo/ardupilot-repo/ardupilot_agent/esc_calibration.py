"""
ESC calibration guidance, verified against
https://ardupilot.org/copter/docs/esc-calibration.html and
https://ardupilot.org/copter/docs/common-brushless-escs.html .

This cannot be fully automated over a USB/MAVLink connection: the
documented procedure requires disconnecting USB and power-cycling the
LiPo battery, which necessarily drops our connection. What this module
*can* do is: (1) tell you whether your ESC protocol needs calibration at
all, (2) drive the semi-automatic method by setting ESC_CALIBRATION=3 over
MAVLink before you power-cycle, and (3) verify the result once you
reconnect. The rest is a checklist for the human.

Key facts from the docs:
- DShot, other digital protocols, and CAN ESCs do NOT need calibration --
  skip this entirely if MOT_PWM_TYPE is set to one of those.
  MOT_PWM_TYPE values verified from common-brushless-escs.html:
  0 = Normal (PWM), 1 = OneShot, 2 = OneShot125 -- all three of these DO
  need calibration. Any other value is a digital/DShot-family protocol and
  does NOT need calibration (exact DShot sub-values weren't individually
  re-verified here, but the 0/1/2 boundary is confirmed from the docs).
- "All at once" calibration: throttle to max, connect battery, LEDs cycle,
  disconnect/reconnect battery with throttle still high, wait for the
  musical tone + cell-count beeps + two beeps (max captured), then pull
  throttle to minimum for the long tone (min captured, done).
- Semi-automatic: set ESC_CALIBRATION=3 via MAVLink, power down (USB +
  battery), reconnect ONLY the battery, wait for the same tone sequence,
  then power down and reconnect normally.
- ALWAYS complete radio calibration before ESC calibration.
- Safety: props OFF, and per the docs, USB should be disconnected during
  the all-at-once/manual methods (autopilot runs on battery only).
"""
from __future__ import annotations

from .connection import FCConnection
from .params import get_param, set_param

# MOT_PWM_TYPE values that require ESC calibration (verified: 0/1/2 are the
# analog-timing protocols; everything else is digital/DShot and skips
# calibration entirely per the docs).
PWM_TYPES_NEEDING_CALIBRATION = {0, 1, 2}

ESC_CALIBRATION_SEMI_AUTO_VALUE = 3  # verified: "set ESC_CALIBRATION parameter to 3"

ALL_AT_ONCE_STEPS = [
    "Remove propellers. This step is mandatory.",
    "Disconnect USB from the autopilot (all-at-once calibration runs on battery power only).",
    "Turn on the transmitter and raise the throttle stick to maximum.",
    "Connect the LiPo battery. The autopilot's LEDs will cycle red/blue/yellow.",
    "With throttle still at maximum, disconnect and reconnect the battery.",
    "If your autopilot has a safety switch, press it until it shows solid red.",
    "Wait for a musical tone, then beeps equal to your battery's cell count, then two beeps "
    "(maximum throttle captured).",
    "Pull the throttle stick down to minimum.",
    "Wait for a single long tone (minimum captured, calibration complete).",
    "Raise the throttle slightly to confirm all motors spin together at the same speed, then "
    "lower it back to zero.",
    "Disconnect the battery to exit ESC-calibration mode.",
]

SEMI_AUTOMATIC_STEPS_BEFORE_POWER_CYCLE = [
    "Complete radio calibration first if you haven't already.",
    "Confirm MOT_PWM_TYPE is 0 (Normal), 1 (OneShot), or 2 (OneShot125) -- this toolkit will "
    "check that for you before starting.",
    "With the autopilot connected over USB, this toolkit will set ESC_CALIBRATION=3.",
]

SEMI_AUTOMATIC_STEPS_AFTER_POWER_CYCLE = [
    "Disconnect both the USB cable and the battery so the autopilot fully powers down.",
    "Connect ONLY the battery (leave USB disconnected).",
    "If your autopilot has a safety switch, press it until it shows solid red.",
    "Wait for the musical tone, then cell-count beeps, then a single long tone (calibration complete).",
    "Disconnect the battery, then reconnect USB to this toolkit to verify.",
]


def needs_calibration(conn: FCConnection) -> bool:
    """Read MOT_PWM_TYPE live and report whether ESC calibration applies at
    all. DShot/digital/CAN ESCs should skip this procedure entirely.
    """
    pwm_type = int(get_param(conn, "MOT_PWM_TYPE"))
    return pwm_type in PWM_TYPES_NEEDING_CALIBRATION


def start_semi_automatic(conn: FCConnection) -> None:
    """Set ESC_CALIBRATION=3 so the next power-up (battery only, no USB)
    enters calibration mode. Requires the vehicle to be disarmed, though in
    practice it should already be un-armable with no battery connected yet.
    """
    conn.require_disarmed()
    set_param(conn, "ESC_CALIBRATION", ESC_CALIBRATION_SEMI_AUTO_VALUE)
    print(
        "ESC_CALIBRATION set to 3. Now: disconnect USB + battery, reconnect ONLY the battery, "
        "and follow the tone sequence. Reconnect USB afterward to verify."
    )


def verify_calibration_flag_cleared(conn: FCConnection) -> bool:
    """ArduPilot resets ESC_CALIBRATION back to 0 once calibration mode has
    been entered and exited. A 0 reading here is a supporting signal that
    the cycle happened -- combine with the human confirming they heard the
    completion tone, don't rely on this alone.
    """
    return int(get_param(conn, "ESC_CALIBRATION")) == 0
