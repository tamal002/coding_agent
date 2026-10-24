"""Tests for the usage meter: sums, free local cost, and the display line."""

from __future__ import annotations

from agent.llm.usage import UsageTracker
from tests.fakes import FAKE_USAGE


def test_record_sums_tokens() -> None:
    tracker = UsageTracker()
    tracker.record(FAKE_USAGE)
    tracker.record(FAKE_USAGE)
    assert tracker.input_tokens == 26
    assert tracker.output_tokens == 14
    assert tracker.total_tokens == 40


def test_record_tolerates_missing_keys() -> None:
    tracker = UsageTracker()
    tracker.record({"output_tokens": 5})  # older payloads may lack keys
    tracker.record(None)
    tracker.record({})
    assert tracker.input_tokens == 0
    assert tracker.output_tokens == 5
    assert tracker.total_tokens == 5


def test_record_from_message() -> None:
    tracker = UsageTracker()

    class FakeMessage:
        usage_metadata = FAKE_USAGE

    tracker.record_from_message(FakeMessage())
    assert tracker.total_tokens == 20


def test_local_cost_is_zero_and_displayed() -> None:
    tracker = UsageTracker()
    tracker.record(FAKE_USAGE)
    assert tracker.cost_usd == 0.0
    assert "$0.00 (local)" in tracker.display()


def test_display_formats_numbers() -> None:
    tracker = UsageTracker()
    tracker.record({"input_tokens": 1842, "output_tokens": 904})
    display = tracker.display()
    assert display == "1,842 in / 904 out • $0.00 (local)"
