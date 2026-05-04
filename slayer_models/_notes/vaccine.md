# vaccine — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/vaccine/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers to
distinguish "skipped on purpose" from "missed".

The vaccine schema's auto-FK joins go child → parent (sensordata →
container, vaccinedetails → container, transportinfo → container, etc.).
They do **not** auto-resolve peer-table references between two children
of the same parent (e.g. vaccinedetails ↔ sensordata both via
container). Composite metrics that span multiple peer tables can't be
inlined as a single `Column.sql` — they need an R-MULTISTAGE
query-backed model that joins each peer to the parent separately and
then composes.

The other major class of deferral is metrics that need access to a
*previous reading* (KB #50 TSC, KB #52 TWQD) or rolling time windows
across sensordata rows (KB #10) — those need either window-function
multistage models or a query-time time-shift transform, not a static
Column.

## KB 3 — Vaccine Viability Period (VVP)

Reason: VVP = (ExpireDay - Current_Date) * TSS. ExpireDay lives on
`vaccinedetails`; TSS is computed from `sensordata`. Both are children
of `container` with no FK between them. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 10 — Container Health Status

Reason: Four-level classification keyed on `average TSS` and
`maximum TBS` "over the past 1 year" plus a cross-reference to the
current TSS. Needs an aggregation over a rolling time window of
sensordata grouped by container, then a CASE on the aggregated
values. Status: deferred to W4b R-MULTISTAGE encoding (rolling-window
flavour).

## KB 12 — High-Risk Route

Reason: RCP < 50% AND CRI > 0.4. RCP is on `transportinfo`; CRI is
computed on `sensordata`. Both peer-children of `container`. Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 18 — Efficient Container

Reason: SER > 0.8 AND TSS > 0.9. SER is on `vaccinedetails`; TSS is on
`sensordata`. Peer-children of `container`. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 19 — Quality Compromise

Reason: VVP < 30 OR QualCheck = 'Failed'. Depends on KB #3 (VVP, also
deferred). Status: deferred — cascades from KB #3.

## KB 32 — Combined Maintenance Risk (CMR)

Reason: (1 - MCS) * (1 + TBS/5) * (1 - LHI). MCS lives on
`regulatoryandmaintenance`, TBS on `sensordata`, LHI on `datalogger`.
Three peers all linked to different parents. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 33 — Shipment Quality Index (SQI)

Reason: VVP/365 * HQI * (1 - CRI). Depends on KB #3 (VVP, deferred).
Status: deferred — cascades from KB #3.

## KB 34 — Logger Reliability Score (LRS)

Reason: LHI * (1 - CMR) * TSS. Depends on KB #32 (CMR, deferred).
Status: deferred — cascades from KB #32.

## KB 35 — Transport Safety Rating (TSR)

Reason: RCP/100 * (1 - TRS) * HQI. RCP on `transportinfo`, TRS+HQI on
`sensordata`. Peer-join. Status: deferred to W4b R-MULTISTAGE
encoding.

## KB 36 — Container Efficiency Score (CES)

Reason: SER * CEI * (1 - CRI). SER on `vaccinedetails`, CEI on
`sensordata`. Peer-join. Status: deferred to W4b R-MULTISTAGE
encoding.

## KB 37 — Quality Maintenance Index (QMI)

Reason: MCS * SQI * (1 - TBS/10). Depends on KB #33 (SQI, deferred).
Status: deferred — cascades from KB #33.

## KB 38 — Route Risk Factor (RRF)

Reason: (1 - RCP/100) * TRS * (1 - CEI). RCP on `transportinfo`,
TRS+CEI on `sensordata`. Peer-join. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 39 — Vaccine Safety Index (VSI)

Reason: VVP/365 * CEI * (1 - TRS). Depends on KB #3 (VVP, deferred).
Status: deferred — cascades from KB #3.

## KB 40 — Critical Transport Condition

Reason: TSR < 0.4 AND TRS > 0.6. Depends on KB #35 (TSR, deferred).
Status: deferred — cascades from KB #35.

## KB 41 — Severe Container Risk

Reason: CES < 0.3 AND CEI < 0.5. Depends on KB #36 (CES, deferred).
Status: deferred — cascades from KB #36.

## KB 42 — High Maintenance Priority

Reason: CMR > 0.7 AND QMI < 0.4. Depends on KB #32 (CMR) and KB #37
(QMI), both deferred. Status: deferred — cascades.

## KB 43 — Critical Route Status

Reason: RRF > 0.8 AND TSR < 0.3. Depends on KB #38 (RRF) and KB #35
(TSR), both deferred. Status: deferred — cascades.

## KB 44 — Unsafe Vaccine Condition

Reason: VSI < 0.4 AND CES < 0.5. Depends on KB #39 (VSI) and KB #36
(CES), both deferred. Status: deferred — cascades.

## KB 45 — Logger Critical State

Reason: LRS < 0.3 AND CMR > 0.8. Depends on KB #34 (LRS) and KB #32
(CMR), both deferred. Status: deferred — cascades.

## KB 46 — Quality Alert Status

Reason: QMI < 0.3 AND VSI < 0.5. Depends on KB #37 (QMI) and KB #39
(VSI), both deferred. Status: deferred — cascades.

## KB 47 — Transport Safety Alert

Reason: TSR < 0.5 AND RRF > 0.7. Depends on KB #35 (TSR) and KB #38
(RRF), both deferred. Status: deferred — cascades.

## KB 48 — Container Alert Status

Reason: CES < 0.4 AND TRS > 0.7. Depends on KB #36 (CES, deferred).
Status: deferred — cascades from KB #36.

## KB 49 — Critical Safety Condition

Reason: VSI < 0.3 AND TSR < 0.4. Depends on KB #39 (VSI) and KB #35
(TSR), both deferred. Status: deferred — cascades.

## KB 50 — Thermal Stability Coefficient (TSC)

Reason: TSC = TSS * exp(-|TempNowC - StoreTempC|/5) * (1 - alpha *
(TempNowC - TempPrevC)/ReadingInterval). Requires the *previous*
sensordata row's TempNowC (a window-function lag) and a tunable alpha.
There's no `TempPrevC` column on the schema. Status: deferred —
needs an R-WINDOW / R-MULTISTAGE encoding with `LAG(tempnowc)`.

## KB 51 — Multi-Parameter Risk Assessment (MPRA)

Reason: sqrt(CRI^2 + TBS^2 + (1 - HQI)^2) * (1 + CDR/CDR_max). The
CRI/TBS/HQI piece is encodable on sensordata, but `CDR_max` is a
dataset-wide normalisation constant the KB doesn't pin (max over the
whole table, max per parent, fixed scalar?), and CDR lives on
`container` (peer of sensordata's host-level computation context).
Status: deferred to W4b R-MULTISTAGE encoding (with explicit choice of
the CDR_max scope).

## KB 52 — Time-Weighted Quality Decay (TWQD)

Reason: TWQD = -d/dt(VVP) * (1 + beta * TBS) * (1 + gamma * (1 - TSS)).
Depends on KB #3 (VVP, deferred), needs a time derivative across
consecutive sensordata readings, and has two unspecified weights
(beta, gamma). Status: deferred — cascades from KB #3 and needs a
time-series formulation.

## KB 54 — Logistics Performance Metric (LPM)

Reason: RCP * HQI / sqrt(1 + TRS). RCP on `transportinfo`, HQI+TRS on
`sensordata`. Peer-join. Status: deferred to W4b R-MULTISTAGE
encoding.

## KB 55 — Critical Cascade Condition

Reason: predicate over MPRA, TSC, TWQD, ESF — depends on KB #50, #51,
#52 (all deferred). Status: deferred — cascades.

## KB 56 — Compound Quality Risk

Reason: "VSI decreases over three consecutive readings AND LPM < 0.5
AND ESF > 0.6". Depends on KB #39 (VSI, deferred), KB #54 (LPM,
deferred), and a 3-reading consecutive-decrease window predicate.
Status: deferred — cascades and needs a window-function formulation.

## KB 57 — Dynamic Stability Threshold

Reason: "average TSC over last 5 readings < 0.7 AND MPRA > 0.6".
Depends on KB #50 (TSC) and KB #51 (MPRA), both deferred. Also needs
a rolling 5-reading window. Status: deferred — cascades.

## KB 58 — Multi-System Failure Risk

Reason: "(CRI + TBS + (1 - HQI))/3 > 0.7 AND all of (TSC, LPM, ESF) <
0.3". Depends on KB #50 (TSC) and KB #54 (LPM), both deferred.
Status: deferred — cascades.

## KB 59 — Predictive Degradation Alert

Reason: "TWQD increases over 3 consecutive readings AND ESF > 0.5 AND
TempDevCount > 3". Depends on KB #52 (TWQD, deferred) and a 3-reading
trend window. Status: deferred — cascades from KB #52.

## KB 65 — Urgency Rank

Reason: vehicles ranked descending by `CMR + DaysOverdue/30`. Depends
on KB #32 (CMR, deferred). Status: deferred — cascades from KB #32.
Once CMR is encoded as a multistage model, this rank is a one-stage
extension.
