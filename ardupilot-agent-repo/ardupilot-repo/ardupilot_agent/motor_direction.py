"""
Motor rotation-direction reversal.

SERVOx_FUNCTION fixes (motor_test.py) only correct *which corner responds
to which mixer input* -- not which way the motor spins. Fixing rotation
direction depends on ESC protocol, verified against
https://ardupilot.org/copter/docs/common-dshot-escs.html :

- Normal PWM / OneShot / OneShot125 (MOT_PWM_TYPE 0/1/2): there is no
  software fix. Physically swap any 2 of the 3 motor/ESC bullet-connector
  wires. This module deliberately does not attempt anything for this case
  -- it's a hardware step, not a parameter write.
- DShot-family protocols (MOT_PWM_TYPE >= 3) on BLHeli32/AM32/BLHeli_S
  ESCs: the DShot "Reverse motor direction" command can flip a motor's
  direction in software via the SERVO_BLH_RVMASK bitmask, no wiring
  needed. This requires SERVO_DSHOT_ESC to be set to the ESC's DShot
  command-set type (1 for the common BLHeli32/AM32/BLHeli_S set) --
  without that, DShot commands (including reverse) are not sent at all.

Note: ArduPilot's *reversible* DShot / 3D mode (SERVO_BLH_3DMASK) is
currently Copter-unsupported per the docs ("ArduPilot only supports the use
of reversible ESCs for Plane and Rover, not Copter"). This module only
uses the separate, simpler "reverse direction" DShot command, not 3D mode.

Bit convention: SERVO_BLH_RVMASK is a per-output bitmask; bit (channel-1)
corresponds to output channel `channel`, matching other ArduPilot *_MASK
output parameters. Always re-read after writing to confirm -- verify,
don't assume.
"""
from __future__ import annotations

from typing import Set

from .connection import FCConnection
from .params import get_param, set_param
from .esc_calibration import PWM_TYPES_NEEDING_CALIBRATION

DSHOT_COMMAND_SET_STANDARD = 1  # SERVO_DSHOT_ESC=1: the commonly-supported BLHeli32/AM32/BLHeli_S command set


def is_dshot_protocol(conn: FCConnection) -> bool:
    """True if MOT_PWM_TYPE is a DShot-family (or other digital) protocol
    rather than analog-timing PWM/OneShot/OneShot125.
    """
    pwm_type = int(get_param(conn, "MOT_PWM_TYPE"))
    return pwm_type not in PWM_TYPES_NEEDING_CALIBRATION


def dshot_commands_enabled(conn: FCConnection) -> bool:
    """SERVO_DSHOT_ESC must be non-zero for DShot commands (including the
    reverse-direction command) to actually be sent to the ESCs.
    """
    return int(get_param(conn, "SERVO_DSHOT_ESC")) != 0


def enable_dshot_commands(conn: FCConnection) -> None:
    """Set SERVO_DSHOT_ESC to the standard command set. Only do this after
    confirming the ESCs are BLHeli32/AM32/BLHeli_S-family -- an
    unrecognized ESC receiving this command set is documented by ArduPilot
    as resulting in undefined operation.
    """
    set_param(conn, "SERVO_DSHOT_ESC", DSHOT_COMMAND_SET_STANDARD)


def get_reverse_mask(conn: FCConnection) -> int:
    return int(get_param(conn, "SERVO_BLH_RVMASK"))


def get_reversed_channels(conn: FCConnection) -> Set[int]:
    mask = get_reverse_mask(conn)
    return {ch for ch in range(1, 17) if mask & (1 << (ch - 1))}


def set_channel_reversed(conn: FCConnection, channel: int, reversed_: bool) -> int:
    """Flip a single channel's bit in SERVO_BLH_RVMASK, leaving other bits
    untouched, and write the new mask. Returns the confirmed mask after
    write. Requires the vehicle disarmed (motor direction is safety
    relevant); a reboot is the safest way to guarantee the change is
    picked up by the ESC driver.
    """
    conn.require_disarmed()
    mask = get_reverse_mask(conn)
    bit = 1 << (channel - 1)
    mask = (mask | bit) if reversed_ else (mask & ~bit)
    return int(set_param(conn, "SERVO_BLH_RVMASK", mask))
