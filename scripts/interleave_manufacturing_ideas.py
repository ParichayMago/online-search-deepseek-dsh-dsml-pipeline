#!/usr/bin/env python3
"""Interleave manufacturing seed families to avoid correlated concurrent work."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import yaml


def interleave(ideas: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for idea in ideas:
        groups[str(idea["id"]).split("-", 1)[0]].append(idea)
    result = []
    for offset in range(max(map(len, groups.values()), default=0)):
        for family in groups.values():
            if offset < len(family):
                result.append(family[offset])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    ideas = []
    for path in args.inputs:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        ideas.extend(payload["ideas"])
    result = interleave(ideas)
    ids = [str(idea["id"]) for idea in result]
    if not result or len(ids) != len(set(ids)):
        raise SystemExit("manufacturing seeds must be nonempty and unique")
    args.output.write_text(
        yaml.safe_dump({"version": 1, "ideas": result}, sort_keys=False, width=100),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
