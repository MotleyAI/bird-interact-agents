# households — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/households/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers to
distinguish "skipped on purpose" from "missed".

Helper columns named below remain encoded on their host models (without
`meta.kb_id`) so the agent can compose the deferred predicates ad-hoc
at query time.

## KB 16 — Service Support Score

Reason: KB definition reads "A weighted score combining domestic help
availability and social assistance participation status (Yes/No)" — the
weights are not specified, and the domestic-help score is itself a
guessed ordinal (the KB only enumerates categories, not numeric values).
Any specific weighting would be a guess.

Helpers available: `service_types.domestic_help_score` (ordinal 1..4
helper for `domestichelp`) and `service_types.soc_support_score`
(1/0 for `socsupport`). The agent can compose any weighting at query
time.

Status: deferred — AMBIGUOUS-PROSE

## KB 18 — Mobility Score

Reason: "The product of the vehicle count and a numeric mapping of the
newest vehicle year." The numeric mapping for year ranges is not
specified by KB #10 or KB #18. Any mapping (ordinal rank, midpoint of
range, last year of range, etc.) would be a guess.

Helpers available: `transportation_assets.vehicle_ownership_index`
(KB #14), `transportation_assets.vehicleinventory__Newest_Year`
(KB #10 raw text).

Status: deferred — AMBIGUOUS-PROSE

## KB 19 — Socioeconomic Index

Reason: "Calculated as a weighted sum of income score, expenditure
ratio, and tenure score." Weights are not specified, and the tenure
score numeric mapping is not specified by KB #1.

Helpers available: `households.income_bracket_score` (ordinal 0..11),
`households.expenditure_ratio` (KB #12), and the raw tenure column
`households.socioeconomic__Tenure_Type` (KB #1).

Status: deferred — AMBIGUOUS-PROSE

## KB 21 — Affluent Household

Reason: "A household with a 'Tenure_Type' of 'OWNED' and an
'Income_Bracket' of either 'High Income' or 'Very High Income'." The
literal bracket labels 'High Income' / 'Very High Income' do not
appear in the schema — `socioeconomic.Income_Bracket` carries
currency-range strings ('More than R$ 880 and less than R$ 1,760',
…). Mapping which currency brackets count as 'High' / 'Very High' is
a guess.

Helpers available: `households.income_bracket_score` and
`households.socioeconomic__Tenure_Type` (raw text; tenure values
normalize via `LOWER(TRIM(...))`).

Status: deferred — AMBIGUOUS-PROSE

## KB 22 — Urban Household

Reason: KB defines this as "'Municipal Piped' Water Access Type and
high-quality Road Surface Quality". The literal string 'Municipal
Piped' does not appear in `infrastructure.wateraccess`; the column
carries 'Yes, available at least in one room' and similar values.
"High-quality" road surface is also not pinned (KB #4 distinguishes
Asphalt/Concrete from others without using the word "high-quality"
itself).

Helpers available: `infrastructure.water_access_score` (KB #3),
`infrastructure.road_surface_score` (KB #4).

Status: deferred — AMBIGUOUS-PROSE

## KB 23 — Mobile Household

Reason: "A household with a high Vehicle Ownership Index and a recent
Vehicle Year Range." Neither "high" nor "recent" is given a numeric
threshold or band list.

Helpers available: `transportation_assets.vehicle_ownership_index`
(KB #14), `transportation_assets.vehicleinventory__Newest_Year`
(KB #10).

Status: deferred — AMBIGUOUS-PROSE

## KB 25 — Crowded Household

Reason: "A household with Household Density greater than a threshold."
KB explicitly says "a threshold" without naming a number.

Helper available: `properties.household_density` (KB #11).

Status: deferred — AMBIGUOUS-PROSE

## KB 26 — Modern Dwelling

Reason: "A dwelling with specific Dwelling Type and active Cable TV
Status." The "specific Dwelling Type" set is not enumerated — KB #6
distinguishes 4-point/3-point/1-point dwelling types but the KB #26
predicate does not pin which subset counts as "modern".

Helpers available: `properties.dwelling_specs__Dwelling_Class`
(raw text), `properties.dwelling_type_score` (KB #44),
`amenities.cable_available` (boolean derived from KB #7).

Status: deferred — AMBIGUOUS-PROSE

## KB 27 — Well-Equipped Household

Reason: "A household with a high Infrastructure Quality Score and a
high Service Support Score." Both thresholds are unspecified, and the
Service Support Score itself (KB #16) has unspecified weights.

Helpers available: `infrastructure.infrastructure_quality_score`
(KB #13), `service_types.domestic_help_score`,
`service_types.soc_support_score`.

Status: deferred — AMBIGUOUS-PROSE

## KB 28 — Economically Stable Household

Reason: "A household with a high Socioeconomic Index and a low
Expenditure Ratio." Depends on KB #19 (deferred — weights unspecified)
and adds two more unspecified thresholds ("high" / "low").

Helpers available: `households.expenditure_ratio` (KB #12),
`households.income_bracket_score`.

Status: deferred — AMBIGUOUS-PROSE

## KB 30 — Self-Sufficient Household

Reason: "A household with limited Domestic Help Availability, social
support status of 'No', and high Vehicle Ownership Index." "Limited"
and "high" are not pinned; only the social-support clause is concrete.

Helpers available: `service_types.domestic_help_score`,
`service_types.socsupport` (KB #9),
`transportation_assets.vehicle_ownership_index` (KB #14).

Status: deferred — AMBIGUOUS-PROSE

## KB 31 — Purge Incomplete Transport Data

Reason: KB definition explicitly says "Delete records from the
transportation assets data for any household where the income
classification is NULL." DML operations are out-of-scope for SLayer
models, which describe queryable shape, not mutations.

Status: deferred — DML

## KB 32 — Register New Household

Reason: KB definition explicitly says "Insert a new record into the
household data with all required information." DML — out-of-scope
(see KB #31).

Status: deferred — DML

## KB 33 — Update Vehicle Inventory

Reason: KB definition explicitly says "Update the vehicle inventory
data for a specific household, modifying fields such as newest vehicle
year or vehicle counts." DML — out-of-scope (see KB #31).

Status: deferred — DML

## KB 34 — Residential Zone Types

Reason: KB describes value labels 'Urban' / 'Suburban' / 'Rural' /
'Mixed'. The schema's `households.locregion` carries administrative
region names (e.g. 'Taguatinga') and `households.loczone` carries
numeric zone codes — neither column carries the four labels KB #34
names. KB #45 ("loczone = 1 ⇒ urban") is the only zone-type rule the
schema can express, and is encoded as `households.is_urban_zone`.

Status: deferred — SCHEMA-GAP

## KB 35 — Utility Access Level

Reason: KB describes composite labels 'Full' / 'Partial' / 'Basic' /
'None' over (water + cable + ?). No schema column carries this
composite indicator, and the KB does not pin the exact rule for
mapping individual utility flags to the four levels.

Helpers available: `infrastructure.water_access_score`,
`amenities.cable_available`.

Status: deferred — AMBIGUOUS-PROSE

## KB 37 — Social Assistance Participation

Reason: Verbatim restatement of KB 9; encoded entity is
`service_types.socsupport` with `meta.kb_id = 9`. KB #9 and KB #37
both describe the same Yes/No social-assistance column with the same
"part of unique constraint combination" wording.

Status: not-applicable — duplicate of KB 9

## KB 38 — Dwelling Condition Status

Reason: KB describes value labels 'Excellent' / 'Good' / 'Fair' /
'Poor'. No schema column tracks dwelling condition; `properties` only
carries `Bath_Count`, `Room_Count`, `Dwelling_Class` (structural
type, not condition).

Status: deferred — SCHEMA-GAP

## KB 39 — Compact Household

Reason: "A household with specific Dwelling Type and a small resident
count." Neither the type list nor the "small" resident-count threshold
is pinned by the KB.

Helpers available: `properties.dwelling_specs__Dwelling_Class`,
`properties.dwelling_type_score`, `households.residentcount`.

Status: deferred — AMBIGUOUS-PROSE

## KB 40 — High-Mobility Urban Household

Reason: "A household with specific Residential Zone Type and Vehicle
Type Distribution." The Residential Zone Type concept (KB #34) is not
in the schema, so the urban-zone clause cannot be expressed beyond
KB #45's narrower `loczone = 1` rule. KB #36 (vehicle_counts) is
encoded but the predicate side ("specific … Vehicle Type
Distribution") is itself unpinned.

Helpers available: `households.is_urban_zone` (KB #45),
`transportation_assets.auto_count`, `transportation_assets.bike_count`,
`transportation_assets.motor_count`,
`transportation_assets.vehicle_ownership_index` (KB #14).

Status: deferred — SCHEMA-GAP

## KB 41 — Stable Infrastructure Household

Reason: "A household with a specific Utility Access Level and Road
Surface Quality." Depends on KB #35 (Utility Access Level — unpinned).
The road-surface side resolves to KB #4 helpers, but the composite
predicate is blocked on KB #35.

Helpers available: `infrastructure.road_surface_score`,
`infrastructure.water_access_score`, `amenities.cable_available`.

Status: deferred — AMBIGUOUS-PROSE

## KB 42 — Economically Independent Household

Reason: "A household with high Income Classification and social
support status of 'No'." "High Income Classification" is not pinned by
KB #2 (the brackets are R$ ranges, not labels like 'High'); the
socsupport='No' part is concrete but cannot be combined without a
threshold.

Helpers available: `households.income_bracket_score`,
`service_types.socsupport` (KB #9).

Status: deferred — AMBIGUOUS-PROSE

## KB 43 — Well-Maintained Dwelling

Reason: "A dwelling with specific Dwelling Condition Status and Cable
TV Status." Depends on KB #38 (Dwelling Condition Status — not in
schema). Cable side resolves to KB #7 helpers, but the composite
predicate is blocked on KB #38.

Helper available: `amenities.cable_available`.

Status: deferred — SCHEMA-GAP
