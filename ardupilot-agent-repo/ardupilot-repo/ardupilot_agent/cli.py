"""
Command-line entry point tying the toolkit together.

Usage examples:
  python -m ardupilot_agent.cli --device COM6 params-search --grep RNGFND
  python -m ardupilot_agent.cli --device COM6 param-get --name FRAME_CLASS
  python -m ardupilot_agent.cli --device COM6 param-set --name MOT_PWM_TYPE --value 0 --reboot
  python -m ardupilot_agent.cli --device COM6 motor-map --count 4 --frame BETAFLIGHT_X --apply
  python -m ardupilot_agent.cli --device COM6 failsafe-wizard --apply
"""
from __future__ import annotations

import argparse
import sys

from .connection import FCConnection, SafetyError
from .params import fetch_all_params, search_params, get_param, set_param, set_param_and_verify_after_reboot
from .motor_test import build_motor_map, compute_servo_function_fixes, apply_servo_function_fixes
from .frame_reference import FRAME_EXPECTED_LAYOUTS
from .failsafe import FailsafeIntent, apply_failsafe_intent, compute_fs_options, describe_fs_options


def _connect(args) -> FCConnection:
    return FCConnection.connect(args.device, baud=args.baud)


def cmd_params_search(args):
    conn = _connect(args)
    all_params = fetch_all_params(conn)
    matches = search_params(all_params, args.grep)
    for name, value in sorted(matches.items()):
        print(f"{name} = {value}")
    if not matches:
        print(f"No parameters matched '{args.grep}'. Do not assume the name -- check spelling/instance suffix.")


def cmd_param_get(args):
    conn = _connect(args)
    print(f"{args.name} = {get_param(conn, args.name)}")


def cmd_param_set(args):
    conn = _connect(args)
    if args.reboot:
        set_param_and_verify_after_reboot(conn, args.name, args.value)
    else:
        if args.require_disarmed:
            conn.require_disarmed()
        result = set_param(conn, args.name, args.value)
        print(f"{args.name} confirmed = {result}")


def cmd_motor_map(args):
    conn = _connect(args)

    def ask_corner(instance: int, channel: int) -> str:
        return input(
            f"Motor instance {instance} spun (output channel {channel} per telemetry). "
            f"Which physical corner spun? (e.g. front-right): "
        ).strip().lower()

    entries = build_motor_map(conn, motor_count=args.count, ask_corner=ask_corner, throttle_pct=args.throttle)
    print("\nVerified wiring table:")
    for e in entries:
        print(f"  instance {e.instance} -> channel {e.channel} -> {e.corner}")

    if args.frame and args.frame in FRAME_EXPECTED_LAYOUTS:
        expected = FRAME_EXPECTED_LAYOUTS[args.frame]
        fixes = compute_servo_function_fixes(entries, expected)
        print("\nRequired SERVOx_FUNCTION fixes:")
        for channel, func_val in fixes.items():
            print(f"  SERVO{channel}_FUNCTION = {func_val}")
        if args.apply:
            apply_servo_function_fixes(conn, fixes)
    else:
        print(
            f"\nFrame type '{args.frame}' not in the local reference cache -- "
            f"fetch https://ardupilot.org/copter/docs/connect-escs-and-motors.html "
            f"for this frame's expected corner->motor mapping, add it to "
            f"frame_reference.py, then re-run with --frame to compute fixes."
        )


def cmd_failsafe_wizard(args):
    conn = _connect(args)

    def yn(prompt):
        return input(f"{prompt} [y/N]: ").strip().lower().startswith("y")

    intent = FailsafeIntent(
        continue_auto_mission_on_radio_loss=yn("Continue an active Auto mission if RC link is lost?"),
        continue_auto_mission_on_gcs_loss=yn("Continue an active Auto mission if GCS/telemetry link is lost?"),
        continue_guided_on_radio_loss=yn("Continue Guided mode if RC link is lost?"),
        continue_pilot_control_on_gcs_loss=yn(
            "Keep pilot control (no RTL/Land) if only the GCS link is lost while flying manually?"
        ),
    )
    print(describe_fs_options(compute_fs_options(intent)))
    if args.apply:
        apply_failsafe_intent(conn, intent)
    else:
        print("Dry run only -- pass --apply to write these to the FC.")


def build_parser():
    p = argparse.ArgumentParser(prog="ardupilot-agent")
    p.add_argument("--device", required=True, help="Serial device, e.g. COM6 or /dev/ttyACM0")
    p.add_argument("--baud", type=int, default=115200)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("params-search", help="Grep the live parameter list")
    sp.add_argument("--grep", required=True)
    sp.set_defaults(func=cmd_params_search)

    sp = sub.add_parser("param-get")
    sp.add_argument("--name", required=True)
    sp.set_defaults(func=cmd_param_get)

    sp = sub.add_parser("param-set")
    sp.add_argument("--name", required=True)
    sp.add_argument("--value", required=True, type=float)
    sp.add_argument("--reboot", action="store_true", help="Use the verify-after-reboot pattern")
    sp.add_argument("--require-disarmed", dest="require_disarmed", action="store_true", default=True)
    sp.set_defaults(func=cmd_param_set)

    sp = sub.add_parser("motor-map", help="Empirical per-instance motor test + telemetry mapping")
    sp.add_argument("--count", type=int, required=True, help="Number of motors")
    sp.add_argument("--throttle", type=int, default=20, help="Test throttle percent (>=15-20 recommended)")
    sp.add_argument("--frame", default="", help="Frame type key from frame_reference.py, e.g. BETAFLIGHT_X")
    sp.add_argument("--apply", action="store_true", help="Apply computed SERVOx_FUNCTION fixes")
    sp.set_defaults(func=cmd_motor_map)

    sp = sub.add_parser("failsafe-wizard")
    sp.add_argument("--apply", action="store_true")
    sp.set_defaults(func=cmd_failsafe_wizard)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except SafetyError as e:
        print(f"SAFETY ABORT: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
