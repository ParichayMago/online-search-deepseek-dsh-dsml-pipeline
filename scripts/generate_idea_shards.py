#!/usr/bin/env python3
"""Generate the canonical 220-idea catalog and eleven disjoint shards."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-07-01"


PROFILES = [
    {
        "slug": "health-healthcare",
        "scope": "United States health policy, public-health, and healthcare operations",
        "audience": "a multi-agency health planning coalition",
        "workstreams": [
            "burden, incidence, and trend measurement",
            "population eligibility, disparities, and access",
            "clinical or operational effectiveness evidence",
            "capacity, workforce, and implementation constraints",
            "federal, state, and local authority",
            "coverage, reimbursement, and affordability",
            "supply continuity and infrastructure resilience",
            "scenario calculations and threshold design",
            "harms, counterevidence, and uncertainty boundaries",
            "phased implementation, monitoring, and reassessment",
        ],
        "domains": ["cdc.gov", "hhs.gov", "cms.gov", "nih.gov", "ahrq.gov", "fda.gov", "who.int"],
        "cases": [
            ("hospital-respiratory-surge-readiness", "prepare a regional hospital network for a severe respiratory-disease surge"),
            ("state-antimicrobial-resistance-portfolio", "allocate a five-year state antimicrobial-resistance budget across surveillance, laboratories, stewardship, and outbreak response"),
            ("maternal-care-desert-response", "reduce maternal-care access failures across rural and underserved counties"),
            ("rural-emergency-access-redesign", "redesign rural emergency and trauma access without destabilizing essential hospitals"),
            ("behavioral-crisis-continuum", "build a behavioral-health crisis continuum spanning call centers, mobile response, emergency departments, and stabilization services"),
            ("overdose-prevention-portfolio", "choose a statewide overdose-prevention portfolio across treatment access, harm reduction, prescribing, and recovery support"),
            ("long-term-care-infection-resilience", "strengthen infection prevention and outbreak resilience across long-term-care facilities"),
            ("cancer-screening-equity-program", "prioritize interventions that close persistent cancer-screening gaps without increasing downstream access bottlenecks"),
            ("diabetes-prevention-scaleup", "scale evidence-based diabetes prevention across Medicaid, employers, and community delivery partners"),
            ("heat-health-protection-network", "coordinate healthcare and public-health protections for recurrent extreme-heat emergencies"),
            ("pediatric-vaccine-catchup", "design a pediatric vaccination catch-up strategy across schools, primary care, pharmacies, and public clinics"),
            ("dialysis-disaster-continuity", "protect dialysis access during prolonged power, water, transport, and supply disruptions"),
            ("telehealth-access-rebalance", "retain useful telehealth access while correcting geographic, disability, language, and broadband inequities"),
            ("critical-drug-shortage-allocation", "allocate scarce critical medicines across hospitals while reducing future shortage exposure"),
            ("newborn-screening-expansion", "decide whether and how to expand a state newborn-screening panel and follow-up capacity"),
            ("dementia-caregiver-support", "build a statewide dementia caregiver-support portfolio with measurable respite, navigation, and health outcomes"),
            ("childhood-asthma-air-quality", "reduce childhood asthma burden through housing, school, outdoor-air, and clinical interventions"),
            ("ems-regionalization", "regionalize emergency medical services while preserving response time, clinical quality, and rural coverage"),
            ("postpartum-mental-health-access", "close postpartum mental-health screening and treatment gaps across obstetric and primary-care systems"),
            ("safety-net-hospital-stabilization", "stabilize safety-net hospital access while distinguishing temporary liquidity problems from structural service mismatch"),
        ],
    },
    {
        "slug": "environment-climate-energy",
        "scope": "United States climate, environmental, and energy policy with relevant regional implementation",
        "audience": "a state and regional resilience commission",
        "workstreams": [
            "hazard baselines and projected exposure",
            "federal, state, tribal, and local authority",
            "technology performance and lifecycle evidence",
            "infrastructure capacity and interdependencies",
            "community health, equity, and environmental justice",
            "capital cost, operating cost, and financing",
            "permitting, siting, and implementation timelines",
            "scenario modeling, units, and denominator alignment",
            "counterevidence, leakage, and uncertainty",
            "sequencing, triggers, monitoring, and adaptive management",
        ],
        "domains": ["epa.gov", "energy.gov", "noaa.gov", "usgs.gov", "fema.gov", "blm.gov", "nrel.gov"],
        "cases": [
            ("grid-extreme-heat-resilience", "prioritize grid investments for extreme-heat load, generation, and transmission stress"),
            ("coastal-flood-adaptation", "choose among protection, accommodation, and managed-retreat strategies for repeatedly flooded communities"),
            ("wildfire-risk-reduction", "allocate a regional wildfire-risk budget across fuels treatment, home hardening, detection, and response capacity"),
            ("methane-reduction-portfolio", "design a methane-reduction portfolio across oil and gas, landfills, agriculture, and abandoned infrastructure"),
            ("groundwater-depletion-response", "stabilize an overdrawn groundwater basin while protecting drinking water, ecosystems, and farm viability"),
            ("pfas-cleanup-prioritization", "prioritize PFAS drinking-water treatment and source-control investments under evolving standards"),
            ("urban-heat-mitigation", "compare tree canopy, reflective surfaces, cooling access, zoning, and building interventions for urban heat"),
            ("building-electrification-transition", "sequence building electrification while managing grid peaks, housing affordability, and workforce capacity"),
            ("offshore-wind-siting", "choose an offshore-wind development and transmission strategy that reconciles energy, fisheries, wildlife, and coastal impacts"),
            ("ev-charging-grid-plan", "site and stage public EV charging while managing distribution-grid upgrades and unequal access"),
            ("dam-removal-river-restoration", "decide whether and how to remove aging dams while addressing water supply, sediment, habitat, recreation, and cultural resources"),
            ("drought-water-allocation", "design a drought allocation framework across cities, agriculture, tribes, industry, and ecosystems"),
            ("carbon-capture-hub", "evaluate a proposed carbon-capture transport and storage hub across performance, safety, permanence, and community impacts"),
            ("community-solar-access", "expand community solar while preserving consumer protection, grid value, and low-income participation"),
            ("hydrogen-hub-strategy", "prioritize hydrogen production and end uses while distinguishing emissions pathways, water demands, and infrastructure needs"),
            ("forest-restoration-portfolio", "allocate forest-restoration funding across fire resilience, biodiversity, carbon, water, and rural economies"),
            ("climate-insurance-retreat", "respond to property-insurance withdrawal while avoiding maladaptive rebuilding and inequitable displacement"),
            ("critical-facility-microgrids", "prioritize microgrids for hospitals, shelters, water systems, and other critical facilities"),
            ("organic-waste-methane", "compare landfill diversion, composting, digestion, and methane-control strategies for organic waste"),
            ("industrial-decarbonization", "choose a regional industrial-decarbonization portfolio across efficiency, electrification, fuels, capture, and material substitution"),
        ],
    },
    {
        "slug": "government-public-services",
        "scope": "United States government administration and public-service delivery",
        "audience": "a state and local public-service modernization board",
        "workstreams": [
            "statutory authority and program eligibility",
            "service demand and population need",
            "current performance and administrative burden",
            "federal, state, local, and tribal role allocation",
            "procurement, workforce, and vendor capacity",
            "budget authority, obligation, spending, and lifecycle cost",
            "accessibility, language access, and distributional equity",
            "privacy, due process, and accountability safeguards",
            "implementation alternatives and failure modes",
            "phasing, performance measures, and corrective triggers",
        ],
        "domains": ["gao.gov", "usa.gov", "census.gov", "omb.gov", "gsa.gov", "fema.gov", "congress.gov"],
        "cases": [
            ("emergency-shelter-network", "redesign an emergency-shelter network for severe weather, displacement, disability access, and family continuity"),
            ("broadband-grant-prioritization", "prioritize broadband grants across unserved locations, affordability, adoption, and long-term network performance"),
            ("transit-service-equity", "rebalance metropolitan transit service across ridership recovery, essential trips, disability access, and operating constraints"),
            ("public-benefits-modernization", "modernize public-benefit enrollment while reducing churn, improper denials, fraud, and administrative burden"),
            ("disaster-housing-recovery", "choose a disaster-housing recovery model spanning shelter, temporary units, rental aid, repair, and permanent relocation"),
            ("public-procurement-modernization", "modernize public procurement while improving competition, delivery speed, transparency, and small-supplier access"),
            ("regional-911-consolidation", "evaluate consolidating local 911 centers while preserving response quality, redundancy, and local accountability"),
            ("small-water-system-support", "build a support and consolidation strategy for financially and operationally distressed small water systems"),
            ("school-meal-access", "expand school-meal access while controlling administrative burden, nutrition quality, waste, and fiscal exposure"),
            ("workforce-training-allocation", "allocate workforce-training funds across displaced workers, employers, community colleges, and high-growth occupations"),
            ("public-records-modernization", "reduce public-record request backlogs while protecting lawful exemptions, privacy, and reproducibility"),
            ("election-accessibility-plan", "improve election accessibility across polling places, mail voting, language assistance, and resilient administration"),
            ("library-digital-access", "position public libraries as durable digital-access, skills, and government-navigation infrastructure"),
            ("grant-oversight-redesign", "redesign grant oversight to detect material misuse without imposing disproportionate burden on capable recipients"),
            ("municipal-pension-stabilization", "stabilize an underfunded municipal pension while preserving service capacity and intergenerational fairness"),
            ("zoning-housing-production", "reform zoning and permitting to increase housing supply while addressing infrastructure, displacement, and affordability"),
            ("community-violence-prevention", "allocate community-violence prevention resources across outreach, hospital intervention, environmental design, and enforcement coordination"),
            ("public-health-data-modernization", "modernize public-health data exchange across jurisdictions while preserving timeliness, privacy, and local capacity"),
            ("language-access-services", "build a government-wide language-access model spanning translation, interpretation, digital services, and emergency communications"),
            ("rural-public-service-hubs", "consolidate selected rural public services into shared hubs without worsening travel, access, or institutional trust"),
        ],
    },
    {
        "slug": "law-rights-legal-processes",
        "scope": "United States legal, regulatory, civil-rights, and enforcement policy",
        "audience": "a legal-policy and compliance working group",
        "workstreams": [
            "controlling statutes, regulations, and case law",
            "jurisdiction, standing, preemption, and applicability",
            "effective dates, transitions, and superseded authority",
            "regulated-entity duties and available exceptions",
            "individual rights, remedies, and procedural protections",
            "agency guidance, enforcement posture, and judicial review",
            "empirical impacts and affected populations",
            "compliance alternatives, cost, and operational feasibility",
            "unresolved conflicts and litigation risk",
            "decision conditions, safeguards, documentation, and monitoring",
        ],
        "domains": ["congress.gov", "justice.gov", "ftc.gov", "dol.gov", "eeoc.gov", "consumerfinance.gov", "law.cornell.edu"],
        "cases": [
            ("ai-hiring-compliance", "design compliant use and oversight rules for automated hiring and employment screening systems"),
            ("tenant-screening-governance", "govern tenant-screening data and algorithms while preserving legitimate risk assessment and applicant rights"),
            ("gig-worker-classification", "assess worker-classification and benefit options for app-mediated labor across conflicting legal tests"),
            ("noncompete-transition", "respond to changing noncompete rules while protecting worker mobility and legitimate confidential information"),
            ("data-broker-regulation", "design a state data-broker framework covering registration, sensitive data, deletion, sale, and enforcement"),
            ("biometric-privacy-compliance", "establish biometric-data collection, consent, retention, vendor, and litigation controls"),
            ("environmental-justice-permitting", "integrate environmental-justice analysis into permitting without obscuring statutory authority or evidentiary limits"),
            ("digital-accessibility-compliance", "prioritize digital-accessibility remediation across government and public-facing services"),
            ("debt-collection-enforcement", "target debt-collection supervision and enforcement across communications, validation, litigation, and vulnerable consumers"),
            ("medical-debt-reporting", "evaluate medical-debt reporting and collection reforms across federal and state authority"),
            ("reproductive-health-privacy", "protect reproductive-health information across providers, apps, subpoenas, interstate requests, and consumer platforms"),
            ("automated-benefit-due-process", "govern automated public-benefit decisions with notice, explanation, appeal, and error-correction safeguards"),
            ("juvenile-record-relief", "redesign juvenile record sealing and expungement across eligibility, automation, notice, and collateral consequences"),
            ("body-camera-governance", "set body-camera activation, retention, disclosure, privacy, discipline, and evidentiary rules"),
            ("service-animal-access", "reconcile service-animal access duties across transportation, housing, employment, and public accommodations"),
            ("cross-border-data-transfer", "choose lawful cross-border data-transfer controls for a regulated multinational organization"),
            ("autonomous-vehicle-liability", "allocate safety, reporting, insurance, and product-liability responsibilities for autonomous vehicles"),
            ("wage-theft-enforcement", "allocate wage-theft enforcement across proactive investigations, complaints, joint liability, and worker remedies"),
            ("consumer-arbitration-policy", "evaluate consumer arbitration and class-waiver policy across enforceability, access, cost, and remedy evidence"),
            ("public-record-exemptions", "reconcile transparency, privacy, safety, deliberative-process, and law-enforcement exemptions in public records"),
        ],
    },
    {
        "slug": "finance-banking-investing",
        "scope": "United States finance, banking, insurance, and investment policy",
        "audience": "a financial-policy and risk committee",
        "workstreams": [
            "controlling financial authority and institutional scope",
            "market size, exposures, and trend measurement",
            "capital, liquidity, solvency, and loss transmission",
            "consumer and investor protection",
            "product structure, fees, incentives, and conflicts",
            "macroeconomic and distributional effects",
            "scenario calculations, stress assumptions, and denominators",
            "implementation capacity and market responses",
            "counterevidence, model risk, and unresolved uncertainty",
            "phased controls, disclosures, monitoring, and escalation",
        ],
        "domains": ["federalreserve.gov", "fdic.gov", "sec.gov", "consumerfinance.gov", "treasury.gov", "cftc.gov", "naic.org"],
        "cases": [
            ("bank-climate-risk", "design proportionate climate-risk supervision for banks with different portfolios and sizes"),
            ("retirement-decumulation", "choose retirement-income and decumulation defaults for a large defined-contribution plan"),
            ("municipal-bond-resilience", "evaluate a municipal capital plan under revenue, climate, pension, and refinancing stress"),
            ("community-bank-fintech", "govern community-bank partnerships with fintech lenders across underwriting, compliance, concentration, and customer outcomes"),
            ("stablecoin-reserve-policy", "assess reserve, redemption, custody, disclosure, and failure-resolution requirements for payment stablecoins"),
            ("mortgage-distress-intervention", "choose a mortgage-distress intervention portfolio across forbearance, modification, counseling, and foreclosure alternatives"),
            ("small-business-credit-access", "expand small-business credit while distinguishing approval, pricing, performance, and distributional outcomes"),
            ("student-loan-repayment", "compare student-loan repayment and relief strategies across eligibility, fiscal cost, delinquency, and administrative feasibility"),
            ("catastrophe-insurance-stability", "stabilize a catastrophe-exposed property-insurance market without masking risk or abandoning vulnerable households"),
            ("public-pension-allocation", "revise public-pension asset allocation under return, liquidity, contribution, and downside-risk constraints"),
            ("esg-fund-disclosure", "govern sustainability-related fund names, disclosures, portfolio practices, and investor expectations"),
            ("buy-now-pay-later", "design consumer protections for buy-now-pay-later products across underwriting, disputes, fees, reporting, and repeat use"),
            ("agricultural-credit-stress", "prepare agricultural lenders and borrowers for commodity, interest-rate, drought, and land-value stress"),
            ("hospital-capital-finance", "choose a capital-financing strategy for safety-net hospital modernization under reimbursement and demand uncertainty"),
            ("open-banking-transition", "implement open banking across data scope, consent, liability, competition, security governance, and inclusion"),
            ("credit-union-liquidity", "strengthen credit-union liquidity planning across member concentration, investments, borrowing, and stress scenarios"),
            ("flood-insurance-transition", "transition flood-insurance pricing and mitigation support while managing affordability and risk signals"),
            ("green-bond-accountability", "design a green-bond framework covering project eligibility, additionality, proceeds, impact metrics, and verification"),
            ("wealth-advice-fiduciary", "govern retirement and wealth advice across fiduciary duties, rollover incentives, conflicts, and disclosure effectiveness"),
            ("deposit-concentration-risk", "address uninsured-deposit and depositor-concentration risk without creating blunt incentives or false reassurance"),
        ],
    },
    {
        "slug": "business-industry-supply-chains",
        "scope": "United States industrial strategy, business operations, and international supply chains",
        "audience": "an industrial resilience and investment council",
        "workstreams": [
            "demand, capacity, concentration, and trade baselines",
            "supplier tiers, dependencies, and substitution limits",
            "standards, regulation, and public-policy authority",
            "technology maturity, quality, and production yield",
            "capital, operating cost, incentives, and financing",
            "workforce, infrastructure, and regional constraints",
            "environmental, labor, and community impacts",
            "scenario calculations and disruption transmission",
            "alternative sourcing, inventory, and continuity strategies",
            "sequencing, qualification, monitoring, and exit conditions",
        ],
        "domains": ["commerce.gov", "trade.gov", "usitc.gov", "nist.gov", "bls.gov", "census.gov", "ustr.gov"],
        "cases": [
            ("semiconductor-reshoring", "prioritize semiconductor manufacturing and supplier investments across technology nodes, demand, incentives, and workforce"),
            ("critical-minerals-sourcing", "build a critical-minerals sourcing portfolio across domestic production, allies, recycling, substitution, and stockpiles"),
            ("pharmaceutical-shortage-resilience", "reduce pharmaceutical shortages across manufacturing quality, concentration, purchasing incentives, inventory, and transparency"),
            ("cold-chain-resilience", "strengthen cold-chain continuity for medicines and food across power, transport, storage, monitoring, and emergency allocation"),
            ("port-disruption-continuity", "prepare importers and regional agencies for a prolonged major-port disruption"),
            ("supplier-traceability", "implement multi-tier supplier traceability while balancing assurance, interoperability, burden, and sensitive information"),
            ("battery-recycling-network", "build a battery collection, transport, processing, and recovered-material market strategy"),
            ("aerospace-supplier-qualification", "expand aerospace supplier capacity without weakening quality, certification, traceability, or delivery reliability"),
            ("food-processing-automation", "prioritize automation investments in food processing across productivity, safety, workforce, quality, and resilience"),
            ("construction-material-volatility", "manage construction-material price and availability risk across procurement, design, inventories, and domestic capacity"),
            ("textile-due-diligence", "design textile supply-chain due diligence across labor, origin, environmental claims, traceability, and supplier remediation"),
            ("medical-device-quality-resilience", "reduce medical-device supply and quality failures across suppliers, validation, recalls, and substitution"),
            ("rare-earth-magnet-capacity", "develop rare-earth magnet capacity across mining, separation, manufacturing, recycling, and demand prioritization"),
            ("rail-freight-capacity", "improve rail-freight capacity and service reliability across labor, terminals, equipment, competition, and shipper needs"),
            ("urban-last-mile-logistics", "redesign urban last-mile logistics across curb access, consolidation, emissions, labor, and neighborhood impacts"),
            ("small-manufacturer-energy", "help small manufacturers manage energy cost, reliability, efficiency, and electrification investments"),
            ("packaging-producer-responsibility", "implement packaging producer responsibility across fees, recyclability, collection, markets, and consumer costs"),
            ("supplier-diversity-procurement", "expand supplier diversity in public and anchor-institution procurement while preserving competition and delivery performance"),
            ("maritime-decarbonization", "choose a maritime decarbonization pathway across fuels, vessels, ports, safety, emissions accounting, and trade effects"),
            ("industrial-water-risk", "manage industrial water risk across site selection, process efficiency, reuse, community needs, and climate variability"),
        ],
    },
    {
        "slug": "consumer-products-services",
        "scope": "United States consumer products, services, markets, and protection policy",
        "audience": "a consumer-market policy and enforcement group",
        "workstreams": [
            "product or service market structure",
            "controlling consumer-protection authority",
            "claims, disclosures, pricing, and contract terms",
            "safety, quality, reliability, and complaint evidence",
            "affected populations and distributional impacts",
            "vendor, platform, and intermediary responsibilities",
            "remedies, enforcement, and compliance alternatives",
            "quantitative incidence, cost, and outcome comparisons",
            "counterevidence, scope limits, and uncertainty",
            "implementation priorities, monitoring, and escalation",
        ],
        "domains": ["ftc.gov", "cpsc.gov", "consumerfinance.gov", "fda.gov", "dot.gov", "fcc.gov", "usa.gov"],
        "cases": [
            ("right-to-repair", "design right-to-repair requirements across parts, tools, diagnostics, software locks, safety, and warranty practices"),
            ("smart-appliance-data", "govern smart-appliance data collection, retention, sharing, updates, and loss of functionality"),
            ("airline-refund-protection", "improve airline refund and disruption protections across cancellations, delays, ancillary services, and intermediaries"),
            ("subscription-cancellation", "govern recurring subscriptions across enrollment, renewal, cancellation, price changes, and recordkeeping"),
            ("childrens-online-services", "set consumer safeguards for children's online services across design, advertising, purchases, privacy, and parental controls"),
            ("used-ev-consumer-protection", "improve used-EV battery-health disclosure, warranty, repair, financing, and resale protections"),
            ("hearing-aid-market", "evaluate consumer outcomes in over-the-counter and prescription hearing-aid markets"),
            ("residential-solar-sales", "govern residential-solar savings claims, financing, installation, interconnection, warranties, and remedies"),
            ("ticketing-fees-resale", "improve ticket price transparency and resale protections across platforms, venues, brokers, and event cancellation"),
            ("dietary-supplement-claims", "prioritize oversight of dietary-supplement claims, ingredients, manufacturing, adverse events, and vulnerable consumers"),
            ("cosmetics-safety", "implement cosmetics safety oversight across facility registration, ingredients, substantiation, reporting, and recalls"),
            ("funeral-pricing-transparency", "modernize funeral price transparency across in-person, telephone, and online purchasing"),
            ("rental-car-pricing", "address rental-car fee, damage, insurance, fuel, toll, and reservation practices"),
            ("home-insurance-disclosures", "improve homeowner understanding of exclusions, deductibles, valuation, nonrenewal, and mitigation conditions"),
            ("loyalty-program-changes", "govern loyalty-program devaluation, expiration, transfer, account closure, and partner changes"),
            ("peer-payment-fraud", "allocate responsibility for peer-to-peer payment fraud, scams, errors, authentication, and consumer recovery"),
            ("pet-insurance-comparison", "improve pet-insurance comparison across exclusions, waiting periods, reimbursement, premium changes, and claims"),
            ("self-service-kiosk-access", "make self-service kiosks accessible across payment, ticketing, check-in, retail, and government services"),
            ("mattress-chemical-claims", "evaluate mattress chemical, flammability, health, and environmental marketing claims"),
            ("resale-marketplace-trust", "govern resale marketplaces across authenticity, stolen goods, returns, seller identity, payments, and platform accountability"),
        ],
    },
    {
        "slug": "food-agriculture-animal-systems",
        "scope": "United States food, agriculture, fisheries, and animal-system policy",
        "audience": "a food-system resilience and agricultural policy board",
        "workstreams": [
            "production, demand, trade, and concentration baselines",
            "federal, state, tribal, and local authority",
            "farm, processor, distributor, and retailer incentives",
            "food safety, animal health, and public-health evidence",
            "soil, water, biodiversity, and climate impacts",
            "labor, rural communities, and equity",
            "technology performance and adoption constraints",
            "scenario calculations, units, yields, and denominators",
            "counterevidence, leakage, and uncertainty",
            "phased implementation, monitoring, and contingency plans",
        ],
        "domains": ["usda.gov", "fda.gov", "epa.gov", "noaa.gov", "usgs.gov", "cdc.gov", "ers.usda.gov"],
        "cases": [
            ("avian-influenza-resilience", "coordinate avian-influenza surveillance, farm biosecurity, worker protection, depopulation, vaccination, and market continuity"),
            ("drought-crop-insurance", "redesign drought resilience and crop-insurance incentives across practices, regions, yields, and fiscal exposure"),
            ("soil-carbon-program", "build a soil-carbon program with credible measurement, additionality, permanence, leakage, and farmer economics"),
            ("pesticide-drift-protection", "reduce pesticide-drift harm across application rules, monitoring, worker protection, notification, and enforcement"),
            ("farmworker-heat-protection", "implement farmworker heat protections across thresholds, acclimatization, housing, enforcement, and farm operations"),
            ("irrigation-modernization", "prioritize irrigation modernization while accounting for basin-scale consumption, energy, farm viability, and ecosystems"),
            ("livestock-antibiotic-stewardship", "reduce medically important antibiotic use in livestock while protecting animal health and producer viability"),
            ("pollinator-protection", "choose a pollinator-protection portfolio across pesticides, habitat, disease, managed bees, and farm production"),
            ("aquaculture-siting", "site and regulate aquaculture across production, water quality, disease, escapes, feed, and coastal communities"),
            ("local-school-food-procurement", "expand local school-food procurement while meeting nutrition, cost, volume, safety, and administrative requirements"),
            ("food-traceability-implementation", "implement food traceability across farms, processors, distributors, retailers, interoperability, and recall speed"),
            ("regional-meat-processing", "expand regional meat-processing capacity across inspection, workforce, utilization, financing, and producer access"),
            ("regenerative-agriculture-claims", "govern regenerative-agriculture claims across definitions, measurement, outcomes, verification, and farmer burden"),
            ("fertilizer-runoff-reduction", "reduce fertilizer runoff across nutrient plans, practices, monitoring, incentives, and watershed accountability"),
            ("urban-agriculture-policy", "support urban agriculture across land access, soil safety, water, zoning, food access, and business viability"),
            ("vertical-farming-viability", "evaluate vertical-farming investment across energy, yield, crop mix, water, labor, and market conditions"),
            ("seed-market-competition", "address seed-market concentration across innovation, licensing, pricing, interoperability, and farmer choice"),
            ("fisheries-bycatch-reduction", "choose bycatch-reduction strategies across gear, closures, monitoring, stock impacts, and fishing communities"),
            ("animal-welfare-labeling", "govern animal-welfare labels across standards, audits, consumer interpretation, producer costs, and enforcement"),
            ("food-waste-organics", "reduce food waste across prevention, donation, date labels, animal feed, digestion, composting, and measurement"),
        ],
    },
    {
        "slug": "science-research-information",
        "scope": "United States research policy, scholarly communication, and scientific infrastructure",
        "audience": "a research-funding and scientific-integrity council",
        "workstreams": [
            "policy authority and institutional applicability",
            "research-field and infrastructure baselines",
            "evidence quality, reproducibility, and external validity",
            "publishing, data, software, and access practices",
            "researcher incentives, careers, and workforce",
            "participant, community, ethical, and equity safeguards",
            "cost, capacity, governance, and implementation",
            "quantitative metrics and denominator alignment",
            "counterevidence, uncertainty, and unintended effects",
            "phased policy, evaluation, and revision triggers",
        ],
        "domains": ["nsf.gov", "nih.gov", "nasa.gov", "energy.gov", "nist.gov", "ostp.gov", "nationalacademies.org"],
        "cases": [
            ("public-access-policy", "implement public access to federally funded publications while addressing repositories, rights, cost, and compliance"),
            ("reproducibility-investment", "allocate reproducibility funding across methods, training, infrastructure, replication, and incentives"),
            ("clinical-trial-data-sharing", "govern clinical-trial data sharing across timing, consent, privacy, access review, reuse, and accountability"),
            ("research-security-compliance", "implement proportionate research-security disclosure and training without suppressing legitimate international collaboration"),
            ("preprint-evidence-use", "set rules for using preprints in funding, clinical communication, media, and evidence synthesis"),
            ("animal-method-alternatives", "accelerate alternatives to animal methods while preserving validation, regulatory acceptance, and research reliability"),
            ("citizen-science-program", "build a citizen-science program with credible data quality, participant value, governance, and decision use"),
            ("biobank-consent-governance", "govern biobank consent, return of results, data linkage, access, commercialization, and community trust"),
            ("telescope-time-allocation", "redesign telescope-time allocation across scientific merit, oversubscription, early-career access, risk, and legacy value"),
            ("research-computing-investment", "allocate research-computing investment across national facilities, campus systems, cloud, software, and workforce"),
            ("research-misconduct-system", "improve research-misconduct prevention and investigation across institutions, funders, journals, and whistleblowers"),
            ("research-metric-reform", "reform research evaluation metrics across hiring, promotion, grants, journals, fields, and unintended incentives"),
            ("indigenous-data-governance", "implement Indigenous data governance in research partnerships across consent, control, benefit, access, and sovereignty"),
            ("negative-results-infrastructure", "increase publication and reuse of negative and null results without creating low-value reporting burden"),
            ("replication-grant-portfolio", "design a replication-grant portfolio across field selection, study choice, methods, incentives, and interpretation"),
            ("shared-core-facilities", "optimize shared research core facilities across capital, utilization, staffing, pricing, access, and replacement"),
            ("interdisciplinary-center-review", "decide whether to renew interdisciplinary research centers using outputs, collaboration, capacity, and counterfactual value"),
            ("field-station-resilience", "adapt field research stations to climate, infrastructure, ecological, access, and continuity risks"),
            ("laboratory-sustainability", "reduce laboratory energy, water, materials, and waste while preserving safety and scientific performance"),
            ("ai-peer-review-governance", "govern AI assistance in peer review across confidentiality, bias, accountability, disclosure, and reviewer workload"),
        ],
    },
    {
        "slug": "technology-telecom-digital-policy",
        "scope": "United States technology, telecommunications, digital-infrastructure, and platform policy",
        "audience": "a technology-policy and infrastructure commission",
        "workstreams": [
            "controlling authority, standards, and institutional scope",
            "market structure, adoption, and performance baselines",
            "technical architecture and interoperability",
            "reliability, resilience, safety, and incident evidence",
            "privacy, civil rights, and consumer impacts",
            "competition, procurement, and vendor concentration",
            "capital, operating cost, workforce, and deployment constraints",
            "scenario calculations and metric reconciliation",
            "counterevidence, obsolescence, and uncertainty",
            "phased governance, testing, monitoring, and exit conditions",
        ],
        "domains": ["fcc.gov", "ftc.gov", "nist.gov", "ntia.gov", "commerce.gov", "gao.gov", "cisa.gov"],
        "cases": [
            ("rural-broadband-deployment", "prioritize rural broadband deployment across coverage, affordability, adoption, performance, and technology longevity"),
            ("government-ai-procurement", "govern public-sector AI procurement across need, testing, data, rights, vendor claims, monitoring, and exit"),
            ("telecom-outage-resilience", "strengthen telecom outage resilience across power, backhaul, roaming, reporting, restoration, and vulnerable users"),
            ("online-child-safety", "design online child-safety safeguards across age assurance, design, content, privacy, parental tools, and rights"),
            ("cloud-concentration-risk", "manage cloud-service concentration across portability, resilience, procurement, observability, and critical dependencies"),
            ("spectrum-sharing-plan", "choose a spectrum-sharing framework across incumbent protection, commercial use, federal missions, and measurement"),
            ("facial-recognition-governance", "govern facial-recognition use across accuracy, context, consent, civil rights, auditing, retention, and redress"),
            ("data-center-energy-water", "plan data-center growth across grid capacity, water, land, emissions, economic value, and community impacts"),
            ("post-quantum-migration", "sequence post-quantum cryptography migration across inventories, standards, dependencies, performance, and long-lived data"),
            ("software-component-transparency", "implement software-component transparency across suppliers, formats, procurement, vulnerability response, and burden"),
            ("satellite-broadband-policy", "evaluate satellite broadband across coverage, capacity, affordability, spectrum, orbital impacts, and public subsidy"),
            ("content-provenance", "deploy content-provenance mechanisms across capture, editing, platforms, interoperability, adoption, and misuse"),
            ("app-store-competition", "govern app-store competition across distribution, payments, security review, ranking, developer access, and consumers"),
            ("connected-device-labeling", "implement connected-device labeling across baseline practices, updates, testing, consumer comprehension, and enforcement"),
            ("digital-identity-system", "design a digital-identity system across assurance, privacy, accessibility, federation, fraud, recovery, and exclusion"),
            ("emergency-alert-modernization", "modernize emergency alerts across targeting, accessibility, multilingual delivery, sender capacity, trust, and evaluation"),
            ("open-source-public-infrastructure", "sustain critical open-source software used by public institutions through funding, governance, maintenance, and procurement"),
            ("undersea-cable-resilience", "improve undersea-cable resilience across route diversity, repair capacity, landing stations, permitting, and coordination"),
            ("algorithmic-transparency", "design algorithmic transparency obligations across scope, documentation, audits, trade secrets, and public usefulness"),
            ("device-electronic-waste", "reduce device electronic waste across durability, repair, collection, reuse, recycling, data handling, and producer responsibility"),
        ],
    },
    {
        "slug": "transportation-mobility-travel",
        "scope": "United States transportation, mobility, logistics, and travel policy",
        "audience": "a regional transportation and mobility authority",
        "workstreams": [
            "travel demand, network performance, and safety baselines",
            "federal, state, local, and operator authority",
            "infrastructure condition, capacity, and resilience",
            "technology performance and operational integration",
            "accessibility, equity, land use, and community impacts",
            "capital, operating cost, revenue, and funding eligibility",
            "environmental, health, and economic effects",
            "scenario calculations and appraisal assumptions",
            "delivery risk, counterevidence, and uncertainty",
            "phasing, pilots, monitoring, and decision triggers",
        ],
        "domains": ["transportation.gov", "fhwa.dot.gov", "fta.dot.gov", "fra.dot.gov", "faa.gov", "ntsb.gov", "bts.gov"],
        "cases": [
            ("intercity-rail-corridor", "choose an intercity passenger-rail corridor strategy across demand, infrastructure, operations, cost, and alternatives"),
            ("bus-fleet-electrification", "sequence bus-fleet electrification across routes, charging, depots, grid upgrades, workforce, and service reliability"),
            ("airport-noise-program", "redesign airport-noise management across measurement, operations, land use, insulation, health evidence, and community equity"),
            ("autonomous-shuttle-pilot", "decide whether and how to pilot autonomous shuttles across safety, accessibility, operations, liability, and public value"),
            ("road-pricing-policy", "design road pricing across congestion, revenue, privacy, exemptions, diversion, equity, and transit alternatives"),
            ("pedestrian-safety-portfolio", "allocate pedestrian-safety funding across street design, speed, vehicles, enforcement, schools, and high-risk locations"),
            ("urban-freight-curb", "manage urban freight and curb access across deliveries, commerce, transit, accessibility, pricing, and enforcement"),
            ("high-speed-rail-phasing", "evaluate high-speed rail phasing across segments, demand, travel-time benefits, costs, interfaces, and delivery risk"),
            ("ferry-system-resilience", "strengthen ferry-system resilience across vessels, terminals, weather, staffing, energy, and essential access"),
            ("rural-transit-access", "improve rural transit across fixed routes, demand response, healthcare trips, workforce access, cost, and coordination"),
            ("ev-charging-corridor-equity", "build an equitable highway and community EV-charging network across utilization, reliability, access, and grid needs"),
            ("essential-air-service", "evaluate essential air service and alternative connectivity across access, subsidy, reliability, emissions, and regional development"),
            ("protected-bike-network", "prioritize a protected bicycle network across safety, connectivity, demand, parking, transit, and neighborhood impacts"),
            ("port-dredging-strategy", "evaluate port dredging across navigation, trade, sediment, habitat, climate, cost, and competing investments"),
            ("electric-school-buses", "sequence electric school-bus adoption across routes, charging, health, grid services, funding, and reliability"),
            ("bridge-rehabilitation-priority", "prioritize bridge rehabilitation across condition, consequence, detours, equity, freight, and lifecycle cost"),
            ("drone-delivery-policy", "govern drone delivery across airspace, safety, noise, privacy, access, labor, and last-mile alternatives"),
            ("intercity-bus-network", "strengthen intercity bus connectivity across rural access, terminals, schedules, subsidies, and rail coordination"),
            ("zero-emission-trucking", "sequence zero-emission trucking across duty cycles, charging or fueling, grid, vehicles, freight operations, and communities"),
            ("regional-evacuation-plan", "redesign regional evacuation across demand, contraflow, transit, fuel, disability access, shelters, and return sequencing"),
        ],
    },
    {
        "slug": "education-learning-training",
        "scope": "United States education, learning, and training policy",
        "audience": "an education-system strategy council",
        "workstreams": [
            "student population, participation, and outcome baselines",
            "federal, state, local, and institutional authority",
            "eligibility, admissions, placement, and completion rules",
            "instructional effectiveness and evidence quality",
            "educator workforce, facilities, and delivery capacity",
            "funding formulas, student cost, and fiscal sustainability",
            "disability access, language access, and distributional equity",
            "credential value, transferability, and labor-market alignment",
            "counterevidence, measurement limits, and unintended effects",
            "phasing, evaluation, safeguards, and revision triggers",
        ],
        "domains": ["ed.gov", "nces.ed.gov", "ies.ed.gov", "bls.gov", "dol.gov", "gao.gov", "census.gov"],
        "cases": [
            ("community-college-completion-redesign", "redesign community-college pathways across placement, advising, transfer, financial aid, and completion"),
            ("early-literacy-intervention-portfolio", "choose an early-literacy portfolio across curriculum, tutoring, screening, teacher support, and family engagement"),
            ("special-education-service-recovery", "recover delayed special-education evaluations and services while preserving procedural and instructional quality"),
            ("teacher-shortage-retention-plan", "address teacher shortages across preparation, compensation, working conditions, licensure, and rural recruitment"),
            ("career-technical-education-alignment", "align career and technical education with credentials, employers, work-based learning, and student mobility"),
            ("college-affordability-aid-redesign", "redesign state student aid across need, merit, completion incentives, part-time study, and institutional response"),
            ("school-discipline-equity-reform", "reform school discipline across safety, due process, disparities, climate, and student support"),
            ("adult-literacy-digital-skills", "scale adult literacy and digital-skills services across access, persistence, credentialing, and employment outcomes"),
            ("rural-school-consolidation", "evaluate rural school consolidation across educational offerings, travel, community effects, staffing, and cost"),
            ("student-mental-health-capacity", "build student mental-health capacity across prevention, counseling, referral, crisis response, and privacy"),
            ("higher-education-transfer-policy", "improve higher-education transfer across articulation, credit loss, advising, program fit, and completion"),
            ("apprenticeship-quality-expansion", "expand apprenticeships while preserving quality, portability, worker protection, employer participation, and access"),
            ("school-connectivity-learning-value", "target school connectivity and device investments according to instructional use, reliability, support, and equity"),
            ("multilingual-learner-program", "redesign multilingual-learner services across identification, instruction, staffing, assessment, and family access"),
        ],
    },
    {
        "slug": "housing-real-estate",
        "scope": "United States housing, real-estate, and community-development policy",
        "audience": "a regional housing and community-development board",
        "workstreams": [
            "housing need, supply, vacancy, and cost baselines",
            "federal, state, local, and contractual authority",
            "eligibility, tenant, borrower, and property scope",
            "production, preservation, and rehabilitation capacity",
            "finance, subsidy, insurance, and lifecycle cost",
            "displacement, segregation, accessibility, and fair-housing effects",
            "land use, infrastructure, climate, and neighborhood impacts",
            "market response, appraisal, and quantitative assumptions",
            "counterevidence, implementation failure, and uncertainty",
            "sequencing, tenant safeguards, monitoring, and reassessment",
        ],
        "domains": ["hud.gov", "fhfa.gov", "census.gov", "consumerfinance.gov", "gao.gov", "fema.gov", "usda.gov"],
        "cases": [
            ("affordable-housing-preservation", "preserve expiring affordable housing across acquisition, rehabilitation, subsidy renewal, and tenant protection"),
            ("eviction-prevention-system", "design an eviction-prevention system across notice, legal help, emergency aid, mediation, and landlord participation"),
            ("office-housing-conversion", "evaluate office-to-housing conversion across physical feasibility, zoning, finance, affordability, and neighborhood demand"),
            ("manufactured-housing-stability", "protect manufactured-housing residents across land tenure, finance, infrastructure, ownership transitions, and relocation"),
            ("rental-inspection-redesign", "redesign rental inspection across risk targeting, habitability, enforcement, tenant retaliation, and owner capacity"),
            ("first-generation-homeownership", "support first-generation homeownership across down payments, underwriting, counseling, supply, and wealth risk"),
            ("public-housing-capital-triage", "prioritize public-housing capital repairs across health, safety, accessibility, climate, displacement, and cost"),
            ("homelessness-permanent-housing", "allocate homelessness resources across prevention, shelter, supportive housing, rapid rehousing, and service capacity"),
            ("accessory-dwelling-unit-scaleup", "scale accessory dwelling units across zoning, finance, construction, rental use, infrastructure, and equity"),
            ("flood-exposed-housing-transition", "manage repeatedly flooded housing across mitigation, insurance, buyouts, relocation, affordability, and community continuity"),
            ("rural-rental-preservation", "preserve rural rental housing across maturing subsidies, rehabilitation, ownership succession, and service access"),
            ("vacant-property-reuse", "convert vacant properties into stable use across title, acquisition, demolition, rehabilitation, affordability, and neighborhood effects"),
            ("housing-voucher-mobility", "improve housing-voucher lease-up and mobility across payment standards, landlord participation, search, discrimination, and location"),
            ("condominium-reserve-safety", "govern condominium reserves and building safety across inspections, disclosures, assessments, insurance, and owner hardship"),
        ],
    },
    {
        "slug": "media-journalism-information-integrity",
        "scope": "United States media, journalism, and information-integrity policy",
        "audience": "a public-interest media and information-integrity consortium",
        "workstreams": [
            "audience, reach, trust, and information-need baselines",
            "constitutional, regulatory, platform, and contractual authority",
            "publisher, platform, advertiser, and creator incentives",
            "news-production capacity and local-market structure",
            "provenance, moderation, recommendation, and technical systems",
            "speech, privacy, civil-rights, and safety implications",
            "funding, ownership, competition, and sustainability",
            "measurement design, attribution, and denominator alignment",
            "counterevidence, uncertainty, and manipulation risk",
            "implementation safeguards, transparency, monitoring, and appeal",
        ],
        "domains": ["fcc.gov", "ftc.gov", "loc.gov", "gao.gov", "census.gov", "nist.gov", "congress.gov"],
        "cases": [
            ("local-news-sustainability", "strengthen local news across ownership, nonprofit conversion, public support, advertising, subscriptions, and editorial independence"),
            ("synthetic-media-disclosure", "govern synthetic-media disclosure across creation, distribution, provenance, exceptions, enforcement, and user comprehension"),
            ("election-information-resilience", "protect election information across official communication, platforms, local media, rumor response, and civil liberties"),
            ("platform-news-bargaining", "evaluate platform-news bargaining across market power, publisher distribution, newsroom support, competition, and unintended effects"),
            ("public-media-digital-transition", "modernize public media across broadcast, streaming, local service, accessibility, archives, funding, and independence"),
            ("health-misinformation-response", "design a health-misinformation response across authoritative communication, community trust, platforms, and uncertainty"),
            ("emergency-rumor-management", "build emergency rumor-management capacity across alerts, local messengers, monitoring, correction, language access, and trust"),
            ("newsroom-ai-governance", "govern newsroom use of AI across sourcing, verification, disclosure, copyright, labor, corrections, and accountability"),
            ("media-ownership-concentration", "assess media-ownership concentration across local competition, viewpoint diversity, employment, investment, and service"),
            ("children-digital-advertising", "govern digital advertising to children across targeting, influencers, disclosures, privacy, platform design, and enforcement"),
            ("community-information-needs", "fund community information services across news deserts, language access, civic coverage, distribution, and evaluation"),
            ("content-moderation-transparency", "design content-moderation transparency across rules, enforcement data, appeals, research access, privacy, and gaming risk"),
            ("journalist-source-protection", "strengthen journalist and source protection across subpoenas, device searches, surveillance, employment status, and exceptions"),
            ("crisis-image-verification", "improve crisis-image verification across provenance, geolocation, newsroom workflow, platform signals, speed, and error correction"),
        ],
    },
    {
        "slug": "nonprofits-philanthropy-social-impact",
        "scope": "United States nonprofit, philanthropy, and social-impact policy",
        "audience": "a nonprofit and philanthropic governance coalition",
        "workstreams": [
            "community need, service coverage, and outcome baselines",
            "tax, charity, grant, contract, and fiduciary authority",
            "beneficiary, organization, and program eligibility",
            "service quality, evidence, and implementation capacity",
            "revenue mix, reserves, overhead, and financial resilience",
            "governance, conflicts, accountability, and public trust",
            "equity, participation, accessibility, and community control",
            "impact measurement, attribution, and cost normalization",
            "counterevidence, displacement, and uncertainty boundaries",
            "portfolio sequencing, learning, monitoring, and exit conditions",
        ],
        "domains": ["irs.gov", "census.gov", "gao.gov", "grants.gov", "sba.gov", "dol.gov", "councilofnonprofits.org"],
        "cases": [
            ("foundation-payout-strategy", "set a foundation payout strategy across current need, perpetuity, liquidity, mission impact, and market stress"),
            ("nonprofit-reserve-policy", "design nonprofit reserve policies across operating volatility, restrictions, capital needs, emergency access, and donor communication"),
            ("community-grantmaking-power", "shift grantmaking power toward communities while preserving legal duties, evidence use, participation, and accountability"),
            ("social-service-contracting", "redesign government social-service contracts across true cost, payment timing, outcomes, compliance, and provider diversity"),
            ("fiscal-sponsorship-governance", "govern fiscal sponsorship across control, restricted funds, fees, liability, transition, and sponsored-project autonomy"),
            ("donor-advised-fund-policy", "evaluate donor-advised fund policy across payout, warehousing, privacy, sponsoring organizations, and charitable benefit"),
            ("nonprofit-merger-decision", "decide whether nonprofits should merge across mission fit, service continuity, finances, workforce, governance, and community trust"),
            ("volunteer-program-safeguards", "scale volunteer programs across screening, training, labor boundaries, accessibility, retention, and beneficiary safety"),
            ("impact-investing-allocation", "allocate an impact-investing portfolio across financial risk, additionality, measurement, liquidity, and mission alignment"),
            ("disaster-philanthropy-coordination", "coordinate disaster philanthropy across immediate relief, recovery, local organizations, duplication, equity, and accountability"),
            ("arts-nonprofit-stabilization", "stabilize arts nonprofits across earned revenue, public support, facilities, labor, access, programming, and reserves"),
            ("nonprofit-data-sharing", "govern nonprofit data sharing across service coordination, consent, privacy, interoperability, burden, and community benefit"),
            ("rural-nonprofit-capacity", "strengthen rural nonprofit capacity across staffing, funding access, collaboration, technology, service reach, and local control"),
            ("charitable-solicitation-oversight", "modernize charitable-solicitation oversight across registration, professional fundraisers, digital campaigns, fraud, and burden"),
        ],
    },
    {
        "slug": "work-employment",
        "scope": "United States work, employment, labor-market, and workforce policy",
        "audience": "a labor-market and workforce strategy commission",
        "workstreams": [
            "employment, wage, vacancy, and participation baselines",
            "federal, state, local, and contractual authority",
            "worker, employer, occupation, and program scope",
            "job quality, safety, scheduling, and benefit evidence",
            "skills, training, hiring, and advancement pathways",
            "business capacity, compliance cost, and labor demand",
            "disparities, accessibility, caregiving, and geographic effects",
            "earnings, productivity, cost, and denominator calculations",
            "counterevidence, substitution, displacement, and uncertainty",
            "phasing, enforcement, monitoring, and adjustment triggers",
        ],
        "domains": ["dol.gov", "bls.gov", "eeoc.gov", "osha.gov", "census.gov", "gao.gov", "nces.ed.gov"],
        "cases": [
            ("predictive-scheduling-policy", "design predictive-scheduling rules across notice, changes, worker income, employer flexibility, enforcement, and coverage"),
            ("paid-leave-program-design", "design paid family and medical leave across eligibility, wage replacement, financing, job protection, and administration"),
            ("warehouse-safety-productivity", "govern warehouse productivity and safety across quotas, injury evidence, monitoring, ergonomics, discipline, and enforcement"),
            ("care-workforce-stabilization", "stabilize the care workforce across wages, reimbursement, training, scheduling, benefits, and service affordability"),
            ("displaced-worker-transition", "support displaced workers across rapid response, income, training, credentials, relocation, and reemployment quality"),
            ("occupational-licensing-mobility", "reform occupational licensing across safety, interstate mobility, military families, immigrants, competition, and earnings"),
            ("seasonal-worker-protection", "protect seasonal workers across recruitment, housing, transportation, wages, safety, retaliation, and employer continuity"),
            ("older-worker-retention", "improve older-worker retention across job design, training, caregiving, disability, discrimination, retirement, and productivity"),
            ("worker-misclassification-enforcement", "target worker-misclassification enforcement across legal tests, industries, data, joint responsibility, and remedies"),
            ("youth-summer-employment", "design a youth summer-employment program across recruitment, work quality, supervision, pay, learning, safety, and long-term outcomes"),
            ("return-to-office-strategy", "set a return-to-office strategy across productivity, collaboration, recruitment, disability, caregiving, real estate, and retention"),
            ("minimum-wage-phasein", "design a minimum-wage phase-in across workers, employers, prices, employment, tipped work, regional variation, and enforcement"),
            ("portable-benefits-system", "evaluate portable benefits across covered workers, contributions, administration, portability, existing rights, and platform incentives"),
            ("workplace-heat-standard", "design workplace heat protections across thresholds, acclimatization, breaks, water, emergency response, industries, and enforcement"),
        ],
    },
]

ARCHETYPES = (
    (
        "professional",
        lambda profile, decision: (
            f"Build a live-web deep-research task for {profile['audience']} "
            f"deciding how to {decision}."
        ),
    ),
    (
        "community",
        lambda profile, decision: (
            "Build a live-web deep-research task for a community coalition "
            f"preparing to scrutinize a public proposal to {decision}."
        ),
    ),
    (
        "general_user",
        lambda profile, decision: (
            "Build a credible first-person live-web research request from someone "
            f"directly affected by the institutional decision about how to {decision}, "
            "who needs evidence for a well-informed meeting rather than personalized "
            "professional advice."
        ),
    ),
    (
        "investigative",
        lambda profile, decision: (
            "Build a live-web deep-research task for an investigative analyst "
            f"testing competing public claims about whether and how to {decision}."
        ),
    ),
    (
        "neutral_exploratory",
        lambda profile, decision: (
            "Build a neutral, open-ended live-web research request assessing the "
            f"conditions under which it would be justified to {decision}."
        ),
    ),
)


def build_ideas() -> list[dict]:
    ideas: list[dict] = []
    maximum_cases = max(len(profile["cases"]) for profile in PROFILES)
    for case_index in range(maximum_cases):
        for profile in PROFILES:
            if case_index >= len(profile["cases"]):
                continue
            idea_id, decision = profile["cases"][case_index]
            subject = idea_id.replace("-", " ")
            workstreams = [
                f"{subject}: {workstream}"
                for workstream in profile["workstreams"]
            ]
            archetype, request = ARCHETYPES[len(ideas) % len(ARCHETYPES)]
            ideas.append(
                {
                    "id": idea_id,
                    "idea": (
                        f"{request(profile, decision)} Require a cited long-form report that "
                        "reconstructs controlling authority and chronology, joins distributed "
                        "evidence across the named workstreams, resolves genuine scope/date/" 
                        "definition conflicts, performs multiple decision-relevant calculations, "
                        "rejects evidence-visible near-neighbor substitutions, preserves bounded "
                        "uncertainty, and reaches a conditional bottom line with practical "
                        "decision triggers."
                    ),
                    "scope": f"{profile['scope']}; target decision: {decision}",
                    "as_of": AS_OF,
                    "requester_archetype": archetype,
                    "task_mode": "structured_evidence_reconstruction",
                    "required_workstreams": workstreams,
                    "authoritative_domains": profile["domains"],
                }
            )
            if len(ideas) == 220:
                return ideas
    return ideas


def validate(ideas: list[dict]) -> None:
    if len(ideas) != 220:
        raise ValueError(f"expected 220 ideas, found {len(ideas)}")
    ids = [item["id"] for item in ideas]
    texts = [" ".join(item["idea"].casefold().split()) for item in ideas]
    scopes = [" ".join(item["scope"].casefold().split()) for item in ideas]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate idea id")
    if len(set(texts)) != len(texts):
        raise ValueError("duplicate idea text")
    if len(set(scopes)) != len(scopes):
        raise ValueError("duplicate scope")
    for item in ideas:
        if item.get("requester_archetype") not in {
            value[0] for value in ARCHETYPES
        }:
            raise ValueError(f"{item['id']} has an invalid requester archetype")
        if item.get("task_mode") != "structured_evidence_reconstruction":
            raise ValueError(f"{item['id']} has an invalid task mode")
        if len(item["required_workstreams"]) != 10:
            raise ValueError(f"{item['id']} must have exactly ten workstreams")
        if len(set(item["required_workstreams"])) != 10:
            raise ValueError(f"{item['id']} repeats a workstream")
        if len(item["authoritative_domains"]) < 6:
            raise ValueError(f"{item['id']} needs at least six authority hints")


def render_catalog(ideas: list[dict]) -> str:
    payload = {"version": 1, "ideas": ideas}
    return yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or verify the canonical idea catalog and shards."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify existing files byte-for-byte without modifying them",
    )
    parser.add_argument("--output-root", type=Path, default=ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ideas = build_ideas()
    validate(ideas)
    expected = {"ideas.yaml": render_catalog(ideas)}
    for index in range(11):
        expected[f"idea{index + 1}.yaml"] = render_catalog(
            ideas[index::11]
        )
    output_root = args.output_root.expanduser().resolve()
    if args.check:
        mismatches = [
            name
            for name, content in expected.items()
            if not (output_root / name).is_file()
            or (output_root / name).read_text(encoding="utf-8") != content
        ]
        if mismatches:
            raise SystemExit(f"idea catalogs are stale or missing: {mismatches}")
        print("verified 220 unique ideas and 11 disjoint 20-idea shards")
        return
    output_root.mkdir(parents=True, exist_ok=True)
    for name, content in expected.items():
        (output_root / name).write_text(content, encoding="utf-8")
    print("wrote 220 unique ideas and 11 disjoint 20-idea shards")


if __name__ == "__main__":
    main()
