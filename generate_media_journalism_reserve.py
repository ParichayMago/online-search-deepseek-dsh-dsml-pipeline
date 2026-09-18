#!/usr/bin/env python3
"""Create reserve shards for the Media and journalism verification campaign."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from generate_media_journalism_ideas import CASES, make_idea

RESERVE_CASES = [
    ("agency-report-revision", "verify a reported agency finding across draft, final, and corrected releases"),
    ("municipal-audit-finding", "verify a municipal audit claim across findings, responses, and remediation records"),
    ("court-docket-timeline", "verify a litigation timeline across filings, orders, service, and docket updates"),
    ("charity-fund-disbursement", "verify a charity disbursement claim across pledges, intermediaries, recipients, and dates"),
    ("union-contract-claim", "verify a labor-contract claim across proposals, ratification, side letters, and effective dates"),
    ("permit-approval-status", "verify whether a permit is proposed, issued, appealed, suspended, or operative"),
    ("inspection-score-comparison", "verify an inspection-score comparison across schemes, facilities, dates, and corrections"),
    ("hospital-capacity-statistic", "verify a hospital-capacity claim across licensed, staffed, occupied, and available beds"),
    ("vaccine-coverage-claim", "verify a vaccination-coverage claim across populations, doses, geography, and reporting dates"),
    ("mortality-rate-comparison", "verify a mortality-rate comparison across causes, age adjustment, populations, and periods"),
    ("school-closure-timeline", "verify a school-closure timeline across announcements, orders, appeals, and reopening records"),
    ("university-funding-claim", "verify a university-funding claim across awards, obligations, expenditures, and restrictions"),
    ("library-ban-statistic", "verify a library-ban statistic across challenges, removals, titles, districts, and periods"),
    ("police-policy-change", "verify whether a reported police-policy change is proposed, adopted, trained, and effective"),
    ("fire-incident-timeline", "verify a fire-incident chronology across dispatch, response, containment, and investigation records"),
    ("bridge-closure-cause", "verify a bridge-closure explanation across inspections, orders, engineering findings, and updates"),
    ("train-delay-statistic", "verify a train-delay statistic across routes, operators, causes, cancellations, and periods"),
    ("airport-delay-cause", "verify an airport-delay attribution across weather, traffic controls, carriers, and timestamps"),
    ("shipping-delay-claim", "verify a shipping-delay claim across vessels, ports, schedules, disruptions, and time zones"),
    ("utility-outage-timeline", "verify a utility-outage timeline across incident reports, restoration estimates, and revisions"),
    ("power-plant-closure", "verify a power-plant closure claim across announcements, regulatory approvals, and operating data"),
    ("pipeline-spill-volume", "verify a pipeline-spill volume across estimates, recovered material, revisions, and units"),
    ("mining-permit-status", "verify a mining-permit status across agencies, stages, conditions, appeals, and expiration dates"),
    ("forest-loss-statistic", "verify a forest-loss statistic across datasets, definitions, baselines, and geographic boundaries"),
    ("glacier-retreat-comparison", "verify a glacier-retreat comparison across observation methods, endpoints, and time windows"),
    ("drought-reservoir-level", "verify a drought reservoir claim across gauges, capacity definitions, dates, and revisions"),
    ("storm-damage-estimate", "verify a storm-damage estimate across preliminary, insured, public, and final assessments"),
    ("heat-record-attribution", "verify a heat-record and attribution claim across stations, corrections, and attribution evidence"),
    ("air-quality-ranking", "verify an air-quality ranking across pollutants, monitors, averaging periods, and missing data"),
    ("emissions-inventory-claim", "verify an emissions-inventory claim across sectors, scopes, years, methods, and revisions"),
    ("food-price-comparison", "verify a food-price comparison across baskets, outlets, geography, inflation, and periods"),
    ("rent-growth-statistic", "verify a rent-growth statistic across asking and paid rents, units, geographies, and dates"),
    ("wage-growth-headline", "verify a wage-growth headline across worker populations, inflation, composition, and revisions"),
    ("tax-revenue-claim", "verify a tax-revenue claim across collections, accruals, forecasts, refunds, and fiscal periods"),
    ("public-debt-comparison", "verify a public-debt comparison across gross and net measures, currencies, and dates"),
    ("grant-award-status", "verify whether a grant was announced, awarded, obligated, disbursed, or terminated"),
    ("procurement-bid-protest", "verify a procurement outcome across solicitation, award, protest, decision, and performance"),
    ("infrastructure-cost-overrun", "verify an infrastructure overrun across approved baselines, scope changes, and forecasts"),
    ("project-completion-timeline", "verify a project-completion claim across milestones, contractual dates, and operational status"),
    ("zoning-change-claim", "verify a zoning-change claim across proposals, hearings, votes, maps, and effective dates"),
    ("eviction-rate-comparison", "verify an eviction-rate comparison across filings, judgments, households, and periods"),
    ("homelessness-count-revision", "verify a homelessness-count headline across methods, populations, geography, and revisions"),
    ("prison-population-statistic", "verify a prison-population statistic across custody types, facilities, dates, and revisions"),
    ("parole-policy-claim", "verify a parole-policy claim across rule text, eligibility, implementation, and court limits"),
    ("border-encounter-statistic", "verify a border-encounter statistic across events, people, sectors, and reporting periods"),
    ("asylum-backlog-claim", "verify an asylum-backlog claim across agencies, case stages, applications, and dates"),
    ("visa-processing-delay", "verify a visa-processing delay across posts, categories, measurement methods, and dates"),
    ("passport-wait-claim", "verify a passport wait-time claim across service levels, processing boundaries, and updates"),
    ("mail-delivery-statistic", "verify a mail-delivery statistic across products, standards, measurement periods, and regions"),
    ("broadband-coverage-claim", "verify a broadband-coverage claim across availability, adoption, speed tiers, and map vintages"),
    ("internet-outage-cause", "verify an internet-outage attribution across providers, routing evidence, timing, and recovery"),
    ("satellite-launch-status", "verify a satellite-launch status across manifests, launch records, deployment, and orbit data"),
    ("space-mission-anomaly", "verify a space-mission anomaly claim across telemetry summaries, updates, and mission outcomes"),
    ("aviation-incident-cause", "verify what is established about an aviation incident cause before investigation completion"),
    ("maritime-collision-timeline", "verify a maritime-collision timeline across vessel identities, tracks, reports, and time zones"),
    ("rail-safety-claim", "verify a rail-safety claim across incident definitions, exposure measures, and reporting periods"),
    ("vehicle-defect-investigation", "verify a vehicle-defect claim across complaints, investigations, recalls, and remedies"),
    ("drug-approval-status", "verify a drug-approval claim across indications, pathways, labeling, and effective dates"),
    ("clinical-trial-result", "verify a clinical-trial headline across endpoints, populations, analyses, and registry updates"),
    ("disease-surveillance-trend", "verify a disease-surveillance trend across definitions, reporting delays, and revisions"),
    ("hospital-closure-claim", "verify a hospital-closure claim across services, licensing, ownership, and effective dates"),
    ("insurance-denial-statistic", "verify an insurance-denial statistic across request types, populations, and appeal outcomes"),
    ("medical-device-alert", "verify a medical-device alert across models, lots, geographies, risk, and recall status"),
    ("nutrition-study-headline", "verify whether a nutrition study supports its reported population, effect, and certainty"),
    ("water-contaminant-level", "verify a contaminant-level claim across samples, methods, units, thresholds, and dates"),
    ("foodborne-outbreak-source", "verify an outbreak-source claim across cases, exposures, traceback, and agency confidence"),
    ("restaurant-closure-cause", "verify a restaurant-closure report across inspections, orders, ownership, and reopening"),
    ("consumer-complaint-trend", "verify a consumer-complaint trend across categories, duplicates, populations, and periods"),
    ("fraud-loss-statistic", "verify a fraud-loss statistic across reports, victims, recoveries, categories, and years"),
    ("bank-failure-timeline", "verify a bank-failure timeline across closure, receivership, acquisition, and depositor access"),
    ("interest-rate-claim", "verify an interest-rate claim across target, effective, lending, and inflation-adjusted measures"),
    ("currency-intervention-report", "verify a currency-intervention report across authorities, transactions, dates, and evidence"),
    ("trade-deficit-comparison", "verify a trade-deficit comparison across goods, services, adjustments, and revisions"),
    ("tariff-effective-date", "verify a tariff effective date across announcement, legal publication, exceptions, and amendments"),
    ("export-ban-scope", "verify an export-ban claim across products, destinations, exemptions, and effective periods"),
    ("company-ownership-chain", "verify a company-ownership chain across subsidiaries, control, dates, and filings"),
    ("executive-compensation-claim", "verify an executive-compensation claim across pay definitions, years, and filings"),
    ("share-buyback-statistic", "verify a share-buyback statistic across authorization, execution, value, and share counts"),
    ("pension-funding-status", "verify a pension-funding claim across valuation dates, assumptions, assets, and liabilities"),
    ("labor-productivity-headline", "verify a productivity headline across output, hours, sectors, adjustments, and revisions"),
    ("patent-ownership-claim", "verify a patent-ownership claim across inventorship, assignment, entity, and current status"),
    ("copyright-ruling-scope", "verify the scope of a copyright ruling across claims, holdings, remedies, and appeals"),
    ("antitrust-case-status", "verify an antitrust-case status across complaints, rulings, settlements, and appeals"),
    ("privacy-law-deadline", "verify a privacy-law deadline across enactment, effectiveness, rulemaking, and extensions"),
    ("content-removal-statistic", "verify a content-removal statistic across requests, items, actions, and reporting periods"),
    ("algorithm-bias-claim", "verify an algorithm-bias claim across populations, benchmarks, versions, and limitations"),
    ("ai-benchmark-headline", "verify an AI benchmark headline across model versions, tasks, settings, and independent results"),
    ("research-funding-source", "verify a research-funding claim across grants, institutions, investigators, and disclosures"),
    ("journal-correction-status", "verify whether a paper is corrected, retracted, withdrawn, or under editorial review"),
    ("scientific-consensus-claim", "verify a scientific-consensus claim across review scope, expert population, and date"),
    ("museum-art-provenance", "verify an artwork-provenance claim across custody, sale, restitution, and attribution records"),
    ("heritage-listing-status", "verify a heritage-listing claim across nomination, inscription, boundaries, and risk status"),
    ("film-revenue-comparison", "verify a film-revenue comparison across markets, currencies, release windows, and sources"),
    ("music-chart-claim", "verify a music-chart claim across chart editions, metrics, territories, and eligibility rules"),
    ("book-sales-ranking", "verify a book-sales ranking across lists, formats, markets, periods, and stated methodology"),
    ("sports-record-revision", "verify a sports-record claim across governing records, sanctions, corrections, and dates"),
    ("athlete-eligibility-status", "verify an athlete-eligibility report across rules, decisions, appeals, and effective dates"),
    ("match-attendance-statistic", "verify a match-attendance statistic across tickets, turnstile counts, capacity, and reports"),
    ("tourism-arrival-claim", "verify a tourism-arrival claim across visitors, trips, borders, periods, and revisions"),
    ("festival-crowd-estimate", "verify a festival crowd estimate across methods, areas, time windows, and official updates"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    original_ids = {idea_id for idea_id, _ in CASES}
    reserve_ids = [idea_id for idea_id, _ in RESERVE_CASES]
    if len(RESERVE_CASES) != 100 or len(set(reserve_ids)) != 100:
        raise SystemExit("reserve catalog must contain 100 unique cases")
    if original_ids.intersection(reserve_ids):
        raise SystemExit("reserve catalog overlaps the original catalog")
    if any(len(idea_id.split("-")) != 3 for idea_id in reserve_ids):
        raise SystemExit("every reserve task ID must contain three words")
    ideas = [
        make_idea(idea_id, decision, index + len(CASES))
        for index, (idea_id, decision) in enumerate(RESERVE_CASES)
    ]
    args.output_root.mkdir(parents=True, exist_ok=True)
    for name, shard in (
        ("media-journalism-reserve-a.yaml", ideas[:50]),
        ("media-journalism-reserve-b.yaml", ideas[50:]),
    ):
        (args.output_root / name).write_text(
            yaml.safe_dump(
                {"version": 1, "ideas": shard},
                sort_keys=False,
                allow_unicode=True,
                width=100,
            ),
            encoding="utf-8",
        )
    print(f"wrote {len(ideas)} reserve ideas in two disjoint 50-idea shards")


if __name__ == "__main__":
    main()
