"""
Motor-order diagnosis subroutine.

The reliable method (established the hard way -- Mission Planner's Motor
Test A/B/C/D buttons do NOT map to a fixed output channel; they follow
ArduPilot's internal per-frame-type test-order sequence, e.g. BetaFlightX's
order visits Motor1, then Motor4, then Motor2, then Motor3, not 1-2-3-4 in
raw order. Physical position descriptions like "front-left" are also
viewer-orientation-dependent and easy to get inconsistent across sessions):

  1. Command each motor instance individually via MAV_CMD_DO_MOTOR_TEST.
  2. Watch SERVO_OUTPUT_RAW during the test to see which numbered output
     channel's PWM actually changed. This gives the true instance->channel
     mapping empirically, independent of GCS UI semantics or memorized
     test-order tables.
  3. Ask the user which physical corner spun for that specific, isolated
     test (one motor at a time, never a batch).
  4. Combine instance->channel (telemetry) with channel->corner (user
     report) into a verified wiring table.
  5. Compare against the frame type's expected corner->motor-number mapping
     (see frame_reference.py) to compute the required SERVOx_FUNCTION fix.
  6. Push the fix, reboot, and re-run the same per-instance test to confirm
     -- don't just trust the parameter write.
  7. Rotation direction (CW/CCW) is a separate check: SERVOx_FUNCTION only
     fixes which corner responds to which mixer input, not which way the
     motor spins. That's fixed by swapping 2 of 3 motor/ESC wires.

Always test at >=15-20% throttle. Below ~10% is often under MOT_SPIN_MIN
and a working motor won't spin at all -- a common false alarm that looks
like a wiring problem but isn't.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from pymavlink import mavutil

from .connection import FCConnection
from .params import get_param, set_param

MOTOR_TEST_THROTTLE_PERCENT = 0  # MOTOR_TEST_THROTTLE_TYPE enum value for "percent"

# SERVOx_FUNCTION enum values for Motor1..Motor8, verified against
# https://ardupilot.org/copter/docs/common-rcoutput-mapping.html
MOTOR_FUNCTION_BASE = 33  # Motor1=33, Motor2=34, ... Motor8=40


def motor_function_value(motor_number: int) -> int:
    """SERVOx_FUNCTION value for MotorN (1-indexed, 1-8)."""
    if not 1 <= motor_number <= 8:
        raise ValueError("motor_number must be 1-8")
    return MOTOR_FUNCTION_BASE + (motor_number - 1)


@dataclass
class ChannelSample:
    channel: int
    baseline_pwm: int
    peak_pwm: int

    @property
    def delta(self) -> int:
        return self.peak_pwm - self.baseline_pwm


def request_servo_output_stream(conn: FCConnection, rate_hz: float = 10.0) -> None:
    """Ask the FC to stream SERVO_OUTPUT_RAW at a useful rate via
    MAV_CMD_SET_MESSAGE_INTERVAL, so motor tests can be watched in
    near-real-time.
    """
    conn.master.mav.command_long_send(
        conn.master.target_system,
        conn.master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW,
        int(1e6 / rate_hz),
        0, 0, 0, 0, 0,
    )


def _read_servo_output_raw(conn: FCConnection, timeout: float = 0.5) -> Optional[Dict[int, int]]:
    msg = conn.master.recv_match(type="SERVO_OUTPUT_RAW", blocking=True, timeout=timeout)
    if msg is None:
        return None
    out = {}
    for ch in range(1, 17):
        field_name = f"servo{ch}_raw"
        if hasattr(msg, field_name):
            out[ch] = getattr(msg, field_name)
    return out


def test_single_motor(
    conn: FCConnection,
    instance: int,
    throttle_pct: int = 20,
    duration_s: int = 2,
) -> None:
    """Send MAV_CMD_DO_MOTOR_TEST for exactly one motor instance.

    param1 = instance (1-indexed)
    param2 = MOTOR_TEST_THROTTLE_PERCENT (0)
    param3 = throttle_pct (use >=15-20; below ~10 is often masked by
             MOT_SPIN_MIN and a working motor won't spin)
    param4 = duration_s (timeout between sequential tests)
    param5 = motor count = 1 (test just this one motor, not a sequence)
    param6 = test order = 0 (irrelevant for a single-motor test)

    Verified against the MAVLink common.xml DO_MOTOR_TEST definition.
    """
    conn.require_disarmed()
    conn.master.mav.command_long_send(
        conn.master.target_system,
        conn.master.target_component,
        mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST,
        0,
        instance, MOTOR_TEST_THROTTLE_PERCENT, throttle_pct, duration_s, 1, 0, 0,
    )


def diagnose_one_instance(
    conn: FCConnection,
    instance: int,
    throttle_pct: int = 20,
    duration_s: int = 2,
    settle_s: float = 0.3,
) -> ChannelSample:
    """Run test_single_motor for one instance while sampling
    SERVO_OUTPUT_RAW, and return the channel whose PWM moved the most. This
    is the empirical instance->channel mapping -- trust this over any
    assumption about ArduPilot's internal test-order semantics.
    """
    baseline = _read_servo_output_raw(conn, timeout=1.0) or {}
    test_single_motor(conn, instance, throttle_pct=throttle_pct, duration_s=duration_s)

    peak: Dict[int, int] = dict(baseline)
    deadline = time.time() + duration_s + settle_s
    while time.time() < deadline:
        sample = _read_servo_output_raw(conn, timeout=0.3)
        if not sample:
            continue
        for ch, pwm in sample.items():
            if pwm > peak.get(ch, 0):
                peak[ch] = pwm

    best_channel, best_delta = None, -1
    for ch, peak_pwm in peak.items():
        base_pwm = baseline.get(ch, peak_pwm)
        delta = peak_pwm - base_pwm
        if delta > best_delta:
            best_channel, best_delta = ch, delta

    if best_channel is None or best_delta < 20:
        raise RuntimeError(
            f"No channel showed a clear PWM change for motor instance {instance}. "
            f"Increase throttle_pct (try 25-30) or check MOT_SPIN_MIN / wiring "
            f"before concluding the motor/ESC is dead."
        )
    return ChannelSample(channel=best_channel, baseline_pwm=baseline.get(best_channel, 0), peak_pwm=peak[best_channel])


@dataclass
class MotorMapEntry:
    instance: int
    channel: int
    corner: str  # user-reported physical position, e.g. "front-right"


def build_motor_map(
    conn: FCConnection,
    motor_count: int,
    ask_corner: Callable[[int, int], str],
    throttle_pct: int = 20,
    duration_s: int = 2,
) -> List[MotorMapEntry]:
    """Drive the full per-instance diagnosis loop. `ask_corner(instance,
    channel)` must isolate the motor spin for the human (already happened by
    the time it's called) and return their reported physical corner as a
    string, e.g. "front-right". Motors are tested one at a time, never
    batched, so the position report is unambiguous.
    """
    request_servo_output_stream(conn)
    entries: List[MotorMapEntry] = []
    for instance in range(1, motor_count + 1):
        sample = diagnose_one_instance(conn, instance, throttle_pct=throttle_pct, duration_s=duration_s)
        corner = ask_corner(instance, sample.channel)
        entries.append(MotorMapEntry(instance=instance, channel=sample.channel, corner=corner))
    return entries


def compute_servo_function_fixes(
    motor_map: List[MotorMapEntry],
    expected_corner_to_motor_number: Dict[str, int],
) -> Dict[int, int]:
    """Given the verified wiring table (channel -> physical corner it
    actually spins) and the frame type's expected corner -> motor-number
    mapping, compute {channel: required_SERVOx_FUNCTION_value} so each
    physical corner responds to the correct mixer input.

    IMPORTANT: expected_corner_to_motor_number must come from the live
    connect-escs-and-motors.html page for the vehicle's actual FRAME_CLASS/
    FRAME_TYPE -- do not trust a memorized table. See frame_reference.py.
    """
    fixes: Dict[int, int] = {}
    for entry in motor_map:
        motor_number = expected_corner_to_motor_number.get(entry.corner)
        if motor_number is None:
            raise KeyError(
                f"Corner '{entry.corner}' not found in expected mapping "
                f"{list(expected_corner_to_motor_number.keys())} -- check spelling/frame type."
            )
        fixes[entry.channel] = motor_function_value(motor_number)
    return fixes


def apply_servo_function_fixes(conn: FCConnection, fixes: Dict[int, int]) -> None:
    """Push all SERVOx_FUNCTION changes, then reboot once and verify each
    one survived (SERVOx_FUNCTION only fully applies after reboot). After
    this returns, re-run diagnose_one_instance per motor to physically
    confirm the fix, rather than trusting the parameter write alone.
    """
    conn.require_disarmed()
    for channel, function_value in fixes.items():
        set_param(conn, f"SERVO{channel}_FUNCTION", function_value)
    conn.reboot_and_wait()
    for channel, function_value in fixes.items():
        after = get_param(conn, f"SERVO{channel}_FUNCTION")
        if after != function_value:
            raise RuntimeError(
                f"SERVO{channel}_FUNCTION did not survive reboot: expected "
                f"{function_value}, FC reports {after}."
            )
    print("All SERVOx_FUNCTION fixes confirmed after reboot. Re-run the motor test per instance to confirm physically.")
