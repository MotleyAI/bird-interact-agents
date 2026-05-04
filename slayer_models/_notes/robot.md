# robot — KB entries not encoded as model entities

Auto-FK joins in this DB are child → parent (each child table holds an
FK to `robot_details` and joins up). This means peer-table queries
(e.g. `performance_and_safety` co-grouped with `operation` by robot)
suffer the standard fan-out problem — the joined-aggregate is over
the global child rows, not the per-group ones — so any ratio whose
numerator and denominator live on **different** child tables of
`robot_details` cannot be inlined as a measure formula. Such metrics
are deferred to W4b R-MULTISTAGE encoding (a query-backed model that
aggregates each child table to per-robot grain first, then composes).

The same applies to ranking / window-function metrics (PERCENT_RANK,
DENSE_RANK + jsonb_build_object) and to "value-of-X-at-argmin-of-Y"
patterns — those need a query-backed model with explicit window or
self-join semantics.

## KB 5 — Recent Fault Prediction Score (RFPS)

Reason: faultpredscore from the maintenance record with the smallest
upkeepduedays (an arg-min lookup, not a plain aggregate). Needs a
window function (`ROW_NUMBER() OVER (PARTITION BY upkeeprobot ORDER BY
upkeepduedays ASC)`) or a self-join via `MIN(upkeepduedays)`. Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 15 — High Fault Risk

Reason: `RFPS > 0.5` predicate. Cascades from KB #5. Status:
deferred — cascades from KB #5.

## KB 31 — Energy Efficiency Ratio (EER)

Reason: `Σ energyusekwhval` (`performance_and_safety`) / TOH
(`operation`). Numerator and denominator live on peer child tables
of `robot_details`; the auto-join produces a Cartesian fan-out that
mis-scopes the per-robot aggregate. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 32 — Joint Degradation Index (JDI)

Reason: `Σ_jc Σ_i (jitemp_i / MJT_robot + jivib_i) / (|jc| · 6)`,
where MJT is the **per-robot global** max joint temperature. The
divisor is itself a per-robot aggregate, so the row-level helper can't
inline it without first materialising MJT per robot. Status: deferred
to W4b R-MULTISTAGE encoding.

## KB 37 — Tool Wear Rate (TWR)

Reason: `Σ toolwearpct` (`performance_and_safety`) / TPC
(`operation`). Same peer-join fan-out as KB #31. Status: deferred to
W4b R-MULTISTAGE encoding.

## KB 41 — Energy Inefficient Robot

Reason: `EER > 0.01 AND TOH > 1000`. Cascades from KB #31. Status:
deferred — cascades from KB #31.

## KB 42 — Joint Health Risk

Reason: `JDI > 1.5 AND MJT > 65`. Cascades from KB #32. Status:
deferred — cascades from KB #32.

## KB 47 — Tool Replacement Status

Reason: 3-tier classification over TWR, TPC, average toolwearpct.
Cascades from KB #37 (TWR). Status: deferred — cascades from KB #37.

## KB 50 — JDI-TOH Regression Slope

Reason: linear-regression slope across qualifying robots (filtered by
JDI, MJT, TOH thresholds). Requires per-robot aggregation of JDI
(KB #32, deferred) and TOH first, then a regression `Σxy − Σx·Σy/n`
formula across the filtered set. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 52 — EER Rank

Reason: `PERCENT_RANK() OVER (PARTITION BY apptypeval ORDER BY EER
DESC)`. Window function over a per-robot aggregate (EER itself
deferred). Status: deferred to W4b R-MULTISTAGE encoding.

## KB 53 — APE Rank

Reason: `PERCENT_RANK() OVER (PARTITION BY ctrltypeval ORDER BY APE
DESC)`. Window function over a per-robot aggregate. Status: deferred
to W4b R-MULTISTAGE encoding.

## KB 54 — Program Efficiency Rank

Reason: `DENSE_RANK() OVER (ORDER BY AVG(program_oce) DESC)` over
per-program aggregates of OCE per robot. Two stages of aggregation
plus a ranking window. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 55 — Efficiency Metrics

Reason: `jsonb_build_object('most_efficient_program', …,
'avg_program_efficiency', AVG(avg_program_oce))` per model series.
Combines a window ranking (KB #54) with `jsonb_build_object`
construction. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 57 — Model Average Position Error

Reason: `(Σ_R APE(R)) / |robots in M|` — average of per-robot APE
across robots in a model series. This is avg-of-aggregate, which
collapses to a different number than `avg(poserrmmval)` grouped by
modelseriesval (the latter weights by per-robot row count). Strict
KB definition needs a multistage model: aggregate APE per robot
first, then average across robots in the model series. Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 58 — Model Average TCP Speed

Reason: same shape as KB #57 — avg-of-per-robot ATCS across a model
series. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 59 — Model Average Max Operating Hours

Reason: same shape as KB #57 — avg-of-per-robot TOH across a model
series. Status: deferred to W4b R-MULTISTAGE encoding.
## KB 1 — Average Joint 1 Temperature (AJ1T)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 2 — Maximum Joint Temperature (MJT)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 3 — Average Position Error (APE)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 4 — Average TCP Speed (ATCS)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 6 — Minimum Remaining Useful Life (MRUL)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 7 — Total Operating Hours (TOH)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 8 — Number of Operations (NO)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 9 — Total Program Cycles (TPC)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 11 — High Temperature Joint 1

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 12 — Overheating Risk

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 13 — Precision Category

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 14 — Fast Robot

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 16 — Urgent Maintenance Needed

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 17 — Heavily Used Robot

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 18 — Multi-Operation Robot

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 19 — High Cycle Count Robot

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 30 — Weighted Fault Prediction Score (WFPS)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 33 — Operation Cycle Efficiency (OCE)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 35 — Maintenance Cost Trend (MCT)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 38 — Joint Torque Variance (JTV)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 39 — Payload Utilization Ratio (PUR)

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 40 — Maintenance Priority Level

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 43 — Cycle Efficiency Category

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 44 — High Safety Concern

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 45 — Escalating Maintenance Costs

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 46 — Controller Overload Risk

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 48 — Operational Instability

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 49 — Overloaded Robot

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 51 — Average Cycle Time

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

## KB 56 — Robot Count

Reason: not encoded during the W4b parallel translation pass (the
agent hit its usage limit before completing this entry).
Status: deferred to follow-up encoding pass.

