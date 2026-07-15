"""
Live parameter access with the read-modify-verify-reboot discipline.

The core lesson encoded here: never trust a remembered parameter name or
enum value. Real examples that bit a previous session: RNGFND1_GNDCLR
(wrong) vs. RNGFND1_GNDCLEAR (correct); assuming a global RNGFND_GNDCLEAR
when the parameter is actually per-instance; and FS_GCS_ENABLE=2 for
"continue mission," which was removed in Copter 4.0+ and replaced by an
FS_OPTIONS bit. Always pull the live parameter list from the FC and search
it, and always verify a SET by re-reading the value (including after a
reboot, for parameters that require one).
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from pymavlink import mavutil

from .connection import FCConnection


def fetch_all_params(conn: FCConnection, timeout: float = 20.0) -> Dict[str, float]:
    """Pull the full live parameter list via param_request_list + collecting
    PARAM_VALUE messages. This is the ground truth -- grep it for the
    parameter you want rather than guessing a name, and don't trust a doc
    page for a similarly-named board variant over what the FC itself reports.
    """
    conn.master.mav.param_request_list_send(conn.master.target_system, conn.master.target_component)
    params: Dict[str, float] = {}
    expected_count: Optional[int] = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.master.recv_match(type="PARAM_VALUE", blocking=True, timeout=1)
        if msg is None:
            continue
        name = msg.param_id.rstrip("\x00")
        params[name] = msg.param_value
        if expected_count is None:
            expected_count = msg.param_count
        if expected_count is not None and len(params) >= expected_count:
            break
    return params


def search_params(all_params: Dict[str, float], substring: str) -> Dict[str, float]:
    """Grep the live param dump for a substring instead of assuming a name
    from memory."""
    substring = substring.upper()
    return {k: v for k, v in all_params.items() if substring in k.upper()}


def get_param(conn: FCConnection, name: str, timeout: float = 5.0) -> float:
    """Read a single parameter's current live value directly from the FC."""
    conn.master.mav.param_request_read_send(
        conn.master.target_system, conn.master.target_component, name.encode("utf-8"), -1
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.master.recv_match(type="PARAM_VALUE", blocking=True, timeout=1)
        if msg is None:
            continue
        if msg.param_id.rstrip("\x00") == name:
            return msg.param_value
    raise TimeoutError(f"No PARAM_VALUE response for {name} within {timeout}s -- verify the name is correct.")


def set_param(
    conn: FCConnection,
    name: str,
    value: float,
    param_type: int = mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    verify: bool = True,
    timeout: float = 5.0,
) -> float:
    """Set a parameter and, by default, immediately re-read it to confirm
    the FC actually accepted the value (not just that the ACK was sent).
    Returns the confirmed live value. Does NOT gate on disarm by itself --
    wrap the call with conn.require_disarmed() when the parameter affects
    motor/servo/frame/serial behavior.
    """
    conn.master.mav.param_set_send(
        conn.master.target_system,
        conn.master.target_component,
        name.encode("utf-8"),
        float(value),
        param_type,
    )
    deadline = time.time() + timeout
    confirmed: Optional[float] = None
    while time.time() < deadline:
        msg = conn.master.recv_match(type="PARAM_VALUE", blocking=True, timeout=1)
        if msg is None:
            continue
        if msg.param_id.rstrip("\x00") == name:
            confirmed = msg.param_value
            break
    if confirmed is None:
        raise TimeoutError(f"No confirmation PARAM_VALUE for {name} within {timeout}s.")
    if verify and confirmed != value:
        print(
            f"WARNING: set {name}={value} but FC reports {confirmed}. "
            f"This can be legitimate float rounding, or it can mean the "
            f"value was rejected/clamped -- check the parameter's valid range."
        )
    return confirmed


def set_param_and_verify_after_reboot(
    conn: FCConnection,
    name: str,
    value: float,
    param_type: int = mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
) -> float:
    """The full pattern for parameters that only fully apply after reboot
    (FRAME_CLASS, SERIALx_PROTOCOL, MOT_PWM_TYPE, SERVOx_FUNCTION, ...):
    read current -> set -> verify ACK -> reboot -> re-read -> confirm it
    survived. Requires the vehicle to be disarmed (enforced inside
    reboot_and_wait).
    """
    before = get_param(conn, name)
    print(f"{name}: current value = {before}")
    set_param(conn, name, value, param_type=param_type)
    conn.reboot_and_wait()
    after = get_param(conn, name)
    if after != value:
        raise RuntimeError(
            f"{name} did not survive reboot: expected {value}, FC reports {after}. "
            f"Do not assume the change is live -- investigate before proceeding."
        )
    print(f"{name}: confirmed {after} after reboot.")
    return after
