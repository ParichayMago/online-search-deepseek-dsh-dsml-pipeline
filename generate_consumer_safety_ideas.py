#!/usr/bin/env python3
"""Create two disjoint, no-wrap Consumer Safety idea shards."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

WORKSTREAMS = [
    "consumer hazard and affected-population baseline",
    "controlling product, food, health, transport, or housing authority and dates",
    "reconstructing the eligible product, incident, market, or location population",
    "normalizing units, denominators, exposure windows, and scenario assumptions",
    "joining injury, exposure, reliability, cost, and distributional evidence",
    "testing manufacturer, retailer, platform, and regulator responsibilities",
    "modeling missing data, recalls, counterevidence, and compound failures",
    "ranking a bounded safety intervention portfolio with reversal triggers",
]

BASE_DOMAINS = [
    "cpsc.gov",
    "fda.gov",
    "ftc.gov",
    "cdc.gov",
    "epa.gov",
    "nih.gov",
    "usa.gov",
]

CASES = [
    ("baby-food-recall", "prioritize a response to contaminant recalls in infant food across testing, lot traceability, retailer notice, caregiver exposure, and replacement supply"),
    ("toy-choking-hazard", "reduce choking risk in toys sold across age bands, small parts, online listings, imports, recalls, and caregiver communication"),
    ("crib-sleep-safety", "compare crib and infant-sleep product interventions across entrapment evidence, labeling, resale channels, testing, and caregiver behavior"),
    ("stroller-brake-failure", "prioritize stroller brake-safety action across incident records, model aliases, standards, repairability, recalls, and secondhand sales"),
    ("car-seat-counterfeit", "detect and reduce counterfeit child restraints across marketplace listings, certification records, crash performance, enforcement, and disposal"),
    ("child-bike-helmet", "improve child bicycle-helmet safety across fit, certification, crash evidence, replacement intervals, counterfeits, and equitable access"),
    ("window-blind-strangulation", "choose window-covering interventions to reduce child strangulation across cord designs, housing stock, recalls, landlord duties, and installation"),
    ("furniture-tipover-prevention", "prioritize furniture tip-over prevention across incident populations, anchoring evidence, product redesign, rental housing, and enforcement"),
    ("playground-surface-safety", "rank playground surface and equipment upgrades across fall injury severity, accessibility, inspection records, climate wear, and maintenance budgets"),
    ("pool-drain-entrapment", "design a pool-drain entrapment prevention portfolio across drain inventories, circulation standards, inspection gaps, retrofit cost, and public access"),
    ("trampoline-injury-risk", "evaluate trampoline safety measures across injury surveillance, product design, supervision, insurance, warnings, and household adoption"),
    ("sunscreen-contamination", "respond to sunscreen contamination signals across benzene testing, lot scope, exposure pathways, recall timing, substitute products, and consumer notice"),
    ("cosmetics-allergen-labeling", "improve cosmetics allergen safety across ingredient identity, fragrance disclosure, adverse events, vulnerable users, imports, and enforcement"),
    ("hair-dryer-shock-risk", "reduce hair-dryer shock and fire risk across wet-location use, GFCI protection, incident patterns, product generations, and recall remedies"),
    ("cookware-coating-exposure", "assess cookware coating exposure claims across materials, temperature boundaries, migration evidence, labeling, alternatives, and household use"),
    ("laundry-pod-ingestion", "reduce laundry-pod ingestion and exposure across packaging, child access, poison-center trends, formulation, warnings, and retailer controls"),
    ("cleaning-product-mixing", "prevent hazardous household cleaning-product mixing across chemical pathways, label comprehension, ventilation, emergency response, and sales channels"),
    ("home-radon-mitigation", "prioritize household radon mitigation across mapped risk, test interpretation, building types, contractor quality, cost, and tenant protection"),
    ("smoke-alarm-replacement", "improve smoke-alarm reliability across sensing technology, nuisance alarms, replacement age, rental compliance, accessibility, and fire outcomes"),
    ("carbon-monoxide-detectors", "target carbon-monoxide detector deployment across appliance risks, testing limits, rental housing, power outages, language access, and response behavior"),
    ("space-heater-fire-risk", "reduce space-heater fire risk across product design, room conditions, incident patterns, recalls, winter energy burden, and safer alternatives"),
    ("gas-grill-leak", "address gas-grill leak hazards across connector failures, cylinder handling, recalls, weather exposure, retailer responsibility, and consumer repairs"),
    ("water-heater-scald", "prioritize water-heater scald prevention across temperature settings, plumbing variation, vulnerable residents, code exceptions, and retrofit affordability"),
    ("rental-housing-mold", "compare rental-housing mold interventions across moisture sources, health evidence, inspection thresholds, landlord duties, remediation quality, and displacement risk"),
    ("food-delivery-temperature", "improve food-delivery temperature safety across transit time, packaging, courier practices, pathogen growth windows, platform responsibility, and consumer remedies"),
    ("restaurant-allergen-control", "reduce restaurant allergen incidents across menu disclosure, kitchen controls, cross-contact evidence, staff training, inspection data, and reporting"),
    ("seafood-mercury-advisory", "design a seafood-mercury communication and market response across species identity, consumption guidance, exposure populations, substitutions, and fishing communities"),
    ("bottled-water-contamination", "prioritize bottled-water contamination controls across source approval, testing, lot traceability, recall speed, vulnerable consumers, and replacement supply"),
    ("supplement-adulteration-risk", "target dietary-supplement adulteration across ingredient claims, adverse events, import pathways, testing limits, advertising, and enforcement"),
    ("herbal-remedy-interactions", "improve herbal-remedy interaction safety across ingredient identity, evidence quality, medication populations, labeling, clinician communication, and retail claims"),
    ("overcounter-drug-recall", "manage over-the-counter drug recalls across manufacturing deviations, lot scope, pharmacy inventory, patient substitution, notification, and access continuity"),
    ("contact-lens-hygiene", "reduce contact-lens infection risk across solution claims, wear schedules, water exposure, user behavior, surveillance, and retailer education"),
    ("hearing-aid-battery", "prevent hearing-aid battery injuries across button-cell access, device generations, labeling, child exposure, disposal, and accessible design"),
    ("pet-food-recall", "respond to pet-food contamination recalls across pathogen evidence, lot distribution, animal vulnerability, retailer withdrawal, veterinary advice, and household exposure"),
    ("pesticide-residue-shopping", "help consumers manage pesticide-residue risk across commodity evidence, washing limits, organic claims, exposure groups, price, and supply substitutions"),
    ("lithium-battery-disposal", "reduce lithium-battery fire risk across damaged cells, collection systems, shipping rules, retailer take-back, consumer labeling, and waste-facility exposure"),
    ("resale-marketplace-trust", "govern resale-marketplace consumer safety across product authenticity, recalled goods, seller identity, returns, payment protection, and platform accountability"),
    ("subscription-cancellation", "protect consumers in recurring subscriptions across enrollment evidence, renewal notice, cancellation friction, dark patterns, refunds, and vulnerable users"),
    ("airline-refund-protection", "improve airline refund and disruption safety across cancellation records, ticket intermediaries, ancillary fees, accessibility, deadlines, and consumer recovery"),
    ("used-ev-consumer-protection", "improve used-EV consumer protection across battery-health disclosure, crash history, warranty scope, financing, repair access, resale claims, and fire risk"),
]


def make_idea(idea_id: str, decision: str, index: int) -> dict:
    subject = idea_id.replace("-", " ")
    archetypes = ["professional", "community", "general_user", "investigative", "neutral_exploratory"]
    return {
        "id": idea_id,
        "idea": (
            f"Build a compact 200-400 word live-web request for a real decision-maker who must {decision}. "
            "Make the hidden solution a dependency-graph, multi-hop research problem rather than a checklist. "
            "The final report must reconcile independent source families, perform bounded calculations, test a "
            "compound-failure scenario, and reach a conditional portfolio recommendation."
        ),
        "scope": f"Consumer Safety; target decision: {decision}; focus: incident evidence, exposure, authority, market actors, equity, remedies, and implementation risk",
        "as_of": "2026-08-01",
        "requester_archetype": archetypes[index % len(archetypes)],
        "domain": "Consumer Safety",
        "task_mode": "dependency_graph_multihop",
        "required_workstreams": [f"{subject}: {w}" for w in WORKSTREAMS],
        "authoritative_domains": BASE_DOMAINS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if len(CASES) != 40 or len({x[0] for x in CASES}) != 40:
        raise SystemExit("Consumer Safety catalog must contain 40 unique cases")
    ideas = [make_idea(a, b, i) for i, (a, b) in enumerate(CASES)]
    args.output_root.mkdir(parents=True, exist_ok=True)
    for name, shard in (("consumer-safety-a.yaml", ideas[:20]), ("consumer-safety-b.yaml", ideas[20:])):
        (args.output_root / name).write_text(
            yaml.safe_dump({"version": 1, "ideas": shard}, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
    print(f"wrote {len(ideas)} ideas in two disjoint 20-idea shards")


if __name__ == "__main__":
    main()
