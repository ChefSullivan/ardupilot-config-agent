"""
Vehicle type + frame class/type human-readable labels.

FRAME_CLASS/FRAME_TYPE numeric meanings verified against
https://ardupilot.org/copter/docs/frame-type-configuration.html and the
ArduCopter FRAME_CLASS/FRAME_TYPE parameter metadata, cross-checked via two
independent lookups (direct GitHub source fetches timed out in this
environment, so this was verified via two separate searches instead of one
single source -- flagged here rather than silently trusted). Values 0-9
(the common frames: Quad/Hexa/Octa/OctaQuad/Y6/Heli/Tri/SingleCopter/
CoaxCopter) were consistent across both lookups. Values 10+ had one
disagreement (Tailsitter vs BiCopter for 10) -- shown with a caveat rather
than asserted confidently. Always cross-check the Parameters tab / your
firmware's own metadata for anything beyond the common 0-9 range, or
before making a real decision based on an uncommon value.

MAV_TYPE (top-level vehicle firmware family: Copter/Plane/Rover/etc.) comes
straight from pymavlink's own enum table (mavutil.mavlink.enums['MAV_TYPE']),
not hand-maintained here -- that's the one live, always-correct source for
that particular enum.
"""
from __future__ import annotations

from typing import Optional

from pymavlink import mavutil

from .connection import FCConnection

FRAME_CLASS_NAMES = {
    0: "Undefined",
    1: "Quad",
    2: "Hexa",
    3: "Octa",
    4: "OctaQuad",
    5: "Y6",
    6: "Heli",
    7: "Tri",
    8: "SingleCopter",
    9: "CoaxCopter",
    10: "Tailsitter or BiCopter (sources disagree -- verify)",
    11: "Heli_Dual",
    12: "DodecaHexa",
    13: "HeliQuad",
    14: "Deca",
    15: "Scripting Matrix",
}

FRAME_TYPE_NAMES = {
    0: "Plus",
    1: "X",
    2: "V",
    3: "H",
    4: "V-Tail",
    5: "A-Tail",
    10: "Y6B",
    11: "Y6F",
    12: "BetaFlightX",
    13: "DJIX",
    14: "ClockwiseX",
    15: "I",
    18: "BetaFlightXReversed",
}


def describe_frame_class(value) -> str:
    v = int(value)
    name = FRAME_CLASS_NAMES.get(v)
    return f"{v} ({name})" if name else f"{v} (uncommon/unrecognized -- check the Parameters tab metadata)"


def describe_frame_type(value) -> str:
    v = int(value)
    name = FRAME_TYPE_NAMES.get(v)
    return f"{v} ({name})" if name else f"{v} (uncommon/unrecognized -- check the Parameters tab metadata)"


def get_vehicle_type_name(conn: FCConnection, timeout: float = 3.0) -> Optional[str]:
    """Read the most recent HEARTBEAT and translate its MAV_TYPE field to a
    human name via pymavlink's own enum table -- e.g. "Quadrotor", "Fixed
    Wing", "Ground Rover". Returns None if no heartbeat is available yet
    (harmless -- caller should just skip the label rather than guess).
    """
    hb = conn.master.recv_match(type="HEARTBEAT", blocking=True, timeout=timeout)
    if hb is None:
        return None
    entry = mavutil.mavlink.enums.get("MAV_TYPE", {}).get(hb.type)
    if entry is None:
        return f"MAV_TYPE={hb.type} (unrecognized)"
    name = entry.name
    if name.startswith("MAV_TYPE_"):
        name = name[len("MAV_TYPE_"):]
    return name.replace("_", " ").title()


def apply_frame_class_and_type(conn: FCConnection, frame_class: int, frame_type: int) -> None:
    """Write FRAME_CLASS and FRAME_TYPE together with a single reboot +
    verify, rather than the two separate reboots that calling
    set_param_and_verify_after_reboot for each individually would cause.
    Mirrors the multi-param + one-reboot pattern in
    motor_test.apply_servo_function_fixes.
    """
    from .params import get_param, set_param

    conn.require_disarmed()
    set_param(conn, "FRAME_CLASS", frame_class)
    set_param(conn, "FRAME_TYPE", frame_type)
    conn.reboot_and_wait()
    after_class = get_param(conn, "FRAME_CLASS")
    after_type = get_param(conn, "FRAME_TYPE")
    if int(after_class) != frame_class or int(after_type) != frame_type:
        raise RuntimeError(
            f"FRAME_CLASS/FRAME_TYPE did not survive reboot: expected "
            f"({frame_class}, {frame_type}), FC reports ({int(after_class)}, {int(after_type)})."
        )
    print(f"FRAME_CLASS={int(after_class)} ({describe_frame_class(after_class)}), "
          f"FRAME_TYPE={int(after_type)} ({describe_frame_type(after_type)}) confirmed after reboot.")
