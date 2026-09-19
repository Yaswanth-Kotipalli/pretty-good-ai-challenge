"""Tests for the dial safety guardrail (offline, no network)."""
import pytest

from pgai_challenge.config import (
    ASSESSMENT_NUMBER,
    UnsafeDialError,
    assert_safe_to_dial,
)


def test_allows_assessment_line():
    assert_safe_to_dial(ASSESSMENT_NUMBER)  # must not raise


def test_blocks_other_numbers():
    with pytest.raises(UnsafeDialError):
        assert_safe_to_dial("+15551234567")


def test_blocks_empty_string():
    with pytest.raises(UnsafeDialError):
        assert_safe_to_dial("")


def test_blocks_similar_looking_number():
    # off-by-one-digit must not slip through
    with pytest.raises(UnsafeDialError):
        assert_safe_to_dial("+18054398009")


def test_allows_approved_test_number():
    test_number = "+15551234567"
    assert_safe_to_dial(test_number, allowed_test_number=test_number)  # must not raise


def test_blocks_unapproved_when_different_test_number_specified():
    with pytest.raises(UnsafeDialError):
        assert_safe_to_dial("+15559999999", allowed_test_number="+15551234567")

