# polar — KB entries not encoded as model entities

The auto-FK joins in this DB go child → equipment (each per-aspect
table joins to `equipment`). They do **not** auto-resolve peer-table
references (`thermalsolarwindandgrid` ↔ `waterandwaste` etc.) because
neither holds an FK to the other. Composite metrics that span multiple
peer tables can't be inlined as a single `Column.sql` — they need a
**multistage / query-backed model** (R-MULTISTAGE) that joins each
aspect table to `equipment` separately and then composes. That recipe
is intentionally deferred from W4a — encoded entries below cover the
single-host calc + the peer-joinable composites whose host model can
reach the other side via its own FK.

The remaining 17 KB ids in this file are deferred to the W4b refinement
pass (or to query-time multistage by the agent).

## KB 10 — Extreme Weather Readiness (EWR)

Reason: composite predicate over SSF (`weatherandstructure`) +
heaterstatus (`cabinenvironment`) + insulationstatus
(`thermalsolarwindandgrid`) + emergencylightstatus (`lightingandsafety`).
Four peer tables; needs a multistage model joining all four through
`equipment`. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 33 — Life Support System Reliability (LSSR)

Reason: 0.7 × ORS + 0.3 × TIE — ORS is on `operationmaintenance`, TIE
on `thermalsolarwindandgrid`. Peer-join via `equipment`. Status:
deferred to W4b R-MULTISTAGE.

## KB 34 — Scientific Mission Success Probability (SMSP)

Reason: SER (`scientific`) × (0.8 + 0.2 × CRI/10) (`communication`).
Peer-join. Status: deferred to W4b R-MULTISTAGE.

## KB 35 — Resource Self-Sufficiency Index (RSSI)

Reason: 0.6 × REC (`thermalsolarwindandgrid`) + 0.4 × WRMI
(`waterandwaste`). Peer-join. Status: deferred to W4b R-MULTISTAGE.

## KB 36 — Extreme Climate Adaptation Coefficient (ECAC)

Reason: SSF (`weatherandstructure`) × (1 + TIE
(`thermalsolarwindandgrid`) × 0.5) × CASE on externaltemperaturec
(`weatherandstructure`). Peer-join (weatherandstructure +
thermalsolarwindandgrid). Status: deferred to W4b R-MULTISTAGE.

## KB 38 — Energy-Water Resource Integration Index (EWRII)

Reason: 0.5 × ESI (`powerbattery`) + 0.5 × WRMI (`waterandwaste`) ×
(1 − heatertemperaturec/100) (`cabinenvironment`). Three-way
peer-join. Status: deferred to W4b R-MULTISTAGE.

## KB 39 — Comprehensive Operational Reliability Indicator (CORI)

Reason: 0.4 × EER (`equipment`) + 0.4 × ORS
(`operationmaintenance`) + 0.2 × CRI (`communication`). EER is
reachable from operationmaintenance via the existing equipment join,
but CRI requires a peer-join. Status: deferred to W4b R-MULTISTAGE.

## KB 40 — Extreme Operating Conditions (EOC)

Reason: SSF > 0.65 AND ECAC > 0.8. Depends on KB #36 (ECAC,
deferred). Status: deferred — cascades from KB #36.

## KB 41 — Emergency Response Readiness Status (ERRS)

Reason: OSPI > 0.75 AND LSSR > 0.8 AND emergencycommunicationstatus
= 'Operational' AND backuppowerstatus = 'Active'. Depends on KB #33
(LSSR, deferred) plus columns on `communication` and
`thermalsolarwindandgrid`. Status: deferred — cascades from KB #33.

## KB 42 — Sustainable Polar Operations (SPO)

Reason: RSSI > 0.7 AND EWRII > 0.65 AND wastemanagementstatus =
'Normal' AND environmentalimpactindex < 6.0. Depends on KB #35
(RSSI, deferred) and KB #38 (EWRII, deferred). Status: deferred —
cascades.

## KB 43 — Critical Scientific Equipment Status (CSES)

Reason: classification on SER (encoded) and SMSP (KB #34, deferred).
Status: deferred — cascades from KB #34.

## KB 44 — Polar Vehicle Safe Operation Conditions (PVSOC)

Reason: PTEC > 0.7 (`chassisandvehicle`) AND VPC > 0.75
(`chassisandvehicle`) AND operationalstatus = 'Active'
(`operationmaintenance`) AND safetyindex >= 0.8 (`equipment`).
Cross-table: PTEC and VPC are local to chassisandvehicle (encoded);
operationalstatus is reachable through operationmaintenance →
equipment ← chassisandvehicle, but that's a peer-join via
`equipment`. Status: deferred to W4b R-MULTISTAGE.

## KB 47 — Long-term Scientific Mission Viability (LSMV)

Reason: SMSP > 0.8 AND CORI > 0.75 AND calibrationstatus = 'Valid'
AND … Depends on KB #34 (SMSP) and KB #39 (CORI). Status: deferred
— cascades.

## KB 48 — Polar Base Energy Security Status (PBESS)

Reason: REC > 65% AND ESI > 0.7 AND RSSI > 0.75 AND
batterystatus.level_percent > 75 AND hydrogenlevelpercent > 70.
RSSI peer-join (KB #35) plus a JSON-extract on batterystatus that
lives on `powerbattery`. Status: deferred — cascades from KB #35.

## KB 49 — Comprehensive Environmental Adaptability Rating (CEAR)

Reason: depends on ECAC (KB #36, deferred) and SSF and insulationstatus.
Status: deferred — cascades from KB #36.

## KB 50 — Extreme Weather Readiness Status (EWRS)

Reason: equivalent to KB #10 (same predicate restated). Defer to
KB #10's resolution. Status: deferred — duplicate of KB #10.

## KB 51 — Life Support Reliability Classification (LSRC)

Reason: 3-tier classification over LSSR. Depends on KB #33
(deferred). Status: deferred — cascades from KB #33.
