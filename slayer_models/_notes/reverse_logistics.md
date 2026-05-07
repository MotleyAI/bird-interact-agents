# reverse_logistics — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/reverse_logistics/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers to
distinguish "skipped on purpose" from "missed".

## KB 3 — Customer Return Frequency Index (CRFI)

Reason: CRFI = T_r / T_y (Total Returns / Customer Tenure in years).
Total Returns is encoded (`customers.total_returns`) but Customer
Tenure (KB #18) has no usable source data — the only candidate field
is `orders.txndate`, which is `None` for every row in the supplied
sqlite (1488/1488 rows). Without a real first-transaction date we
can't compute customer tenure, and therefore can't compute CRFI.

Status: deferred — blocked on the upstream data gap (KB #18). Once
real `orders.txndate` values are populated the agent can compute
`tenure_years = (current_date - min(txndate)) / 365` per customer and
divide `total_returns` by it; or we'd add an R-MULTISTAGE model that
aggregates per-customer min(txndate) and joins it back to customers.

## KB 9 — Return Channel Cost Index (RCCI)

Reason: RCCI = S_f / mean(S_f for the same Return_Channel). This is a
composite that crosses an aggregation boundary — the denominator is
an aggregate over peer rows of the same return — so it requires an
R-MULTISTAGE encoding (stage 1: `avg(shipping_fee)` grouped by
`return_channel`; stage 2: join the aggregate back to `returns` and
divide each row's `shipping_fee` by the channel mean).

Status: deferred to W4b R-MULTISTAGE encoding. An initial attempt
created `return_channel_cost_index` as a query-backed model, but
SLayer 0.4.2's multistage SQL emitter referenced the named stage-1
CTE as a bare table (`LEFT JOIN avg_fee_per_channel AS …`) without
inlining the previous stage as a subquery the way `vaccine`'s
`container_risk_rank` does. Until that emit path is fixed (or a
working stage-2 join syntax confirmed), the agent can compute RCCI
ad-hoc with a two-step query: pull `shipping_fee:avg` grouped by
`return_channel`, then divide each row's `shipping_fee` by that mean
client-side.

## KB 18 — Customer Tenure (Years)

Reason: Defined as "(current date - first recorded transaction) /
365". The only candidate source field is `orders.txndate`, but every
row in the supplied sqlite has `txndate = None` (1488/1488). With no
first-transaction date, tenure cannot be computed.

Status: not encodable from current data. Once `orders.txndate` is
populated, encode as a column on `customers` derived via the
`rl_orders` join (or as an R-MULTISTAGE model aggregating per-customer
min(txndate)).

