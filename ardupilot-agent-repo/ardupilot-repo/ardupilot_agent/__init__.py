"""
ardupilot_agent: safety-gated pymavlink toolkit for ArduPilot configuration
work, distilled from hands-on debugging of flight-controller parameter and
motor-wiring issues.

Design principle running through every module: never trust a remembered
parameter name, enum value, or GCS-UI convention. Always verify against the
live flight controller, and gate anything destructive behind an explicit
armed-state check.
"""
from .connection import FCConnection, SafetyError

__all__ = ["FCConnection", "SafetyError"]
