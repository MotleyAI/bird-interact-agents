# mental — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/mental/`. The verifier (`scripts/verify_kb_coverage.py`)
reads the `## KB <id> — …` headers to distinguish "skipped on
purpose" from "missed".

The bulk of these are **composite metrics or predicates that combine
facility-level aggregates from different tables** (e.g. TAR on
`treatmentoutcomes` × TES on `treatmentbasics`). SLayer named-measure
formulas can compose measures *within the same model*, but a
cross-model named measure requires an explicit aggregation
(`treatmentbasics.tes:avg`, etc.), so a saved
`(tes + tar*3)/2`-style formula on either host model would be invalid
without a multistage `R-MULTISTAGE` rollup that aggregates each
component per facility before combining.

Per the skill's "Peer-join composites defer to notes" guidance, the
agent at query time can compose these on-the-fly by issuing one query
per component metric (each grouped by facility) and combining the
results client-side, or by writing a query-backed multistage model
ad-hoc when the benchmark task pins concrete thresholds.

## KB 12 — Complex Care Needs

Reason: Combines two facility-level aggregates (SRP > 20% on
`assessmentsymptomsandrisk`, PFIS > 2.5 on
`assessmentsocialanddiagnosis`) with a per-row predicate (`subuse in
{Opioids, Multiple}`). Cross-aggregation, cross-table — needs an
R-MULTISTAGE rollup.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 31 — Engagement-Adherence Score (EAS)

Reason: `(TES + TAR×3) / 2` mixes a measure on `treatmentbasics` with
one on `treatmentoutcomes`. Cross-model named-measure composition
requires an explicit aggregation, so the saved formula can't be a
simple bare-name reference.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 32 — Facility Risk Profile Index (FRPI)

Reason: `(SRP/100 × 5) + PFIS` crosses `assessmentsymptomsandrisk` and
`assessmentsocialanddiagnosis`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 33 — Patient Stability Metric (PSM)

Reason: `1 / (1 + CIF + MAR)` — CIF on `treatmentbasics`, MAR on
`encounters`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 34 — Resource-Demand Differential (RDD)

Reason: `PFIS − FRAI` crosses `assessmentsocialanddiagnosis` and
`facilities`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 35 — Socio-Environmental Support Index (SESI)

Reason: `(avg(SSE) + FRAI) / 2` crosses `assessmentsocialanddiagnosis`
and `facilities`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 36 — Adherence Effectiveness Ratio (AER)

Reason: `TAR / PFIS` crosses `treatmentoutcomes` and
`assessmentsocialanddiagnosis`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 37 — Engagement Deficit Index (EDI)

Reason: `(3 − TES) × (1 + MAR)` crosses `treatmentbasics` and
`encounters`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 38 — Comprehensive Facility Risk Score (CFRS)

Reason: `APSF/27 + SRP/100 + PFIS/3` crosses
`assessmentsymptomsandrisk` and `assessmentsocialanddiagnosis`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 39 — Support System Pressure Index (SSPI)

Reason: `CIF / (avg(SSE) + 1)` crosses `treatmentbasics` and
`assessmentsocialanddiagnosis`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 40 — High-Need, Under-Resourced Facility

Reason: `FRPI > 4.5 AND FRAI < 1.5` — predicate over two
facility-level aggregates that themselves require multistage rollups
(KB 32, KB 5).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 41 — Facility with Engaged but High-Impairment Population

Reason: `EAS > 2.0 AND PFIS > 2.0` — predicate over
cross-aggregation composites (KB 31, KB 6).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 43 — Facility Attrition Risk Indicator

Reason: `EAS < 1.5 AND MAR > 2.5` — predicate over
cross-aggregation composites (KB 31, KB 9).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 44 — Well-Resourced High-Support Environment

Reason: `FRAI ≥ 2.0 AND avg(SSE) ≥ 4.5` — facility-level aggregates
across `facilities` and `assessmentsocialanddiagnosis`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 46 — Facility with Potential Treatment Inertia

Reason: `TES > 2.2 AND TAR < 0.6` — facility-level aggregates across
`treatmentbasics` and `treatmentoutcomes`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 48 — Facility Demonstrating Strong Patient Retention

Reason: `TAR > 0.75 AND MAR < 1.0` — facility-level aggregates across
`treatmentoutcomes` and `encounters`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 50 — Clinical Improvement Potential Index (CIPI)

Reason: `EAS / (SSI + 1)` — both children are themselves
cross-aggregation composites (KB 31, KB 30).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 51 — Facility Efficiency Index (FEI)

Reason: `PSM × FRAI` — PSM is itself a cross-aggregation composite
(KB 33).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 52 — Therapeutic Alliance & Engagement Score (TAES)

Reason: `(avg(theralliance_score) + TES) / 2` crosses
`treatmentoutcomes` and `treatmentbasics`. The per-row CASE for
theralliance_score is encoded as a column on `treatmentoutcomes`, but
combining with TES across tables is the deferred part.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 53 — Recovery Trajectory Index (RTI)

Reason: `avg(funcimpv_score) × TAR` — both come from
`treatmentoutcomes`, so this could in principle be a saved measure on
that model (`funcimpv_score:avg * tar`). Deferred only because the
KB description scopes it to a *facility*, which adds the same
aggregation-over-aggregation flavour as the others. The funcimpv_score
column is encoded.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 54 — Crisis Adherence Ratio (CAR)

Reason: `CIF / (TAR + 0.01)` crosses `treatmentbasics` and
`treatmentoutcomes`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 55 — Facility with High Clinical Leverage Potential

Reason: `EAS > 2.5 AND SSI > 15` — predicate over two
cross-aggregation composites (KB 31, KB 30).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 56 — Patient Exhibiting Fragile Stability

Reason: Combines Stable Recovery (KB 13, encoded on
`assessmentsocialanddiagnosis`) with per-patient aggregate predicates
(`avg missappt > 2` over encounters, `individual SSE < 3`). The
patient-grain aggregation requires a multistage rollup.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 57 — Resource-Intensive High-Risk Patient Cohort

Reason: Conjunction of Complex Care Needs (KB 12, deferred) and
Frequent Crisis Patient (KB 17, encoded). Blocked on KB 12.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 58 — Facility with Potential Engagement-Outcome Disconnect

Reason: `TES > 2.0 AND RTI < 0.8` — facility-level aggregates across
`treatmentbasics` and `treatmentoutcomes`.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 59 — Systemically Stressed Facility Environment

Reason: `RDD > 1.0 AND Facility Attrition Risk Indicator` — composite
of two deferred facility-level composites (KB 34, KB 43).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 60 — Correlation Between Resource Adequacy and Adherence (CRAA)

Reason: `CORR(resource_score, tar)` over per-facility rows. Requires a
multistage rollup that produces one row per facility carrying both
columns, then applies SLayer's `corr` UDF. The per-row inputs
(`facilities.resource_score`, `treatmentoutcomes.tar` per facility)
are encoded as building blocks.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 61 — Facility Performance Quadrant (FPQ)

Reason: Quadrant assignment via `NTILE(2) OVER ()` on per-facility TAR
and PSM. R-WINDOW recipe over a multistage that already needs PSM
(KB 33, deferred).
Status: deferred to W5 R-WINDOW encoding (also blocked on KB 33).
