# solar - KB entries not encoded as model entities

The 8 auto-ingested tables (`alerts`, `electrical`, `environment`,
`inverter`, `maintenance`, `panel`, `panel_performance`, `plant`)
all share a single `growregistry`/`hubregistry`/`siteref`/`arearegistry`
key in this dataset (1:1 alignment by plant), so most cross-table
formulas (TPCI, IEL, EPE, TAPR, TSL, EEY, WCE, EDI, FFDR, etc.) can be
inlined as `Column.sql` against `panel.environment.*` and
`panel.inverter.*` peer-joins through `panel`. The composite domain
predicates (KB#40 Advanced Performance Degradation Alert, KB#41
Premium Maintenance Candidate, KB#50 Maintenance Urgency
Classification, KB#42 Optimal Cleaning Schedule, KB#44 End-of-Warranty
Optimization, KB#52 Degradation Severity, KB#10 Critical Performance
Threshold, KB#15 Optimal Performance Window) are encoded directly on
the host model whose grain matches the predicate.

One non-trivial bookkeeping note: the `solar` `performance` table
collides with an already-existing `performance` model in the live
SLayer storage owned by `exchange_traded_funds`. Auto-ingest skipped
the solar copy. The solar version was therefore created under the
unique name **`panel_performance`** (`sql_table=performance`,
`data_source=solar`); FK joins from `electrical`, `alerts`, and
`maintenance` were rewritten to point at `panel_performance` instead
of the (wrong-data-source) `performance` model. This is a real
ingestion bug surfaced by the cross-DB shared SLayer storage; in
production the per-DB YAMLStorage layout written by
`export_slayer_models.py` makes the issue moot.

The 11 KB ids in this file are deferred because the schema is missing
data the formula depends on, the formula is not algebraically pinned,
or the predicate cascades from a deferred parent.

## KB 9 — Irradiance Utilization Ratio (IUR)

Reason: formula is `(MeasuredPowerW / PanelAreaM2) / POAIrradianceWM2`,
but `PanelAreaM2` is not a column anywhere in the solar schema (panel
table has `powratew`, `paneeffpct`, `nomtempc`, `tempcoef`, but no
area). KB#28 description (POAIrradianceWM2) and KB#9's POA reference
are encoded as `environment.poa_irradiance_wm2`, but the ratio itself
can't be computed.

Status: deferred - missing input column (PanelAreaM2).

## KB 11 — Hot Spot Risk

Reason: predicate compares a panel's Voc/Isc against "other panels in
the same string" with > 5% deviation. The schema has no "string"
identifier - the only panel-grouping is via `panel.hubregistry`
(plant), which is too coarse (1 panel per plant in this dataset). Plus
the cell-temp branch needs ambient temperature from `environment` -
that part is reachable through the `panel.environment` peer-join, but
without a string membership the deviation comparison can't be
expressed.

Status: deferred - schema lacks "string" grouping identifier.

## KB 16 — Panel String Mismatch

Reason: same root cause as KB#11. Stddev of Imp/Isc across panels in a
"string" exceeds 3% of mean. No string identifier in the schema.

Status: deferred - schema lacks "string" grouping identifier.

## KB 17 — Warranty Claim Threshold

Reason: requires the manufacturer's "warranty curve" (typical
guarantee like 80% of nameplate at year 25) + 3 consecutive
underperforming measurements. Neither the curve coefficients nor the
"3 consecutive" temporal predicate are pinned in the KB or expressible
without a manufacturer reference table that the schema doesn't
provide.

Status: deferred - missing manufacturer warranty curve data.

## KB 33 — Effective Performance Index (EPI)

Reason: formula is `PPR x (1 - TSL/PowerRatedW) x (IUR/PaneEffPct)`.
PPR (KB#0), TSL (KB#31), PowerRatedW, and PaneEffPct are all encoded,
but IUR (KB#9) is deferred because PanelAreaM2 is missing. EPI
cascades.

Status: deferred - cascades from KB#9 (IUR depends on missing
PanelAreaM2).

## KB 39 — Financial Impact of Degradation (FID)

Reason: formula is
`GenCapMW x 1000 x NDI x PELR x ElectricityPricePerKWh x 24 x 365`.
The `ElectricityPricePerKWh` constant has no source in the solar
schema (no pricing / tariff table). All other inputs (NDI, PELR,
GenCapMW) are encoded.

Status: deferred - missing ElectricityPricePerKWh constant / pricing
table.

## KB 43 — High-Risk Weather Condition

Reason: predicate is `WSI > 7.0 AND CellTempC > upper limit of Optimal
Performance Window` (45 C). The cell-temp half is trivially
encodable, but `WSI` (KB#18 Weather Severity Index) is itself a prose
composite without a closed-form definition - encoded as a JSON bundle
of inputs (`environment.weather_severity_inputs`) but not as a single
scalar threshold.

Status: deferred - cascades from KB#18 (WSI is a prose-only composite).

## KB 46 — System Upgrade Candidate

Reason: predicate is
`FID > 10% of replacement_cost AND EPI < 0.85 for 3 consecutive
months`. Both FID (KB#39) and EPI (KB#33) are deferred, plus the
"3 consecutive months" temporal aggregation across panel_performance.

Status: deferred - cascades from KB#39 and KB#33.

## KB 47 — Inverter-Panel Compatibility Index

Reason: condition is
`WCE within 5% of manufacturer's specifications AND inverteffpct > 97%`.
The "manufacturer's specifications" baseline is not in the schema (no
mfr WCE-curve column on panel, no nameplate-WCE constant). The
inverteffpct branch is encoded (KB#29) but the WCE-vs-mfr-spec branch
can't be expressed.

Status: deferred - missing manufacturer WCE specification baseline.

## KB 48 — Environmental Stress Classification

Reason: classifies based on combining WSI (KB#18, deferred composite)
and "exposure time outside the Optimal Performance Window" - the
latter requires a temporal aggregation of `environment.in_optimal_window`
over an unspecified window (presumably trailing days/weeks). Neither
the WSI scalar nor the exposure-time window length are pinned.

Status: deferred - cascades from KB#18 plus undefined exposure-time
window.

## KB 49 — Total Economic Performance

Reason: prose meta-metric "combining Maintenance Return on Investment
(MROI), Financial Impact of Degradation (FID), and revenue generation
adjusted by the Effective Performance Index (EPI)" without a closed-
form aggregation rule. FID (KB#39) and EPI (KB#33) are themselves
deferred.

Status: deferred - prose-only meta-metric; cascades from KB#39, #33.
