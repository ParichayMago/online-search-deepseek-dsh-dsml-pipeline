#!/usr/bin/env python3
"""Create two disjoint Media and journalism verification idea shards."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

WORKSTREAMS = [
    "decomposing the submitted assertion into falsifiable material claims",
    "tracing each claim to the earliest stable primary record",
    "testing source independence, syndication, and circular reporting",
    "resolving entity, location, timestamp, jurisdiction, and version identity",
    "normalizing quoted numbers, populations, denominators, and time windows",
    "checking provenance and context separately from content authenticity",
    "seeking credible counterevidence and preserving unresolved boundaries",
    "assigning Supported, Contradicted, or Insufficient evidence and deciding publish, hold, correct, or retract",
]

STARTING_DOMAINS = [
    "apnews.com",
    "reuters.com",
    "govinfo.gov",
    "archives.gov",
    "courtlistener.com",
    "sec.gov",
]

CASES = [
    ("breaking-news-casualty", "verify competing casualty claims before a breaking-news alert"),
    ("conflict-footage-origin", "verify where and when conflict footage was recorded before broadcast"),
    ("election-result-claim", "verify a claimed election result before calling a race"),
    ("disaster-image-context", "verify whether disaster images depict the named event and date"),
    ("public-health-quote", "verify a disputed public-health quotation before publication"),
    ("corporate-document-leak", "verify the authenticity and meaning of a purported corporate leak"),
    ("climate-graphic-claim", "verify a viral climate graphic and its underlying dataset"),
    ("protest-video-context", "verify the location, chronology, and caption of protest video"),
    ("war-damage-geolocation", "verify a claimed strike location from independent public evidence"),
    ("manipulated-audio-claim", "verify whether circulated audio supports its attributed speaker and context"),
    ("synthetic-interview-clip", "verify a purported interview clip before rebroadcast"),
    ("quotation-attribution-chain", "verify a quotation whose attribution passes through several publications"),
    ("anonymous-source-corroboration", "decide whether nominally separate reports independently corroborate an anonymous claim"),
    ("government-data-revision", "verify a headline after an official dataset revision"),
    ("court-filing-allegation", "verify what a court filing alleges versus what the record establishes"),
    ("study-headline-causality", "verify whether a study supports a causal news headline"),
    ("crime-statistics-comparison", "verify a cross-city crime trend claim with comparable definitions"),
    ("celebrity-death-rumor", "verify a viral death report without amplifying unsupported claims"),
    ("recall-news-alert", "verify the product, lot, geography, and status in a recall alert"),
    ("earnings-headline-claim", "verify a company performance headline across filings and revisions"),
    ("campaign-ad-factcheck", "verify the material factual claims in a campaign advertisement"),
    ("ballot-rule-explainer", "verify a time-sensitive ballot-rule claim in the controlling jurisdiction"),
    ("polling-aggregation-claim", "verify a polling trend after deduplicating samples and field dates"),
    ("immigration-statistic-claim", "verify a migration statistic across incompatible populations and periods"),
    ("school-policy-rumor", "verify a local school-policy rumor against the operative record"),
    ("local-budget-claim", "verify a local budget claim across proposal, amendment, and adoption stages"),
    ("spill-footage-verification", "verify footage and impact claims about an environmental spill"),
    ("weather-record-claim", "verify a claimed weather record against station and revision boundaries"),
    ("sports-integrity-allegation", "verify a sports-integrity allegation without treating repetition as corroboration"),
    ("aid-delivery-claim", "verify a humanitarian-aid delivery claim across sender, recipient, and timing records"),
    ("historical-photo-caption", "verify the date, place, and subject in a historical photograph caption"),
    ("satellite-image-interpretation", "verify what a satellite image can and cannot establish"),
    ("platform-trend-claim", "verify a claimed social-platform trend despite incomplete public measurement"),
    ("embargoed-release-claim", "verify an embargoed press-release claim against the underlying record"),
    ("translated-statement-meaning", "verify a translated public statement and material contextual alternatives"),
    ("document-date-authenticity", "verify the date, version, and completeness of a circulated document"),
    ("data-visualization-claim", "verify a news visualization's denominator, exclusions, and visual conclusion"),
    ("source-identity-impersonation", "verify whether a source account or document represents the claimed institution"),
    ("correction-retraction-decision", "decide whether new evidence warrants a correction, retraction, update, or abstention"),
    ("newsroom-publish-hold", "make a publish-or-hold decision for a mixed-evidence investigative claim set"),
    ("ceasefire-map-caption", "verify a ceasefire map caption against controlling dates, boundaries, and agreements"),
    ("wildfire-evacuation-claim", "verify a wildfire evacuation claim across orders, zones, timestamps, and later revisions"),
    ("dam-collapse-video", "verify whether circulated video depicts the claimed dam failure, location, and date"),
    ("earthquake-magnitude-revision", "verify an earthquake magnitude headline after agency and solution revisions"),
    ("epidemic-case-count", "verify an epidemic case-count claim across reporting dates, definitions, and revisions"),
    ("medication-shortage-report", "verify a medication shortage report across manufacturers, regulators, products, and dates"),
    ("research-preprint-claim", "verify whether a preprint supports a reported finding and its stated certainty"),
    ("deepfake-press-conference", "verify the provenance and content of a purported press-conference recording"),
    ("legislative-vote-claim", "verify a legislative vote claim across chambers, amendments, motions, and timestamps"),
    ("executive-order-scope", "verify the operative scope of an executive order across text, amendments, and guidance"),
    ("sanctions-list-identity", "verify whether a named person or entity matches a sanctions-list record"),
    ("military-unit-casualty", "verify a military-unit casualty claim across announcements, identities, and reporting windows"),
    ("refugee-crossing-statistic", "verify a refugee-crossing statistic across routes, populations, agencies, and periods"),
    ("food-shortage-photograph", "verify whether a photograph supports a reported food-shortage location and timeframe"),
    ("police-bodycam-chronology", "verify a reported incident chronology against released body-camera and official records"),
    ("weather-radar-interpretation", "verify what a weather-radar image establishes about a reported severe event"),
    ("wildfire-smoke-attribution", "verify a smoke-attribution claim across observations, transport models, and fire records"),
    ("energy-price-comparison", "verify an energy-price comparison across products, taxes, geographies, and time windows"),
    ("unemployment-rate-headline", "verify an unemployment headline across definitions, seasonal adjustments, and revisions"),
    ("inflation-basket-claim", "verify an inflation claim across baskets, populations, base periods, and releases"),
    ("campaign-finance-donation", "verify a campaign-finance donation claim across filers, committees, refunds, and amendments"),
    ("lobbying-disclosure-claim", "verify a lobbying claim across registrations, reports, clients, issues, and periods"),
    ("nonprofit-funding-network", "verify a reported nonprofit funding network without double-counting intermediaries"),
    ("property-record-ownership", "verify a property-ownership claim across parcels, entities, dates, and controlling records"),
    ("vessel-tracking-claim", "verify a vessel-location claim across identifiers, tracking gaps, ports, and timestamps"),
    ("aircraft-path-allegation", "verify an aircraft-path allegation across registrations, tracks, time zones, and limitations"),
    ("wildfire-origin-rumor", "verify a wildfire-origin rumor against investigations, incident records, and unresolved evidence"),
    ("flood-map-claim", "verify a flood-map claim across map vintages, modeled zones, observations, and jurisdiction"),
    ("water-quality-alert", "verify a water-quality alert across analytes, samples, thresholds, areas, and effective dates"),
    ("election-turnout-comparison", "verify an election-turnout comparison across eligible populations, ballots, and certification stages"),
    ("polling-sample-overlap", "verify a polling trend after resolving shared panels, sponsors, field dates, and populations"),
    ("legislative-text-amendment", "verify whether reported legislative language survived amendments and final passage"),
    ("regulatory-deadline-report", "verify a regulatory deadline across publication, effectiveness, compliance, and extension records"),
    ("press-photo-provenance", "verify a press photograph's creator, capture context, distribution chain, and caption"),
    ("livestream-chronology-claim", "verify a livestream chronology across upload times, time zones, edits, and independent records"),
    ("obituary-identity-match", "verify an obituary identity match without conflating namesakes or recycled notices"),
    ("academic-credential-claim", "verify an academic credential claim across institutions, programs, dates, and official records"),
    ("expert-affiliation-disclosure", "verify a quoted expert's relevant affiliations, funding, roles, and disclosure timing"),
    ("conflict-map-boundary", "verify a conflict-control map claim across dates, definitions, sources, and uncertainty"),
    ("detention-facility-image", "verify whether imagery depicts the claimed detention facility, conditions, and date"),
    ("aid-convoy-footage", "verify aid-convoy footage across vehicles, route, custody, timing, and delivery evidence"),
    ("hospital-attack-claim", "verify a hospital-attack claim across geolocation, chronology, damage, and attribution evidence"),
    ("cultural-site-damage", "verify reported cultural-site damage across identity, imagery, assessments, and dates"),
    ("commodity-export-claim", "verify a commodity-export claim across units, destinations, customs periods, and revisions"),
    ("labor-strike-participation", "verify a strike-participation claim across bargaining units, locations, shifts, and dates"),
    ("corporate-layoff-count", "verify a corporate layoff count across notices, geographies, subsidiaries, and announcements"),
    ("merger-approval-status", "verify a merger-approval headline across jurisdictions, conditions, appeals, and closing"),
    ("bankruptcy-filing-claim", "verify what a bankruptcy filing establishes about entities, liabilities, and procedural status"),
    ("cyberattack-attribution-claim", "verify the evidentiary basis and uncertainty behind a cyberattack attribution claim"),
    ("data-breach-scale", "verify a data-breach scale claim across incidents, records, people, notices, and revisions"),
    ("platform-account-authenticity", "verify whether a platform account represents its claimed person or institution"),
    ("deleted-post-reconstruction", "verify the content, author, timestamp, and context of a reportedly deleted post"),
    ("podcast-quotation-context", "verify a podcast quotation against the recording, transcript, edits, and surrounding context"),
    ("transcript-editing-claim", "verify whether transcript edits materially changed a reported statement's meaning"),
    ("archival-record-quotation", "verify an archival quotation across document identity, version, transcription, and context"),
    ("census-population-claim", "verify a population claim across census products, geographies, universes, and vintages"),
    ("housing-price-comparison", "verify a housing-price comparison across property types, geographies, statistics, and periods"),
    ("school-enrollment-statistic", "verify a school-enrollment statistic across institutions, grades, dates, and reporting systems"),
    ("transit-ridership-claim", "verify a transit-ridership claim across modes, agencies, periods, and revised totals"),
    ("public-contract-award", "verify a public-contract award claim across solicitation, selection, protest, and execution stages"),
]


def make_idea(idea_id: str, decision: str, index: int) -> dict:
    subject = idea_id.replace("-", " ")
    archetypes = ["investigative", "professional", "community", "neutral_exploratory"]
    return {
        "id": idea_id,
        "idea": (
            "Build an exact 120-word live-web newsroom micro-contract requiring a verifier to "
            f"{decision}. Require Supported, Contradicted, or Insufficient evidence for each "
            "material claim, explicit abstention when support is insufficient, exact inline URLs, "
            "and a publish/hold/correct/retract recommendation. Keep the hidden solution a "
            "dependency-graph, multi-hop verification problem rather than a checklist."
        ),
        "scope": (
            f"Media and journalism; verification decision: {decision}; focus: provenance, "
            "source independence, chronology, quantitative normalization, counterevidence, "
            "uncertainty, abstention, and editorial consequence"
        ),
        "as_of": "2026-08-01",
        "requester_archetype": archetypes[index % len(archetypes)],
        "domain": "Media and journalism",
        "task_mode": "verification_and_abstention",
        "instruction_shape": "exact_120_word_micro_contract",
        "required_workstreams": [f"{subject}: {workstream}" for workstream in WORKSTREAMS],
        "authoritative_domains": STARTING_DOMAINS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if len(CASES) != 100 or len({idea_id for idea_id, _ in CASES}) != 100:
        raise SystemExit("Media and journalism catalog must contain 100 unique cases")
    if any(len(idea_id.split("-")) != 3 for idea_id, _ in CASES):
        raise SystemExit("every Media and journalism task ID must contain three words")
    ideas = [make_idea(idea_id, decision, index) for index, (idea_id, decision) in enumerate(CASES)]
    args.output_root.mkdir(parents=True, exist_ok=True)
    for name, shard in (
        ("media-journalism-a.yaml", ideas[:50]),
        ("media-journalism-b.yaml", ideas[50:]),
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
    print(f"wrote {len(ideas)} ideas in two disjoint 50-idea shards")


if __name__ == "__main__":
    main()
