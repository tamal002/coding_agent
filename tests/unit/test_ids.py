"""Tests for the shared id helpers (thread ids, run ids)."""

from __future__ import annotations

import re

import pytest

from agent.infra.ids import (
    ID_PATTERN,
    assert_valid_id,
    new_run_id,
    new_thread_id,
)


def test_new_thread_id_matches_shared_pattern() -> None:
    thread_id = new_thread_id("tui")
    assert ID_PATTERN.fullmatch(thread_id), thread_id
    assert thread_id.startswith("tui-")
    # caller prefix stays readable and ids stay unique enough per call
    assert new_thread_id("run") != new_thread_id("run")


def test_new_run_id_is_short_and_prefixed() -> None:
    run_id = new_run_id()
    assert run_id.startswith("r-")
    assert len(run_id) <= 16


@pytest.mark.parametrize(
    "bad",
    ["", "has space", "way-too-long-" + "x" * 60, "slash/semantic"],
)
def test_assert_valid_id_rejects_bad_values(bad: str) -> None:
    with pytest.raises(ValueError):
        assert_valid_id(bad)


def test_assert_valid_id_passes_generated_ids() -> None:
    """Generated ids never raise; the helper returns its input unchanged."""
    thread_id = new_thread_id("cli")
    assert assert_valid_id(thread_id) == thread_id
    assert_valid_id(new_run_id())


def test_pattern_is_the_thread_id_contract_regex() -> None:
    # The locked convention: ^[A-Za-z0-9_-]{1,64}$ (plan section 2.1).
    assert ID_PATTERN.pattern == r"^[A-Za-z0-9_-]{1,64}$"
    assert re.fullmatch(ID_PATTERN, "aA0-_")
