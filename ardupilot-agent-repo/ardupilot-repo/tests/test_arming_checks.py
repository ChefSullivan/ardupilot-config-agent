"""
Offline verification of the ARMING_CHECK / ARMING_SKIPCHK conversion logic
in ardupilot_agent.arming_checks.

This does NOT touch real hardware -- it can't confirm the two parameters
behave as documented on an actual Copter 4.7.0 flight controller. What it
does confirm, without needing a bench: the bit table this module hardcodes
matches the metadata quoted in arming_checks.py's own docstring (taken from
AP_Arming.cpp's "// @Param: SKIPCHK" block at tag Copter-4.7.0), and that
converting a set of enabled-check names to either parameter's raw value and
back always recovers the original set. See docs/bench_test_arming_skipchk.md
for the real-hardware procedure this is meant to be paired with.
"""
from __future__ import annotations

import itertools

import pytest

from ardupilot_agent.arming_checks import (
    ARMING_CHECK_BITS,
    INDIVIDUAL_CHECKS,
    SKIP_CHECK_BITS,
    SKIP_PARAM,
    LEGACY_PARAM,
    ArmingCheckParamMissing,
    apply,
    compute_skip_value,
    compute_value,
    describe_value,
    read_current,
    resolve_check_param,
)

# Bit -> name, transcribed directly from the "@Bitmask:" line quoted in
# arming_checks.py's docstring (itself copied from AP_Arming.cpp at tag
# Copter-4.7.0). Bit 9 is intentionally absent -- that gap exists in
# ArduPilot's own metadata, not a typo here.
EXPECTED_SKIPCHK_BITMASK_METADATA = {
    1: "Barometer",
    2: "Compass",
    3: "GPS lock",
    4: "INS",
    5: "Parameters",
    6: "RC Channels",
    7: "Board voltage",
    8: "Battery Level",
    10: "Logging Available",
    11: "Hardware safety switch",
    12: "GPS Configuration",
    13: "System",
    14: "Mission",
    15: "Rangefinder",
    16: "Camera",
    17: "AuxAuth",
    18: "VisualOdometry",
    19: "FFT",
}


def test_skipchk_bit_table_matches_quoted_metadata():
    """SKIP_CHECK_BITS must equal the @Bitmask metadata verbatim -- this is
    the exact check that would have caught the bits being inverted if the
    fix had assumed a plain rename instead of reading AP_Arming.cpp."""
    assert SKIP_CHECK_BITS == EXPECTED_SKIPCHK_BITMASK_METADATA


def test_legacy_bit_table_is_skipchk_table_plus_all():
    """ARMING_CHECK bits 1..19 must carry the same names as ARMING_SKIPCHK
    bits 1..19 -- only bit 0 ("All") is unique to the legacy parameter."""
    assert ARMING_CHECK_BITS[0] == "All"
    assert {b: n for b, n in ARMING_CHECK_BITS.items() if b != 0} == SKIP_CHECK_BITS


def test_legacy_worked_example_from_ardupilot_docs():
    """ArduPilot's own docs: ARMING_CHECK=72 means 'GPS lock + RC Channels'
    (2**3 + 2**6 = 8 + 64 = 72). Confirms compute_value's bit-shift direction."""
    assert compute_value({"GPS lock", "RC Channels"}) == 72


def test_skipchk_all_enabled_skips_nothing():
    assert compute_skip_value(set(INDIVIDUAL_CHECKS)) == 0
    assert compute_skip_value({"All"}) == 0


def test_skipchk_none_enabled_skips_every_individual_bit():
    value = compute_skip_value(set())
    expected = sum(1 << bit for bit in SKIP_CHECK_BITS)
    assert value == expected
    # Sanity: this must NOT equal -1 (this module deliberately avoids the
    # "-1 skips all current and future checks" shortcut -- see
    # compute_skip_value's docstring).
    assert value != -1


@pytest.mark.parametrize(
    "enabled",
    [
        set(INDIVIDUAL_CHECKS),
        set(),
        {"GPS lock"},
        {"RC Channels", "Board voltage", "System", "Parameters", "INS"},  # NEVER_RECOMMEND_DISABLING
        {"GPS lock", "GPS Configuration", "Compass", "Battery Level", "Rangefinder", "Camera", "Barometer"},
    ],
)
def test_skipchk_round_trips(enabled):
    """enabled -> ARMING_SKIPCHK raw value -> decode back must recover the
    exact same set. This is the invariant a hardware bench test is checking
    for real; here it's checked against the documented bit semantics only."""
    raw = compute_skip_value(enabled)
    skipped = {name for bit, name in SKIP_CHECK_BITS.items() if raw & (1 << bit)}
    decoded = set(INDIVIDUAL_CHECKS) - skipped
    assert decoded == enabled


def test_skipchk_and_legacy_agree_on_every_individual_subset():
    """For every non-empty subset of individual checks (skipping the full
    2^18 powerset -- this samples all singletons/pairs plus the extremes),
    the two parameters' raw values must decode to the same enabled set when
    each is interpreted with its own (opposite) polarity."""
    checks = sorted(INDIVIDUAL_CHECKS)
    samples = [set(checks), set()]
    samples += [{c} for c in checks]
    samples += [set(pair) for pair in itertools.combinations(checks, 2)]
    for enabled in samples:
        legacy_raw = compute_value(enabled)
        legacy_decoded = {name for bit, name in ARMING_CHECK_BITS.items() if bit != 0 and legacy_raw & (1 << bit)}
        assert legacy_decoded == enabled

        skip_raw = compute_skip_value(enabled)
        skipped = {name for bit, name in SKIP_CHECK_BITS.items() if skip_raw & (1 << bit)}
        skip_decoded = set(INDIVIDUAL_CHECKS) - skipped
        assert skip_decoded == enabled


def test_unknown_check_name_rejected_by_both_encoders():
    with pytest.raises(KeyError):
        compute_value({"Not A Real Check"})
    with pytest.raises(KeyError):
        compute_skip_value({"Not A Real Check"})


def test_describe_value_labels_the_encoding_explicitly():
    """describe_value must name which parameter/polarity a raw value came
    from, so a skip-mask can never be misread as an enable-mask (or vice
    versa) in logs/UI text."""
    skip_text = describe_value(SKIP_PARAM, compute_skip_value({"GPS lock"}))
    assert SKIP_PARAM in skip_text
    assert "SKIPPING" in skip_text
    # Everything except GPS lock should be listed as skipped.
    for name in INDIVIDUAL_CHECKS - {"GPS lock"}:
        assert name in skip_text
    assert "GPS lock" not in skip_text.replace("SKIPPING ", "")  # not skipped, shouldn't appear as skipped

    legacy_text = describe_value(LEGACY_PARAM, compute_value({"GPS lock"}))
    assert LEGACY_PARAM in legacy_text
    assert "GPS lock" in legacy_text


# ---------------------------------------------------------------------------
# Fake-FC tests: exercise resolve_check_param / read_current / apply's
# control flow (which parameter gets probed/written) without any pymavlink
# connection. These do NOT verify real FC behavior -- see the bench-test doc.
# ---------------------------------------------------------------------------


class _FakeConn:
    """Stands in for FCConnection; only used as an opaque token passed
    through to the monkeypatched get_param/set_param below."""


def _fake_get_param_factory(params):
    def _fake_get_param(conn, name, timeout=5.0):
        if name not in params:
            raise TimeoutError(f"no such param {name}")
        return params[name]

    return _fake_get_param


def _fake_set_param_factory(params):
    def _fake_set_param(conn, name, value, param_type=None, verify=True, timeout=5.0):
        params[name] = value
        return value

    return _fake_set_param


def test_resolve_prefers_legacy_when_both_present(monkeypatch):
    params = {LEGACY_PARAM: 0.0, SKIP_PARAM: 0.0}
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    assert resolve_check_param(_FakeConn()) == LEGACY_PARAM


def test_resolve_falls_back_to_skipchk(monkeypatch):
    params = {SKIP_PARAM: 0.0}
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    assert resolve_check_param(_FakeConn()) == SKIP_PARAM


def test_resolve_raises_when_neither_param_exists(monkeypatch):
    params = {}
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    with pytest.raises(ArmingCheckParamMissing):
        resolve_check_param(_FakeConn())


def test_read_current_on_simulated_47_fc_decodes_skip_polarity(monkeypatch):
    """Simulates a 4.7.0-style FC (only ARMING_SKIPCHK present) with GPS
    lock and Compass skipped; read_current must report everything else as
    enabled."""
    skip_raw = compute_skip_value(set(INDIVIDUAL_CHECKS) - {"GPS lock", "Compass"})
    params = {SKIP_PARAM: float(skip_raw)}
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    enabled = read_current(_FakeConn())
    assert enabled == set(INDIVIDUAL_CHECKS) - {"GPS lock", "Compass"}


def test_read_current_on_simulated_pre_47_fc_decodes_legacy_polarity(monkeypatch):
    params = {LEGACY_PARAM: float(compute_value({"GPS lock", "RC Channels"}))}
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    enabled = read_current(_FakeConn())
    assert enabled == {"GPS lock", "RC Channels"}


def test_apply_writes_skipchk_on_simulated_47_fc(monkeypatch):
    params = {SKIP_PARAM: 0.0}
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    monkeypatch.setattr("ardupilot_agent.arming_checks.set_param", _fake_set_param_factory(params))
    param_name, value = apply(_FakeConn(), set(INDIVIDUAL_CHECKS) - {"GPS lock"})
    assert param_name == SKIP_PARAM
    assert value == compute_skip_value(set(INDIVIDUAL_CHECKS) - {"GPS lock"})
    # And reading it back must decode to the same enabled set (full
    # write-then-read round trip through the module's own public API).
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    assert read_current(_FakeConn()) == set(INDIVIDUAL_CHECKS) - {"GPS lock"}


def test_apply_writes_legacy_on_simulated_pre_47_fc(monkeypatch):
    params = {LEGACY_PARAM: 0.0}
    monkeypatch.setattr("ardupilot_agent.arming_checks.get_param", _fake_get_param_factory(params))
    monkeypatch.setattr("ardupilot_agent.arming_checks.set_param", _fake_set_param_factory(params))
    param_name, value = apply(_FakeConn(), {"GPS lock", "RC Channels"})
    assert param_name == LEGACY_PARAM
    assert value == 72
