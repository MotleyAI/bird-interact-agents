# households — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/households/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers to
distinguish "skipped on purpose" from "missed".

## KB 19 — Socioeconomic Index

Reason: KB defines this as "a weighted sum of income score,
expenditure ratio, and tenure score" but does not specify the weights
or how to normalise the three terms (their natural ranges differ).
Status: deferred. The agent at query time can compose it ad-hoc from
`households.tenure_type`, `households.income_bracket_score`, and
`households.expenditure_ratio` if a benchmark task requires a specific
weighting.

## KB 22 — Urban Household

Reason: KB says "'Municipal Piped' Water Access Type and high-quality
Road Surface Quality", but no `Municipal Piped` value appears in the
`infrastructure.wateraccess` data (the column carries 'Yes',
'available...' etc.). 'High-quality' road surface is also undefined.
Status: deferred — predicate would be a guess against the real
distinct values. Agent can compose from
`infrastructure.water_access_score` + `infrastructure.road_surface_score`
at query time.

## KB 23 — Mobile Household

Reason: "High Vehicle Ownership Index and a recent Vehicle Year Range"
— KB doesn't pin a numeric threshold for "high" or "recent". Status:
deferred. The agent has `transportation_assets.vehicle_ownership_index`
and `transportation_assets.newest_year_score` to filter on at query
time.

## KB 25 — Crowded Household

Reason: "Household Density greater than a threshold" — threshold
unspecified. Status: deferred; agent filters on
`properties.household_density > N` at query time.

## KB 26 — Modern Dwelling

Reason: "specific Dwelling Type and active Cable TV Status" — neither
"specific" type list nor "active" cable status values are pinned by
KB. Status: deferred.

## KB 27 — Well-Equipped Household

Reason: "high Infrastructure Quality Score and a high Service Support
Score" — both thresholds unspecified. Status: deferred; agent filters
on `infrastructure.infrastructure_quality_score` +
`service_types.service_support_score` at query time.

## KB 28 — Economically Stable Household

Reason: "high Socioeconomic Index and a low Expenditure Ratio".
Depends on KB #19 (deferred above) and undefined thresholds. Status:
deferred.

## KB 30 — Self-Sufficient Household

Reason: "limited Domestic Help Availability, social support 'No', and
high Vehicle Ownership Index" — "limited" and "high" thresholds
unspecified. Status: deferred; the agent has the helper columns to
filter on at query time.

## KB 31 — Purge Incomplete Transport Data

Reason: This is a DML operation (DELETE rows from
`transportation_assets` for households with NULL
`socioeconomic.Income_Bracket`), not a property of a SLayer model.
SLayer models describe queryable shape, not mutations. Status: not
applicable to model translation.

## KB 32 — Register New Household

Reason: DML operation (INSERT into `households`). See KB #31 reasoning.
Status: not applicable to model translation.

## KB 33 — Update Vehicle Inventory

Reason: DML operation (UPDATE on `transportation_assets`). See KB #31
reasoning. Status: not applicable to model translation.

## KB 34 — Residential Zone Types

Reason: KB describes 'Urban' / 'Suburban' / 'Rural' / 'Mixed' zone
types, but the `households.locregion` and `households.loczone` columns
hold administrative-region codes and macrozone numbers, not these
labels. No source field carries this concept in the schema. Status:
not encodable from current data; this looks like a stale or aspirational
KB entry.

## KB 35 — Utility Access Level

Reason: KB describes 'Full' / 'Partial' / 'Basic' / 'None' utility
levels, but no schema column carries this composite indicator (water,
cable, etc are split across `infrastructure` and `amenities`). Could
be derived in principle, but KB doesn't pin the exact rule. Status:
not encodable from current data.

## KB 38 — Dwelling Condition Status

Reason: KB describes 'Excellent' / 'Good' / 'Fair' / 'Poor' condition
labels, but no schema column tracks dwelling condition. Status: not
encodable from current data.

## KB 39 — Compact Household

Reason: "specific Dwelling Type and a small resident count" — neither
the type list nor the resident-count threshold is pinned. Status:
deferred.

## KB 40 — High-Mobility Urban Household

Reason: References KB #34 (Residential Zone Types — not encodable) and
KB #36 (vehicle type distribution — encoded). Without zone types in
schema, this composite predicate can't be encoded. Status: blocked on
schema gap (KB #34).

## KB 41 — Stable Infrastructure Household

Reason: References KB #35 (Utility Access Level — not encodable) and
road surface (encoded). Blocked on KB #35. Status: blocked on schema
gap (KB #35).

## KB 43 — Well-Maintained Dwelling

Reason: References KB #38 (Dwelling Condition Status — not encodable)
and KB #7 (cable status — encoded). Blocked on KB #38. Status:
blocked on schema gap (KB #38).
