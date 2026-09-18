#!/usr/bin/env python3
"""Build the default Online Search catalog from allowed taxonomy domains."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict, deque
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def normalized_domain(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def load_taxonomy(path: Path) -> tuple[list[str], set[str], dict]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "online-search-domain-taxonomy-v1":
        raise ValueError("unsupported domain taxonomy schema")
    allowed = payload.get("allowed_domains")
    forbidden = payload.get("forbidden_domains")
    if not isinstance(allowed, list) or not allowed:
        raise ValueError("taxonomy allowed_domains must be nonempty")
    if not isinstance(forbidden, list) or not forbidden:
        raise ValueError("taxonomy forbidden_domains must be nonempty")
    normalized_allowed = [normalized_domain(value) for value in allowed]
    if len(normalized_allowed) != len(set(normalized_allowed)):
        raise ValueError("taxonomy contains duplicate allowed domains")
    catalog = payload.get("default_catalog")
    if not isinstance(catalog, dict):
        raise TypeError("taxonomy default_catalog must be an object")
    return (
        [str(value) for value in allowed],
        {normalized_domain(value) for value in forbidden},
        catalog,
    )


def forbidden_match(domain: str, forbidden: set[str]) -> bool:
    normalized = normalized_domain(domain)
    return any(
        normalized == blocked
        or normalized.startswith(blocked + " ")
        or normalized.endswith(" " + blocked)
        for blocked in forbidden
    )


def load_sources(paths: list[Path], allowed: list[str], forbidden: set[str]) -> list[dict]:
    canonical = {normalized_domain(value): value for value in allowed}
    seen: set[str] = set()
    seen_source_ids: set[str] = set()
    ideas: list[dict] = []
    for path in paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        rows = payload.get("ideas") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise TypeError(f"idea source has no ideas list: {path}")
        for raw in rows:
            if not isinstance(raw, dict):
                raise TypeError(f"idea row must be an object: {path}")
            domain = str(raw.get("domain") or "")
            normalized = normalized_domain(domain)
            if forbidden_match(domain, forbidden):
                continue
            if normalized not in canonical:
                raise ValueError(f"unknown domain {domain!r} in {path}")
            source_id = str(raw.get("id") or "")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", source_id):
                raise ValueError(f"idea ID must be a slug: {source_id!r}")
            if source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            parts = source_id.split("-")
            idea_id = "-".join(parts[:3] if len(parts) >= 3 else [*parts, "review"])
            if idea_id in seen:
                raise ValueError(
                    f"three-word ID collision {idea_id!r} derived from {source_id!r}"
                )
            seen.add(idea_id)
            # The builder sees the seed. Remove source whitelists and default
            # cutoff hints so they cannot leak into the authored instruction.
            row = {
                key: value
                for key, value in raw.items()
                if key not in {"authoritative_domains", "as_of"}
            }
            row["id"] = idea_id
            row["domain"] = canonical[normalized]
            ideas.append(row)
    return ideas


def round_robin(
    ideas: list[dict], allowed: list[str], *, max_tasks_per_domain: int
) -> list[dict]:
    grouped: dict[str, deque[dict]] = defaultdict(deque)
    for idea in ideas:
        grouped[str(idea["domain"])].append(idea)
    for domain, queue in list(grouped.items()):
        grouped[domain] = deque(list(queue)[:max_tasks_per_domain])
    ordered: list[dict] = []
    while grouped:
        progressed = False
        for domain in allowed:
            queue = grouped.get(domain)
            if not queue:
                continue
            ordered.append(queue.popleft())
            progressed = True
            if not queue:
                del grouped[domain]
        if not progressed:
            raise AssertionError("round-robin catalog made no progress")
    return ordered


def write_catalog(path: Path, ideas: list[dict]) -> None:
    path.write_text(
        yaml.safe_dump(
            {"version": 1, "ideas": ideas},
            sort_keys=False,
            allow_unicode=True,
            width=100,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, default=ROOT / "domain-taxonomy.yaml")
    parser.add_argument("--output", type=Path, default=ROOT / "ideas.yaml")
    parser.add_argument("--reserve-output", type=Path, default=ROOT / "ideas-reserve.yaml")
    parser.add_argument("--reserve-every", type=int, default=5)
    args = parser.parse_args()
    if args.reserve_every < 2:
        raise SystemExit("--reserve-every must be at least 2")
    allowed, forbidden, catalog = load_taxonomy(args.taxonomy)
    globs = catalog.get("source_globs")
    if not isinstance(globs, list) or not globs:
        raise SystemExit("taxonomy default_catalog.source_globs must be nonempty")
    sources = sorted(
        {
            path
            for pattern in globs
            for path in ROOT.glob(str(pattern))
            if path.is_file()
        }
    )
    if not sources:
        raise SystemExit("no ideaN.yaml taxonomy sources found")
    eligible = load_sources(sources, allowed, forbidden)
    max_tasks = int(catalog.get("max_tasks_per_domain", 25))
    if max_tasks < 1:
        raise SystemExit("taxonomy max_tasks_per_domain must be positive")
    ordered = round_robin(
        eligible,
        allowed,
        max_tasks_per_domain=max_tasks,
    )
    primary = [row for index, row in enumerate(ordered, 1) if index % args.reserve_every]
    reserve = [row for index, row in enumerate(ordered, 1) if not index % args.reserve_every]
    write_catalog(args.output, primary)
    write_catalog(args.reserve_output, reserve)
    print(
        yaml.safe_dump(
            {
                "sources": len(sources),
                "eligible": len(eligible),
                "selected": len(ordered),
                "primary": len(primary),
                "reserve": len(reserve),
                "domains": sorted({row["domain"] for row in ordered}),
            },
            sort_keys=False,
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
