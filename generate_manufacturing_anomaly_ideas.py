#!/usr/bin/env python3
"""Build a disjoint reserve catalog for Manufacturing anomaly-detection tasks."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

PRODUCTS = [
    "bearing", "valve", "gearbox", "pump", "motor", "furnace", "reactor",
    "conveyor", "compressor", "turbine", "sensor", "actuator", "boiler",
    "catalyst", "battery", "panel", "molding", "welding", "coating", "packaging",
]
ANOMALIES = [
    ("lot-identity", "lot identifiers, genealogy, and release records"),
    ("supplier-origin", "supplier legal identity, facility, and origin records"),
    ("quantity-balance", "received, consumed, rejected, and released quantities"),
    ("date-sequence", "manufacture, inspection, shipment, and corrective-action dates"),
    ("certificate-scope", "certificate scope, revision, and applicability"),
    ("inspection-result", "inspection method, result, unit, and acceptance boundary"),
    ("deviation-closure", "deviation ownership, disposition, and closure evidence"),
    ("capa-effectiveness", "CAPA root cause, action, due date, and effectiveness evidence"),
    ("release-status", "quarantine, release, rework, and disposition status"),
    ("traceability-link", "links among lot, supplier, process, and CAPA records"),
]
DOMAINS = [
    "fda.gov", "ecfr.gov", "nist.gov", "osha.gov", "iso.org",
    "ema.europa.eu", "echa.europa.eu", "data.europa.eu",
]
WORKSTREAMS = [
    "reconstruct lot genealogy and detect identity, quantity, and date inconsistencies",
    "match supplier legal names, facilities, certificates, and ownership across records",
    "compare inspection, certificate, process, and disposition records using consistent units",
    "trace nonconformances to corrective and preventive actions without treating a closure date as proof of effectiveness",
    "separate clerical discrepancies, source conflicts, and safety-relevant anomalies",
    "verify the controlling manufacturing, quality, and reporting requirements on current public sources",
    "test source independence, superseded revisions, scope boundaries, and entity aliases",
    "preserve missing evidence and bounded uncertainty rather than inventing a lot or supplier conclusion",
    "classify each material finding as Anomaly confirmed, Reconciled, or Insufficient evidence",
    "recommend hold, release, rework, escalation, or CAPA reopening from the reconstructed evidence",
]


def make_idea(product: str, anomaly: str, description: str, index: int) -> dict:
    subject = f"{product} {anomaly.replace('-', ' ')}"
    archetypes = ["quality_engineering", "supplier_assurance", "operations", "regulatory_compliance"]
    return {
        "id": f"{product}-{anomaly}",
        "idea": (
            "Build an approximately 300-word live-web Manufacturing anomaly-detection specification "
            f"for a {subject} case. Require a structured analyst to reconcile {description}, "
            "identify lot, supplier, and corrective-action inconsistencies, and distinguish "
            "Anomaly confirmed, Reconciled, and Insufficient evidence. Require explicit abstention "
            "when the evidence cannot support a finding, exact inline URLs, and a hold, release, "
            "rework, escalation, or CAPA-reopening recommendation. Keep the hidden solution a "
            "dependency-graph, multi-hop investigation rather than a checklist."
        ),
        "scope": (
            "Manufacturing; anomaly detection across lot genealogy, supplier identity, inspection "
            "and certificate records, nonconformance, corrective and preventive action, release "
            "status, chronology, source conflicts, and bounded disposition decisions"
        ),
        "as_of": "2026-08-10",
        "requester_archetype": archetypes[index % len(archetypes)],
        "domain": "Manufacturing",
        "task_mode": "anomaly_detection",
        "instruction_shape": "around_300_word_structured_specification",
        "required_workstreams": [f"{subject}: {workstream}" for workstream in WORKSTREAMS],
        "authoritative_domains": DOMAINS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    ideas = [
        make_idea(product, anomaly, description, index)
        for index, product in enumerate(PRODUCTS)
        for anomaly, description in ANOMALIES
    ]
    if len(ideas) != 200 or len({item["id"] for item in ideas}) != 200:
        raise SystemExit("manufacturing catalog must contain 200 unique ideas")
    args.output_root.mkdir(parents=True, exist_ok=True)
    for name, shard in (("manufacturing-anomaly-a.yaml", ideas[:100]), ("manufacturing-anomaly-b.yaml", ideas[100:])):
        (args.output_root / name).write_text(
            yaml.safe_dump({"version": 1, "ideas": shard}, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
    print(f"wrote {len(ideas)} ideas in two disjoint 100-idea shards")


if __name__ == "__main__":
    main()
