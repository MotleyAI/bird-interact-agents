# crypto — KB entries not encoded as model entities

The crypto schema spreads the data the KB cares about across many tables
that aren't directly joinable: `orders` carries the order ticket,
`riskandmargin` carries the per-order JSON-blob position/leverage
profile, `accountbalances` carries per-user wallet/PnL, while
`marketdata` / `marketstats` / `analyticsindicators` /
`systemmonitoring` carry per-(exchange × market) snapshots that the
schema never links to specific orders by FK.

Auto-FK ingestion gives us:

- `riskandmargin → orders`
- `orderexecutions → orders`
- `fees → orders`
- `accountbalances → users`
- `orders → users`
- `analyticsindicators → marketdata`, `analyticsindicators → marketstats`
- `marketstats → marketdata`
- `systemmonitoring → analyticsindicators`

What is **not** linked: `orders ↔ marketdata/marketstats` (no FK from
`orders.mktnote` to a market record), `accountbalances ↔ riskandmargin`
(per-user vs per-order, no shared key), and `systemmonitoring ↔ orders`
(slipratio/mkteffect are global gauges, not per-order). Many KB
formulas insist on combining facts from these unlinked sources;
those entries are deferred to W4b R-MULTISTAGE encoding (or to
agent-driven query-time joins).

## KB 1 — Slippage Impact

Reason: dealcount / (bidunits or askunits) × spreadband. dealcount is
on `orders`; bidunits/askunits/spreadband are JSON fields of
`marketdata.quote_depth_snapshot`. There is no FK between `orders`
and `marketdata`, and `orders.mktnote` (e.g. "BTC-USDT") is not a
key into `marketdata` either. Status: deferred to W4b R-MULTISTAGE
encoding.

## KB 2 — Position Value at Risk (PVaR)

Reason: possum (riskandmargin JSON) × volmeter (marketstats) × 0.01.
`riskandmargin → orders` exists, but `orders ↔ marketstats` has no FK,
so the chain doesn't close. Status: deferred to W4b R-MULTISTAGE
encoding.

## KB 4 — Market Impact Cost (MIC)

Reason: dealcount × dealquote × mkteffect × 0.01. dealcount/dealquote
are on `orders`; mkteffect is on `systemmonitoring`. systemmonitoring
joins to analyticsindicators, not to orders. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 6 — Realized Risk Ratio (RRR)

Reason: realline / PVaR. realline is on `accountbalances` (per-user);
PVaR per KB #2 (deferred) needs a per-order grain. Cross-grain plus
deferred dependency. Status: deferred — cascades from KB #2.

## KB 7 — Margin Utilization

Reason: inithold (riskandmargin JSON, per-order) / margsum
(accountbalances, per-user) × 100. Cross-grain — per-order numerator
vs per-account denominator with no aggregation rule provided in the
KB. Status: deferred to W4b R-MULTISTAGE encoding (likely as
`SUM(inithold) over user / margsum` once the grain is fixed).

## KB 9 — Market Efficiency Ratio (MER)

Reason: Slippage Impact / slipratio. Slippage Impact (KB #1) is
deferred for cross-table reasons; slipratio is on `systemmonitoring`
(global gauge), not joinable to a specific order. Status: deferred —
cascades from KB #1.

## KB 10 — Whale Order

Reason: dealcount > 10% × (bidunits or askunits at best bid/ask).
dealcount on `orders`; bidunits/askunits in `marketdata` JSON. Same
unlinked pair as KB #1. Status: deferred to W4b R-MULTISTAGE
encoding.

## KB 11 — Liquidation Risk Level

Reason: categorise positions vs liqquote (riskandmargin JSON) using
"current market price". Current price would be `marketdata.midquote`
or `marketdata.markquote` for the position's market — but
riskandmargin → orders → mktnote is not a FK to marketdata. Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 13 — Over-Leveraged Position

Reason: posmagn (riskandmargin JSON) × volmeter (marketstats) > 500.
Same unlinked pair as KB #2 (per-order × per-market with no FK).
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 14 — Market Maker Activity

Reason: exectune (orderexecutions, per-fill) predominantly 'Maker'
AND makermotion (analyticsindicators, per-snapshot) = 'High'.
orderexecutions has no FK to analyticsindicators. Status: deferred
to W4b R-MULTISTAGE encoding.

## KB 17 — Momentum Divergence

Reason: "price makes new highs/lows while momentum indicators
(buyforce, sellforce) move in the opposite direction". No anchor for
"new highs/lows" (no per-market time series with prior-period
references) and direction comparison is undefined for a single row.
Status: deferred — needs an explicit time/window encoding the KB
does not specify.

## KB 18 — Margin Call Risk

Reason: Margin Utilization > 80%. Margin Utilization is KB #7
(deferred). Status: deferred — cascades from KB #7.

## KB 19 — Technical Breakout

Reason: price > highspotday OR price < lowspotday with volday at
least 50% above the **30-day average** volume. Needs a 30-day
rolling/historical aggregation; the per-row marketstats snapshot
holds only one day. Status: deferred — needs a temporal R-VAR
encoding the KB doesn't fully specify.

## KB 30 — Risk-Adjusted Return

Reason: realline / (PVaR × posriskrate). Depends on KB #2 (PVaR,
deferred) and crosses accountbalances ↔ riskandmargin which share no
FK. Status: deferred — cascades from KB #2.

## KB 31 — True Cost of Execution

Reason: feetotal + (dealcount × dealquote × Slippage Impact × 0.01).
Depends on KB #1 (Slippage Impact, deferred). Status: deferred —
cascades from KB #1.

## KB 33 — Effective Leverage

Reason: posmagn × possum / walletsum. posmagn/possum on
`riskandmargin` (per-order); walletsum on `accountbalances`
(per-user). The two tables share no FK and the KB doesn't say how to
aggregate per-order positions against the single per-user wallet
balance. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 35 — Arbitrage ROI

Reason: AOS × dealquote / (feetotal × 2). AOS is on
`analyticsindicators`, dealquote on `orders`, feetotal on `fees`.
fees → orders is FK; orders ↔ analyticsindicators is not. Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 36 — Market Depth Ratio

Reason: (biddepth or askdepth) / dealcount × Liquidity Ratio.
biddepth/askdepth in `marketdata` JSON, dealcount in `orders` —
unlinked pair. Plus posedge gating (Long → biddepth, Short → askdepth)
that crosses to `riskandmargin`. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 40 — Critically Over-Leveraged Position

Reason: Over-Leveraged AND Effective Leverage > 20 AND Margin
Utilization > 90%. All three components (KB #13, #33, #18) are
deferred. Status: deferred — cascades from KB #13 / #33 / #18.

## KB 41 — High-Quality Arbitrage Opportunity

Reason: Arbitrage Window AND Arbitrage ROI > 0.5% AND MER < 1.2.
Depends on KB #35 (deferred) and KB #9 (deferred). Status: deferred
— cascades from KB #35 / #9.

## KB 42 — Technical Reversal Signal

Reason: |Technical Signal Strength| > 8 AND Momentum Divergence.
Depends on KB #17 (Momentum Divergence, deferred). Technical Signal
Strength is encoded; the conjunction can't be expressed without #17.
Status: deferred — cascades from KB #17.

## KB 43 — Liquidity Constrained Position

Reason: Market Depth Ratio < 2.0. Depends on KB #36 (deferred).
Status: deferred — cascades from KB #36.

## KB 44 — Optimal Trading Window

Reason: Volatility-Adjusted Spread < 1.0 AND Market Maker Activity
indicates 'High'. VAS is on `marketstats` (encoded), Market Maker
Activity per KB #14 (deferred — exectune × makermotion across
unlinked tables). Even ignoring exectune, makermotion is on
`analyticsindicators`, which joins to marketstats; so a
makermotion-only proxy could be encoded but it would not match the
KB's full definition. Status: deferred — cascades from KB #14.

## KB 45 — Risk-Efficient Position

Reason: Risk-Adjusted Return > 1.5 AND Risk-to-Reward Ratio < 0.5.
RAR per KB #30 (deferred). Status: deferred — cascades from KB #30.

## KB 46 — Whale-Driven Market

Reason: whalemotion = 'High' AND ∃ Whale Order in same direction as
Smart Money Flow. Whale Order per KB #10 (deferred), and the
"same-direction" join across unlinked orders ↔ analyticsindicators.
Status: deferred — cascades from KB #10.

## KB 47 — Liquidation Cascade Risk

Reason: > 15% of open positions classified as Liquidation Risk Level
'High Risk' AND |Order Book Imbalance Ratio| > 0.3. The first
predicate is a population statistic over `riskandmargin` (Liquidation
Risk Level per KB #11, deferred). Order Book Imbalance Ratio is
encoded on `marketdata`. Status: deferred — cascades from KB #11
and needs an aggregation-vs-row comparison (R-MULTISTAGE).

## KB 48 — Perfect Technical Setup

Reason: Technical Signal Strength > 7 AND techmeter ↔ mktfeel
direction matches AND no Momentum Divergence. Depends on KB #17
(deferred). Status: deferred — cascades from KB #17.

## KB 49 — Flash Crash Vulnerability

Reason: Liquidation Cascade Risk AND > 30% of positions
Over-Leveraged AND Liquidity Crisis developing. Depends on KB #47,
#13 (both deferred). Status: deferred — cascades.

## KB 51 — Smart Money Accuracy

Reason: proportion of times Smart Money Flow direction matches
4-hour-forward price movement. Requires `next_price_4h` and
`mid_price` over a future window — neither column exists in the
schema, and the KB definition uses a self-COUNT-CASE pattern that
needs a time-shifted self-join SLayer doesn't provide here. Status:
deferred — needs an R-VAR / temporal encoding the schema doesn't
support.

## KB 52 — Effective Leverage Risk Classification

Reason: 'High Risk' if Effective Leverage > 20 else 'Normal'.
Effective Leverage per KB #33 (deferred). Status: deferred —
cascades from KB #33.
