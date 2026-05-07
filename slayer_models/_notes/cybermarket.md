# cybermarket — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/cybermarket/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers to
distinguish "skipped on purpose" from "missed".

The auto-FK joins in this DB go child → parent, with these direction-FKs:

- `buyers` → markets, vendors
- `vendors` → markets
- `products` → buyers, vendors
- `transactions` → buyers, markets, products
- `communication` → transactions, products
- `riskanalysis` → communication, transactions
- `securitymonitoring` → communication, riskanalysis
- `investigation` → riskanalysis, securitymonitoring

Composite metrics whose definition crosses an aggregation boundary
(per-market aggregations over child rows in vendors, transactions,
products, alerts; per-vendor aggregations over transactions or
markets-the-vendor-operates-on; per-buyer aggregations over
transactions; identity-matching across markets) cannot be inlined as
`Column.sql` on a single host model — they need a multistage /
query-backed model (R-MULTISTAGE). One such model is encoded
(`market_stability_index`, KB #15); the rest are queued for a W4b
refinement pass.

The cascading domain-knowledge predicates that depend on a deferred
calc are themselves deferred — fixing the calc unblocks them.

## KB 20 — High-Risk Market

Reason: predicate combines markets-local checks (MRS > 500, vendcount
> 100, dlyflow > 5000) with "at least one 'High' security alert".
The alert lives on `securitymonitoring`, which is reachable from
markets only via tx → comm → risk → secmon — a 4-hop fan-in plus an
EXISTS aggregation. Needs an R-EXISTS / R-MULTISTAGE encoding. Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 25 — Priority Investigation Target

Reason: IPS > 200 (encoded on `investigation`) AND lawinterest = 'High'
AND involves a Suspicious Transaction Pattern (KB #22, encoded on
`transactions` reachable via riskref → riskanalysis → txref) AND
connected to a High-Risk Market (KB #20, deferred). Cascades from
KB #20. Status: deferred — cascades from KB #20.

## KB 27 — Market Migration Indicator

Reason: a *temporal cross-market pattern* — multiple vendors and
buyers from one mktregistry begin appearing on a different mktregistry
within < 30 days, often after a security incident. Requires
correlating vendor/buyer identity across markets over time, plus a
30-day window anchor. The mini-interact schema has no shared
vendor/buyer identity across markets (`vendregistry` and
`buyregistry` are unique per market) and no event-time on the join.
Status: deferred — cross-market identity matching is not expressible
against the current schema.

## KB 29 — Cross-Platform Operator

Reason: identifies entities with keymatchcount > 30 (on
`communication`) operating on three or more markets simultaneously.
"Operating on N markets" needs a per-entity COUNT(DISTINCT
mktref) — but the schema has no entity identity that survives across
markets. Multi-stage aggregation plus a missing identity column.
Status: deferred — needs cross-market identity aggregation that the
schema doesn't support.

## KB 30 — Market Vulnerability Index (MVI)

Reason: MVI = (100 - MSI) + (COUNT(CASE WHEN alertsev IS NOT NULL …)
/ 10) × (alertsev_numeric × 2) - vendcount × 0.05 + (COUNT(CASE WHEN
lawinterest = 'High') / 5). Per-market metric whose terms require
aggregating alerts (from `securitymonitoring`) and law-interest
flags (from `investigation`) — both reachable from markets only via
the long tx → comm → risk → secmon / inv chain. Multi-stage
aggregation. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 31 — Vendor Network Centrality (VNC)

Reason: VNC = (COUNT(DISTINCT mktref) × 5) + vendtxcount/50 +
(VTI × 0.1) - (1 - sizecluster_numeric) × 10. The
COUNT(DISTINCT mktref) term is per *vendor identity across markets*,
but `vendors.mktref` is a single value per vendor row (vendregistry
is unique per market). Without a cross-market vendor identity column,
this can't be expressed. Status: deferred — same identity-mapping
issue as KB #27 / KB #29.

## KB 34 — Transaction Velocity Metric (TVM)

Reason: TVM = COUNT(txregistry) / (MAX(eventstamp) - MIN(eventstamp))
× payamtusd/500 × (1 + paymethod_weight × 0.1). The first factor is
an aggregation over transactions "from a single source", but the
"source" is undefined in the KB (buyer? wallet? vendor?). Mixes
aggregated terms with per-row terms; needs a multistage definition.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 35 — Market Diversification Score (MDS)

Reason: MDS = COUNT(DISTINCT prodsubcat)/5 + vendcount/50 +
COUNT(txregistry)/vendcount × 0.5 - mktclass_weight/10. Per-market
metric requiring distinct-count of `products.prodsubcat` and
`transactions.txregistry` per market. `products` reaches markets only
via `vendref → vendors → mktref` (peer-join) or via `transactions →
mktref`; needs an R-MULTISTAGE encoding that joins both children to
`markets` separately, then composes. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 38 — Cross-Platform Risk Amplification (CPRA)

Reason: CPRA = (keymatchcount × 3) + (COUNT(DISTINCT mktref) × 10) +
(WRI × 0.2) + (mktspan/365 × 5) - compliancescore/20. Same
COUNT(DISTINCT mktref) cross-market identity issue as KB #29 / KB
#31. Status: deferred — needs cross-market identity aggregation.

## KB 40 — Unstable Market

Reason: MVI > 75 AND MSI < 40 AND has 'Critical' alert. Depends on
KB #30 (MVI, deferred) and the same secmon→market fan-in. Cascades
from KB #30. Status: deferred — cascades from KB #30.

## KB 41 — Market Kingpin

Reason: VNC > 85 AND COUNT(DISTINCT mktref) >= 3 AND vendchecklvl =
'Premium' AND Trusted Vendor. Depends on KB #31 (VNC, deferred) and
the cross-market vendor identity that the schema lacks. Cascades from
KB #31. Status: deferred — cascades from KB #31.

## KB 44 — Flash Transaction Cluster

Reason: TVM > 50 AND paymethod = 'Crypto_B' AND short timeframe AND
escrowhrs < 12. Depends on KB #34 (TVM, deferred). Cascades from KB
#34. Status: deferred — cascades from KB #34.

## KB 45 — Diversified Marketplace

Reason: MDS > 65 AND COUNT(DISTINCT prodsubcat) >= 15 AND vendcount >
200 AND mktclass = 'Marketplace'. Depends on KB #35 (MDS, deferred).
Cascades from KB #35. Status: deferred — cascades from KB #35.

## KB 47 — Customer Loyalty Network

Reason: VRS > 90 AND > 5 transactions per buyer (per-vendor,
per-buyer aggregation over `transactions` joined through `products`)
AND vendrate > 4.8 AND vendchecklvl IN ('Advanced', 'Premium'). The
">5 tx per buyer" predicate is a per-(vendor, buyer) aggregation over
transactions; needs an R-MULTISTAGE encoding. Status: deferred to W4b
R-MULTISTAGE encoding.

## KB 48 — Multi-Platform Threat Entity

Reason: CPRA > 80 AND Cross-Platform Operator characteristics AND WRI
> 70 AND consistent OPSEC across platforms. Depends on KB #38 (CPRA,
deferred) and KB #29 (Cross-Platform Operator, deferred). Cascades.
Status: deferred — cascades from KB #29 / KB #38.
