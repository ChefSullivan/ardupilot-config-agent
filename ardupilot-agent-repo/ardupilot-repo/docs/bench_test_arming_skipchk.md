# Bench test: ARMING_SKIPCHK on real Copter 4.7.0+ hardware

This is a manual procedure for whoever has physical access to a Copter
4.7.0+ flight controller. It is the piece the offline suite
(`tests/test_arming_checks.py`) cannot cover: that suite proves the bit
table and conversion math match ArduPilot's *documented* `SKIPCHK`
metadata, not that a real FC actually behaves that way.

Status as of this writing: **not yet run against real hardware.** Update
`.ardupilot_update_state.json`'s `known_issues` entry (remove/reword it)
once this has been done and the result is known.

## Prerequisites

- A flight controller running Copter **4.7.0 or later**, connected over
  USB (props off, no battery needed — this is param-only work).
- `ardupilot-agent` installed (`pip install -r requirements.txt` from the
  repo root).
- Know the FC's COM port (Windows Device Manager) or `/dev/ttyACM0`-style
  path.

## Procedure

1. **Confirm ARMING_SKIPCHK is what's actually present.**
   ```bash
   python -m ardupilot_agent.cli --device COM6 params-search --grep ARMING_
   ```
   Confirm `ARMING_SKIPCHK` is listed and `ARMING_CHECK` is **not** — if
   both appear, this FC is not on the encoding this bench test targets.

2. **Record the FC's current value** before touching anything:
   ```bash
   python -m ardupilot_agent.cli --device COM6 param-get --name ARMING_SKIPCHK
   ```
   Write it down. If it's `0`, that's "skip nothing" (all checks run) —
   the common default.

3. **Cross-check against reality.** With the current value, try to arm
   the vehicle (props off) in a mode that doesn't require GPS (e.g.
   Stabilize), and separately in Loiter/PosHold if no GPS is connected.
   Confirm the arming failure/success matches what
   `ardupilot_agent.arming_checks.describe_value()` predicts for that raw
   value — e.g. if `GPS lock` is *not* in the skipped set, arming in
   Loiter without a GPS fix should be refused with a GPS-related prearm
   message; if it *is* skipped, arming should proceed (mind other checks
   still enabled).

4. **Write a known skip set and verify it lands correctly.** Using the
   library directly (safer than the CLI for this one-off check, since it
   lets you inspect the raw value):
   ```python
   from ardupilot_agent.connection import FCConnection
   from ardupilot_agent import arming_checks

   conn = FCConnection.connect("COM6", baud=115200)
   conn.require_disarmed()

   # Skip everything except the checks this toolkit says should never be disabled.
   target_enabled = arming_checks.INDIVIDUAL_CHECKS - arming_checks.NEVER_RECOMMEND_DISABLING
   param_name, raw_value = arming_checks.apply(conn, target_enabled)
   print(param_name, raw_value)
   ```
5. **Read it back independently** — not through this toolkit, to rule out
   a read/write path both making the same mistake. Use Mission Planner's
   Full Parameter List (or `mavproxy.py`'s `param show ARMING_SKIPCHK`)
   and manually decode the bitmask against the `@Bitmask:` list in
   `AP_Arming.cpp` for that firmware version. It must match
   `describe_value()`'s printed summary from step 4.

6. **Confirm arming behavior matches the write.** With that skip set
   applied, attempt to arm (props off) with one of the *never-disabled*
   checks intentionally in a failing state (e.g. disconnect RC — "RC
   Channels" is in `NEVER_RECOMMEND_DISABLING` and should still be
   enforced). Arming should still be **refused**. Then attempt to arm
   with a *skipped* check in a failing state (e.g. no GPS fix, if "GPS
   lock" was skipped) — arming should **succeed** (motors off, props off,
   just confirming the prearm check itself passes).

7. **Round-trip through `read_current()`** to close the loop:
   ```python
   read_back = arming_checks.read_current(conn)
   assert read_back == target_enabled, (read_back, target_enabled)
   ```

8. **Restore a safe default** before disconnecting — don't leave a bench
   FC with checks skipped:
   ```python
   arming_checks.apply(conn, arming_checks.INDIVIDUAL_CHECKS)  # skip nothing
   ```

## What "pass" means

All of: the FC only exposes `ARMING_SKIPCHK` (not `ARMING_CHECK`); the
raw value this toolkit writes decodes, via an independent tool (Mission
Planner / MAVProxy), to the same enabled/skipped set this toolkit
reports; and real arm/disarm behavior for both a skipped and a
never-disabled check matches that decoded set.

If any of those disagree, the bug is almost certainly in the polarity or
bit-table assumptions in `arming_checks.py` — re-derive the semantics
from `AP_Arming.cpp`'s `SKIPCHK` metadata at the exact tag for the
firmware under test (metadata has changed before; don't assume 4.7.0's
table still applies to a later point release without checking).
