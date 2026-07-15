---
name: ardupilot-config
description: Use this skill whenever the user wants to configure, diagnose, or fix an ArduPilot flight controller (Copter/Plane/Rover) over a direct USB/serial MAVLink connection -- setting or searching parameters, diagnosing motor order/wiring, configuring failsafes, or identifying board/frame variants. Trigger on mentions of ArduPilot, Mission Planner parameters, FRAME_CLASS, motor test, ESC wiring, SERVOx_FUNCTION, FS_OPTIONS/failsafe setup, or a COM port / serial device connected to a flight controller. Do NOT use for simulation-only work with no real hardware attached, or for non-ArduPilot autopilots (PX4, etc.) without adapting the MAVLink specifics first.
---

# ArduPilot Configuration Agent

## Overview

This skill wraps the `ardupilot_agent` Python toolkit (in this same
directory) for doing live ArduPilot flight-controller configuration over a
direct pymavlink connection -- not just through Mission Planner. It encodes
patterns learned the hard way in a prior session: never trust a remembered
parameter name or enum value, gate every destructive action on the vehicle
being disarmed, and diagnose motor wiring empirically rather than by
assumption.

**This requires real hardware on a real serial port.** It will not work in
a sandboxed/cloud environment with no USB access -- run it in a terminal
session (e.g. Claude Code) on the machine the flight controller is
physically plugged into.

## Setup

```bash
cd ardupilot-agent
pip install -r requirements.txt
```

Identify the serial device first: `COM6` and similar on Windows,
`/dev/ttyACM0` or `/dev/ttyUSB0` on Linux/macOS. The FC is powered over USB
independent of the flight battery, so parameter work does not require
props-on power -- but always treat the vehicle as if it could arm.

## Hard safety rules (non-negotiable)

1. **Never proceed with a reboot, motor test, or motor/servo/frame/serial
   parameter change while armed.** The toolkit enforces this in code
   (`FCConnection.require_disarmed()`, called internally by the relevant
   functions) -- don't work around it or call low-level pymavlink directly
   to bypass it.
2. **Never trust a remembered parameter name or enum value.** Always call
   `params.fetch_all_params()` + `params.search_params()` against the live
   FC before setting anything, even if you're confident you know the name.
   Real examples that have bitten this before: `RNGFND1_GNDCLR` (wrong) vs.
   `RNGFND1_GNDCLEAR` (correct); assuming a global `RNGFND_GNDCLEAR` when
   it's per-instance; `FS_GCS_ENABLE=2` meaning "continue mission" (removed
   in Copter 4.0+, replaced by an `FS_OPTIONS` bit).
3. **Never trust a doc page matched by board name alone.** Product lines
   ship multiple variants with different pinouts (e.g. "iFlight Blitz F7"
   covers F745/Mini, Whoop F7 AIO, and F7 Pro with different UART/RC
   mappings). Ask for the exact silkscreen text or firmware target string
   (e.g. `IFLIGHT_BLITZ_F7_AIO`), and when in doubt, verify empirically
   against the live vehicle instead of trusting documentation matching by
   name. A silkscreen label like "UART3" does not necessarily match
   ArduPilot's internal `SERIALx` numbering -- these are independent
   numbering schemes set by the board's hwdef.
4. **Parameters that only fully apply after reboot** -- `FRAME_CLASS`,
   `SERIALx_PROTOCOL`, `MOT_PWM_TYPE`, `SERVOx_FUNCTION` -- must go through
   `params.set_param_and_verify_after_reboot()`, not a plain `set_param()`.
   Setting them live does not guarantee the new behavior takes effect until
   restart.
5. **DShot / ESC protocol changes are high-risk.** Setting `MOT_PWM_TYPE`
   to a DShot value without confirming the specific ESC firmware supports it
   can cause continuous ESC beeping and motor twitching while disarmed.
   `MOT_PWM_TYPE=0` (normal PWM) is the universal-compatibility fallback.
   Require a real ESC calibration pass before trusting DShot.
6. **`FRAME_CLASS=0` is a valid-but-broken default** that silently blocks
   arming. Check for it explicitly rather than assuming a nonzero value.
7. **Don't "fix" a legitimate prearm refusal.** If arming is blocked because
   `ARMING_CHECK` includes GPS and there's no fix, that's correct behavior,
   not a bug -- don't resolve it by disabling arming checks.

## Motor-order diagnosis workflow

This is the trickiest and most reusable part. Do NOT ask the user to run
Mission Planner's Motor Test A/B/C/D buttons and report which corner spun --
those buttons follow ArduPilot's internal per-frame-type test order (e.g.
BetaFlightX visits Motor1, Motor4, Motor2, Motor3 -- not 1-2-3-4), and
"front-left"-style position reports are viewer-orientation-dependent and
easy to get inconsistent across a session.

Instead, use `motor_test.build_motor_map()`:

1. It commands each motor instance individually via
   `MAV_CMD_DO_MOTOR_TEST` (one motor at a time, never batched).
2. It simultaneously watches `SERVO_OUTPUT_RAW` to see which numbered
   output channel's PWM actually changed -- the true instance->channel
   mapping, independent of GCS UI semantics.
3. It asks the user which physical corner spun for that specific, isolated
   test.
4. It combines instance->channel (telemetry) with channel->corner (user
   report) into a verified wiring table.

Test at **>=15-20% throttle**, never below ~10% -- that's often under
`MOT_SPIN_MIN` and a working motor won't spin, which looks like a wiring
fault but isn't.

Once you have the verified wiring table, look up the frame type's expected
corner->motor-number mapping. Check `frame_reference.py` first, but treat
it as a starting point only -- verify against
https://ardupilot.org/copter/docs/connect-escs-and-motors.html for the
vehicle's actual `FRAME_CLASS`/`FRAME_TYPE` before trusting it, and add
confirmed entries back to that file for reuse. Then
`motor_test.compute_servo_function_fixes()` computes the required
`SERVOx_FUNCTION` values, and `motor_test.apply_servo_function_fixes()`
pushes them, reboots, and verifies.

**After applying the fix, re-run the per-instance test to confirm
physically** -- don't just trust the parameter write. Separately verify
rotation direction (CW/CCW) per corner against the frame's expected
mapping: `SERVOx_FUNCTION` only fixes which corner responds to which mixer
input, not which way the motor spins. Wrong rotation direction is fixed by
swapping any 2 of the 3 motor/ESC wires, not by a parameter change.

This generalizes cleanly to hex/octo frames (`motor_function_value()`
supports Motor1-8).

## Failsafe configuration workflow

`FS_GCS_ENABLE` sets the default failsafe action; `FS_OPTIONS` is a
separate bitmask that determines whether an autonomous mission actually
survives a link loss. **"Continue the mission regardless of link" and
"return home on link loss" are not the same setting** -- get explicit
answers from the user on both axes (radio-link loss behavior and GCS-link
loss behavior, and whether Auto/Guided/pilot-controlled modes should be
affected) before writing anything. Use `failsafe.FailsafeIntent` to capture
that intent explicitly, then `failsafe.apply_failsafe_intent()` to write it
atomically. See the module docstring in `failsafe.py` for the verified bit
meanings (sourced live from ardupilot.org, not memory).

## Board/UART identification

Board-specific "USER" UARTs are the right place for companion computers or
peripherals -- check the board's documented port table for which ports are
dedicated (GPS, RC, DisplayPort, ESC telemetry) vs. free, rather than
picking an arbitrary free-looking port. When a board name is ambiguous,
stop and ask for the exact silkscreen text or firmware target string before
touching `SERIALx_PROTOCOL` or wiring anything to a specific port.

## CLI reference

```bash
python -m ardupilot_agent.cli --device COM6 params-search --grep RNGFND
python -m ardupilot_agent.cli --device COM6 param-get --name FRAME_CLASS
python -m ardupilot_agent.cli --device COM6 param-set --name MOT_PWM_TYPE --value 0 --reboot
python -m ardupilot_agent.cli --device COM6 motor-map --count 4 --frame BETAFLIGHT_X --apply
python -m ardupilot_agent.cli --device COM6 failsafe-wizard --apply
```

Or import the modules directly in a Python/Claude Code session for more
control -- see `README.md` for module-level examples.
