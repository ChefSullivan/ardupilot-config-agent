"""
Reference cache of frame-type expected motor layouts.

WARNING: treat this as a starting point only, not ground truth. Before
trusting any entry, cross-check it live against
https://ardupilot.org/copter/docs/connect-escs-and-motors.html for the
vehicle's actual FRAME_CLASS/FRAME_TYPE. Board and frame naming is
genuinely ambiguous across product lines (e.g. "iFlight Blitz F7" covers
several variants with different pinouts), and a doc page for a
similarly-named variant is a real trap. Verify empirically with
motor_test.py rather than trusting this table or memory alone.

Only add entries here after they've been confirmed against the live doc
page for that specific frame type -- don't extrapolate from a related frame.
"""
from __future__ import annotations

from typing import Dict

# corner -> motor number (1-indexed), per frame type name.
FRAME_EXPECTED_LAYOUTS: Dict[str, Dict[str, int]] = {
    "BETAFLIGHT_X": {
        # BetaFlightX frame type (FRAME_TYPE=12). Confirmed against
        # connect-escs-and-motors.html during a live diagnosis session.
        "front-right": 1,
        "rear-left": 2,
        "front-left": 3,
        "rear-right": 4,
    },
}

# corner -> expected rotation direction. SERVOx_FUNCTION fixes only correct
# *which corner responds to which mixer input* -- they do NOT fix rotation
# direction, which is a function of the 3-phase wiring between motor and ESC
# (fixed by swapping any 2 of the 3 bullet-connector wires).
ROTATION_EXPECTED: Dict[str, Dict[str, str]] = {
    "BETAFLIGHT_X": {
        "front-right": "CW",
        "rear-left": "CW",
        "front-left": "CCW",
        "rear-right": "CCW",
    },
}
