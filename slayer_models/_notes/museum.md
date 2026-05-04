# museum — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/museum/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — ...` headers
to distinguish "skipped on purpose" from "missed".

A note on dataset reality: the `artifactsecurityaccess.insvalueusd`
column has a max value of ~$997,619 in the museum dataset, so the
"InsValueUSD > $1,000,000" leg of KB #11 / #51 / #55 / `is_arv`
never matches any row. Encoded anyway because the predicate is
well-defined.

## KB 9 — Conservation Budget Efficiency (CBE)

Reason: Definition references "BudgetRatio = proportion of total
conservation budget allocated to each artifact", but no
budget-allocation column exists on any table — `budgetallocstatus` is
a categorical status (Adequate / Insufficient / Review Required), not
a numeric proportion. Status: deferred. The agent at query time can
compose a proxy ratio if a benchmark task specifies a particular
budget metric.

## KB 17 — Conservation Budget Crisis

Reason: Depends on CBE (KB #9, deferred above) plus a per-artifact
join to ConserveStatus='Critical' AND BudgetAllocStatus='Insufficient'.
Status: deferred — cascades from KB #9.

## KB 36 — Conservation Resource Allocation Efficiency (CRAE)

Reason: CRAE = CBE * (1 - CBR / 10). Depends on CBE (KB #9, deferred).
Status: deferred — cascades from KB #9.

## KB 39 — Environmental Compliance Index (ECI)

Reason: ECI = 10 - (|TempC - IdealTemp| + |RelHumidity - IdealHumidity|/5
+ ERF/2). KB defines neither IdealTemp nor IdealHumidity. KB #27
suggests ideal temperature is 18-22 deg C (a range, not a point) and
KB #28 suggests 45-55% RH (also a range). Picking a single value
inside either range would be a guess that biases the score. Status:
deferred. The agent at query time can pick midpoints (20 deg C / 50%
RH) and compute ECI directly via dimensions.

## KB 45 — Conservation Resource Crisis

Reason: CRAE < 0.3 AND Conservation Budget Crisis. Depends on KB #36
(CRAE, deferred) and KB #17 (Conservation Budget Crisis, deferred).
Status: deferred — cascades.

## KB 47 — Environmental Control Failure

Reason: ECI < 4 AND Environmental Instability Event. Depends on KB
#39 (ECI, deferred). The Environmental Instability Event leg is
encoded as `environmentalreadingscore.is_env_instability_event`, but
without ECI the composite predicate can't be expressed.
Status: deferred — cascades from KB #39.
