#!/usr/bin/env python3
"""Thin grading entrypoint shared byte-for-byte by every online task."""

from test_utils import run


def test_report() -> None:
    """Let no-Compose solver harnesses invoke the same verifier via pytest."""
    assert run() == 0


if __name__ == "__main__":
    raise SystemExit(run())
