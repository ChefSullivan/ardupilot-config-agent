# ardupilot-agent

A safety-gated pymavlink toolkit for ArduPilot flight-controller
configuration, distilled from a hands-on debugging session that hit real
gotchas: mis-remembered parameter names, a stale failsafe enum value, a
wrong-board doc match that would have caused a real safety issue, and a
Mission-Planner-UI motor test that gave contradictory results.

It ships as two things:

- **`ardupilot_agent/`** -- a standalone Python library/CLI you can run
  yourself, with or without an LLM in the loop. The safety patterns (armed
  check, read-modify-verify-reboot, empirical motor mapping) are hard-coded,
  not just documented.
- **`SKILL.md`** -- domain knowledge and workflow guidance for an AI agent
  (e.g. Claude Code) driving the library, including the specific gotchas
  worth knowing before touching a real vehicle.

**Important:** this needs a real serial connection to a real flight
controller. It will not do anything useful in a sandboxed/cloud
environment with no USB access -- run it wherever the FC is physically
plugged in.

## Install

```bash
pip install -r requirements.txt
```

## Quick start (GUI)

If you'd rather click buttons than type commands, there's a desktop GUI
built on Tkinter (ships with Python on Windows -- no extra install):

```bash
py ardupilot_gui.py
```

It gives you a connection bar (auto-populated COM-port dropdown, live
armed/disarmed indicator, light/dark theme toggle with an ArduPilot-inspired
orange accent) plus four tabs. The Setup Wizard's step area scrolls, so
taller steps are reachable at any window size, not just maximized.

- **Setup Wizard** -- a linear, Next/Back walkthrough (with a step
  dropdown for jumping around) of the full first-time-configuration
  sequence:
  - *Welcome* -- a pre-flight checklist of what should already be true
    (firmware flashed, receiver bound, props off, etc.) before you start.
  - *Welcome* opens with a "Run this first" callout linking straight to
    the Compatibility Check (see below), before the checklist and the
    one-time "Vehicle Profile" pick (bench
    testing / manual flying / semi-autonomous / autonomous mission) that
    pre-fills the Failsafe and Arming Checks presets downstream, plus an
    "Apply Recommended Failsafe + Arming Now" shortcut that writes both in
    one click without visiting either page -- this is the "do more than
    just gate manual param edits" automation layer.
  - *Frame Class Review* -- shows FRAME_CLASS/FRAME_TYPE with their
    human-readable meaning (Quad/Hexa/Octa/BetaFlightX/etc), the detected
    vehicle type (Copter/Plane/Rover/...) from the live heartbeat, and can
    now write FRAME_CLASS/FRAME_TYPE (not just read them) with one reboot.
  - *RC Calibration* -- a live per-channel PWM monitor (wiggle a stick or
    flip a switch and watch it move), RCMAP role reassignment, and the
    original guided live-capture / quick known-values calibration modes.
  - *Flight Modes* -- assign a mode to a switch position by flipping the
    physical switch and watching a live "you're on slot N" readout, or
    fill in the 6-slot table directly.
  - *Motor Order & Direction* -- the empirical per-instance motor test
    (unchanged), plus a rotation-direction section: guidance for
    PWM/OneShot ESCs (physical wire swap) and a software DShot reverse
    toggle (SERVO_BLH_RVMASK) for DShot ESCs.
  - *ESC Calibration* -- auto-checks your protocol and leads with a
    skip/needed verdict; the detailed checklist is collapsed by default.
  - *Failsafe* -- plain yes/no questions instead of jargon, "Recommended
    Failsafe" presets by use case (auto-selected from your Vehicle Profile,
    still changeable), and a GPS/Position (EKF) failsafe section
    (FS_EKF_ACTION / FS_EKF_THRESH) -- the modern replacement for
    ArduPilot's now-archived dedicated "GPS failsafe".
  - *Arming Checks* -- presets by use case (bench/indoor, manual outdoor,
    autonomous, or a "No Checks" bench-testing preset with an explicit
    extra warning) alongside the individual checkboxes, each with a hover
    tooltip explaining what it checks and what hardware it applies to.
  - *Summary* -- lists every change actually applied this session (a
    running change log), not just static text, so you can verify and jump
    back to fix anything.
- **Parameters** -- search/get/set against the live FC. Any parameter name
  typed or selected is decoded: a specific plain-English description if
  this toolkit has one, otherwise a breakdown of its subsystem prefix
  (EKF, SERIAL, RNGFND, BATT, etc. -- see `param_help.py`'s PREFIX_GLOSSARY)
  so unfamiliar parameters are less opaque even without a curated entry.
- **Motor Map** -- the same per-instance motor test as the wizard's Motor
  Order step, for revisiting it standalone later.
- **Failsafe** -- the same checkbox/preview UI as the wizard's Failsafe
  step, for revisiting it standalone later.
- **Compatibility** -- reads the connected FC's firmware version and checks
  every parameter this toolkit relies on against the live FC, flagging
  anything a future ArduPilot update has renamed/removed instead of
  failing confusingly deep inside a wizard step. Run it any time something
  behaves unexpectedly, or right after a firmware update.

Every button that writes to the FC still goes through the same
`require_disarmed()` safety gate as the CLI -- the GUI is convenience on
top, it doesn't relax any check. All serial I/O runs on a single background
thread so nothing can talk over the connection at once. Every apply action
across every step is recorded to the Setup Wizard's Summary step via
`_record_change()`, so nothing gets applied silently.

## Quick start (CLI)

```bash
# Find a parameter without trusting a remembered name
python -m ardupilot_agent.cli --device COM6 params-search --grep RNGFND

# Read one value
python -m ardupilot_agent.cli --device COM6 param-get --name FRAME_CLASS

# Set a parameter that needs a reboot to take effect, and verify it survived
python -m ardupilot_agent.cli --device COM6 param-set --name MOT_PWM_TYPE --value 0 --reboot

# Diagnose motor wiring empirically (per-instance test + telemetry, not GCS buttons)
python -m ardupilot_agent.cli --device COM6 motor-map --count 4 --frame BETAFLIGHT_X --apply

# Compose failsafe behavior from explicit yes/no intent, not a memorized enum
python -m ardupilot_agent.cli --device COM6 failsafe-wizard --apply
```

`--device` is `COM6` (or similar) on Windows, `/dev/ttyACM0` or
`/dev/ttyUSB0` on Linux/macOS.

## Quick start (library)

```python
from ardupilot_agent.connection import FCConnection
from ardupilot_agent.params import fetch_all_params, search_params, set_param_and_verify_after_reboot
from ardupilot_agent.motor_test import build_motor_map, compute_servo_function_fixes, apply_servo_function_fixes
from ardupilot_agent.frame_reference import FRAME_EXPECTED_LAYOUTS

conn = FCConnection.connect("COM6", baud=115200)

# Never trust a remembered name -- pull the live list and grep it
all_params = fetch_all_params(conn)
print(search_params(all_params, "GNDCLEAR"))

# Reboot-requiring param, verified after restart
set_param_and_verify_after_reboot(conn, "FRAME_CLASS", 1)

# Empirical motor-order diagnosis
entries = build_motor_map(
    conn,
    motor_count=4,
    ask_corner=lambda instance, channel: input(f"instance {instance} (ch {channel}) spun which corner? "),
)
fixes = compute_servo_function_fixes(entries, FRAME_EXPECTED_LAYOUTS["BETAFLIGHT_X"])
apply_servo_function_fixes(conn, fixes)
```

## Module map

| Module | Purpose |
|---|---|
| `connection.py` | Connect, armed-state check, `require_disarmed()` hard gate, reboot-and-wait |
| `params.py` | Fetch full live param list, substring search, get/set, verify-after-reboot |
| `motor_test.py` | Per-instance `MAV_CMD_DO_MOTOR_TEST` + `SERVO_OUTPUT_RAW` telemetry mapping, `SERVOx_FUNCTION` fix computation/application |
| `frame_reference.py` | Cache of confirmed frame-type corner->motor layouts (verify before trusting/extending) |
| `failsafe.py` | `FS_OPTIONS`/`FS_GCS_ENABLE` composition from explicit intent, with bit meanings sourced from ardupilot.org |
| `rc_calibration.py` | RC channel min/max/trim capture (guided live-capture or quick known-values mode), RCMAP-aware |
| `flight_modes.py` | Verified flight-mode enum, `FLTMODE_CH`/`FLTMODEn` assignment, PWM breakpoints |
| `esc_calibration.py` | ESC calibration guidance/checklist + semi-automatic `ESC_CALIBRATION` trigger |
| `arming_checks.py` | `ARMING_CHECK` bitmask composition, with guidance on what's safe to disable |
| `vehicle_info.py` | FRAME_CLASS/FRAME_TYPE human-readable labels, MAV_TYPE vehicle detection |
| `motor_direction.py` | DShot motor rotation-direction reversal (`SERVO_BLH_RVMASK`) |
| `presets.py` | Curated failsafe/arming-check presets by use case (testing/manual/semi-auto/autonomous) |
| `param_help.py` | Plain-English descriptions for the parameters this toolkit already touches |
| `compatibility.py` | Live firmware-version + parameter-existence check against everything this toolkit relies on |
| `cli.py` | Command-line wrapper over the core modules |
| `ardupilot_gui.py` + `ardupilot_gui_*.py` | Tkinter desktop GUI (Setup Wizard + standalone tabs), run standalone, no Claude/CLI needed. Each wizard step lives in its own `ardupilot_gui_wizard_*.py` file. |

## Tests

```bash
python -m pytest tests/
```

Offline only — no flight controller needed. `tests/test_arming_checks.py`
verifies the `ARMING_CHECK`/`ARMING_SKIPCHK` bit tables against the
metadata quoted in `arming_checks.py` and round-trips the conversion in
both encodings. It cannot confirm a real FC behaves as documented; the
manual procedure for that is
[`docs/bench_test_arming_skipchk.md`](docs/bench_test_arming_skipchk.md),
which has **not** yet been run against real 4.7.0+ hardware.

## Extending

- Add a confirmed frame layout to `frame_reference.py` only after
  cross-checking https://ardupilot.org/copter/docs/connect-escs-and-motors.html
  for that specific `FRAME_CLASS`/`FRAME_TYPE` -- don't extrapolate from a
  similarly-named frame.
- If you hit a parameter name/enum gotcha not already documented in
  `params.py` or `failsafe.py`, add it as a comment near the relevant
  function so the next session doesn't repeat the mistake.
