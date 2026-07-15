"""
RC (transmitter) calibration: capturing each input channel's min/max/trim so
ArduPilot can correctly interpret stick, switch, and knob positions.

Verified against https://ardupilot.org/copter/docs/common-radio-control-calibration.html
and https://ardupilot.org/copter/docs/common-rcmap.html :

- Default channel mapping is Roll=1, Pitch=2, Throttle=3, Yaw=4, Flight
  modes=5, tuning knob=6, aux functions=7-12 -- but this is only the
  DEFAULT. The actual mapping for roll/pitch/throttle/yaw is controlled by
  RCMAP_ROLL/RCMAP_PITCH/RCMAP_THROTTLE/RCMAP_YAW and can be remapped.
  Always read these live rather than assuming channel 1 is roll.
- Safety note directly from the docs: "Ensure the battery is disconnected
  -- it is possible to accidentally arm the vehicle during the RC
  calibration process." This toolkit's USB-only connection model already
  keeps the battery out of the loop, but the require_disarmed() gate below
  is kept as defense in depth regardless.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from pymavlink import mavutil

from .connection import FCConnection
from .params import get_param, set_param

DEFAULT_ROLES = {
    1: "Roll (default)",
    2: "Pitch (default)",
    3: "Throttle (default)",
    4: "Yaw (default)",
    5: "Flight mode switch (default, see FLTMODE_CH)",
    6: "Tuning knob (optional)",
}


def request_rc_channels_stream(conn: FCConnection, rate_hz: float = 10.0) -> None:
    conn.master.mav.command_long_send(
        conn.master.target_system,
        conn.master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS,
        int(1e6 / rate_hz),
        0, 0, 0, 0, 0,
    )


def read_rc_channels(conn: FCConnection, timeout: float = 1.0) -> Dict[int, int]:
    """One snapshot of {channel: pwm} from the RC_CHANNELS message."""
    msg = conn.master.recv_match(type="RC_CHANNELS", blocking=True, timeout=timeout)
    if msg is None:
        return {}
    count = getattr(msg, "chancount", 8)
    out = {}
    for ch in range(1, min(count, 18) + 1):
        field = f"chan{ch}_raw"
        if hasattr(msg, field):
            val = getattr(msg, field)
            if val not in (0, 65535):  # 0/UINT16_MAX mean "not available" per MAVLink spec
                out[ch] = val
    return out


def get_rcmap(conn: FCConnection) -> Dict[str, int]:
    """Read RCMAP_ROLL/PITCH/THROTTLE/YAW live. Never assume channels 1-4 --
    remapping is common and these parameters are the only source of truth.
    """
    roles = {}
    for role, param_name in [("roll", "RCMAP_ROLL"), ("pitch", "RCMAP_PITCH"),
                              ("throttle", "RCMAP_THROTTLE"), ("yaw", "RCMAP_YAW")]:
        try:
            roles[role] = int(get_param(conn, param_name))
        except TimeoutError:
            print(f"WARNING: could not read {param_name} -- RCMAP parameter may not exist on this firmware.")
    return roles


def capture_center(conn: FCConnection, timeout: float = 2.0) -> Dict[int, int]:
    """Snapshot RC channels once, intended to be called while the pilot has
    all sticks centered and throttle at minimum (mirrors the Mission
    Planner flow: this becomes the RCx_TRIM baseline).
    """
    return read_rc_channels(conn, timeout=timeout)


def capture_ranges(
    conn: FCConnection,
    duration_s: float = 20.0,
    on_sample: Optional[Callable[[Dict[int, int], Dict[int, int], Dict[int, int]], None]] = None,
) -> Dict[int, Tuple[int, int]]:
    """Live-capture mode: sample RC_CHANNELS for duration_s while the pilot
    moves every stick, switch, and knob to its extremes. Returns
    {channel: (min, max)}. `on_sample(latest, running_min, running_max)` is
    called after each sample if provided, so a GUI can show live bars.
    """
    request_rc_channels_stream(conn)
    running_min: Dict[int, int] = {}
    running_max: Dict[int, int] = {}
    deadline = time.time() + duration_s
    while time.time() < deadline:
        sample = read_rc_channels(conn, timeout=0.5)
        for ch, pwm in sample.items():
            running_min[ch] = min(running_min.get(ch, pwm), pwm)
            running_max[ch] = max(running_max.get(ch, pwm), pwm)
        if on_sample and sample:
            on_sample(sample, dict(running_min), dict(running_max))
    return {ch: (running_min[ch], running_max[ch]) for ch in running_min}


@dataclass
class RCChannelCal:
    channel: int
    pwm_min: int
    pwm_max: int
    pwm_trim: int
    reversed: bool = False


def apply_calibration(conn: FCConnection, cal: RCChannelCal, verify: bool = True) -> None:
    """Write RCx_MIN/MAX/TRIM/REVERSED for one channel. These apply live,
    no reboot required, but we still route through require_disarmed() as
    defense in depth since RC input directly drives control surfaces.
    """
    conn.require_disarmed()
    prefix = f"RC{cal.channel}"
    set_param(conn, f"{prefix}_MIN", cal.pwm_min, verify=verify)
    set_param(conn, f"{prefix}_MAX", cal.pwm_max, verify=verify)
    set_param(conn, f"{prefix}_TRIM", cal.pwm_trim, verify=verify)
    set_param(conn, f"{prefix}_REVERSED", 1 if cal.reversed else 0, verify=verify)


def quick_apply(conn: FCConnection, cals: List[RCChannelCal]) -> None:
    """Apply known min/max/trim values directly for every channel in one
    pass, skipping the live move-the-sticks capture step entirely. This is
    the "just give it the limits and let it run" mode -- useful when you
    already know your transmitter's endpoints (e.g. from a previous
    calibration or the radio's own display) and don't need the guided
    capture.
    """
    for cal in cals:
        apply_calibration(conn, cal)
    print(f"Applied quick RC calibration for {len(cals)} channel(s).")


def set_rcmap(
    conn: FCConnection,
    roll: "Optional[int]" = None,
    pitch: "Optional[int]" = None,
    throttle: "Optional[int]" = None,
    yaw: "Optional[int]" = None,
) -> None:
    """Write RCMAP_ROLL/PITCH/THROTTLE/YAW for whichever roles are given
    (None = leave unchanged). Per the docs, these should apply live but a
    reboot is the safest way to guarantee ArduPilot has picked up a channel
    remap -- callers doing an interactive reassignment should prompt for one.
    """
    conn.require_disarmed()
    role_to_value = {"RCMAP_ROLL": roll, "RCMAP_PITCH": pitch, "RCMAP_THROTTLE": throttle, "RCMAP_YAW": yaw}
    for param_name, value in role_to_value.items():
        if value is not None:
            set_param(conn, param_name, value)
