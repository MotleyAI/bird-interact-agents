# labor_certification_applications — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/labor_certification_applications/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers to
distinguish "skipped on purpose" from "missed".

The dataset has 981 cases all received on a single date (2023-12-21),
so anything that needs cross-year, multi-month, or population data
either degrades or has no source data. Most ratios/aggregations encode
fine; the deferrals below are the genuine gaps.

## KB 22 — Cost of Living Adjusted Wage (CLAW)

Reason: KB defines `CLAW = (Offered Wage / Cost of Living Index) × 100`
where Cost of Living Index has 100 = national average. No
`cost_of_living_index` column exists on `worksite`, `case_worksite`,
`employer`, or any other table; the schema has no per-city/state COL
data. Status: deferred — the agent can compose ad-hoc only by joining
an external COL table not present here.

## KB 36 — Wage Growth Rate (WGR)

Reason: KB defines WGR = ((current_year_avg_wage − previous_year_avg_wage)
/ previous_year_avg_wage) × 100. Every row in this dataset has
`recvday = '2023/12/21'`, so there is no "previous year" to compare
against — the cross-year pivot collapses to a single year. Status:
deferred — degenerate against this snapshot. The aggregation
infrastructure (avg offered wage by year via `cases.recvday` →
year, joined to `case_worksite.offered_wage_annual`) is in place; only
the time-series data is missing.

## KB 38 — Worksite Cost Index (WkCI)

Reason: KB defines `WkCI = (Worksite Cost of Living / National Average
Cost of Living) × 100`. Like KB #22 (CLAW), this needs a per-worksite
cost-of-living value that is not in the schema. Status: deferred — no
source field carries this concept.

## KB 42 — Visa-Dependent Industry

Reason: KB defines a visa-dependent industry as one where "the
percentage of visa applications relative to the total workforce
exceeds 15%". The dataset has no workforce / employment-base data to
divide visa apps by; we only have visa application counts (numerator),
not denominator. Status: deferred. KB #20 (Industry Application
Distribution) is encoded and gives the share of *applications* (not
workforce) per industry — that's the closest available proxy.

## KB 49 — Occupational Specialization Levels

Reason: KB defines General / Specialized / Highly Specialized but
gives no thresholds and no source field for "specialization level".
KB hints at correlation with wage level and experience but doesn't
pin a rule. Status: deferred — can't encode a CASE without numeric
boundaries. Agent can filter on
`prevailing_wage.prevailing_wage_level` (I-IV, KB #5) at query time
as a proxy.

## KB 53 — Worksite Geographic Diversity

Reason: KB defines Single-Location (all apps for one location),
Regional (multiple locations in one region), or National (multiple
regions). The "region" concept is not in the schema — `worksite` only
has state/city/county, no region grouping. Single-Location vs
multi-location is encodable (compare distinct worksite count to 1,
related to KB #27 WDI which is encoded), but the Regional/National
split requires a state→region mapping not present in this dataset.
Status: deferred — partial logic possible (Single-Location vs
multi-location) but the canonical 3-class distinction is blocked on
the missing region field.

## KB 54 — Employer Dependency Level

Reason: KB defines tiers based on "less than 5% / 5-15% / over 15%
of workforce" — needs employer total-workforce numbers. Same data
gap as KB #2 (H-1B Dependency Status) and KB #42: only the visa
applications side of the ratio is recorded. Status: deferred —
workforce denominator not in the schema. The H-1B-dependent flag
itself (`cases.h1bdep`, encoded under KB #2) approximates the High
Dependency tier.

## KB 55 — Position Scarcity Index

Reason: KB defines Abundant / Moderate Scarcity / High Scarcity but
gives no thresholds or formula — KB only says "often correlated with
wage premiums and processing priorities". Status: deferred — no
encodable rule. Agent can rank by
`occupational_demand_index.odi` (KB #21, encoded) and
`prevailing_wage.wage_premium_rate` (KB #17, encoded) at query time
as a proxy.
## KB 14 — Attorney Case Load (ACL)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 16 — Worksite Density (WD)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 18 — Application Success Rate (ASR)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 19 — State Application Distribution (SAD)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 20 — Industry Application Distribution (IAD)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 29 — Visa Class Distribution (VCD)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 34 — Attorney Specialization Index (ASI)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

