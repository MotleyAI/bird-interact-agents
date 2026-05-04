# fake — KB entries not encoded as model entities

The `fake` DB is a synthetic social-network moderation schema with a
single linear FK chain (`account → profile → sessionbehavior →
{contentbehavior, networkmetrics} → messaginganalysis → technicalinfo
→ securitydetection → moderationaction`). Auto-FK joins go child →
parent only. `moderationaction` is the deepest descendant table and
hosts most KB composite metrics because it can reach every other
table through dotted joined paths.

A few KB rules use **scales the data does not match** (e.g. KB #21
documents `coordscore` in [0,1] but the column is on a 0-100 scale;
similarly `trustval`, `botlikscore`, `netinflscore`). The encoded
formulas faithfully match the KB definitions; downstream queries will
produce values whose scale reflects the raw column ranges, not the
KB-described [0,1]. This is a data/KB mismatch, not an encoding bug —
flagged here so it isn't mistaken for either.

KB ids in the headers below are deliberately omitted from
`slayer_models/fake/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers
to distinguish "skipped on purpose" from "missed".

## KB 11 — Bot Network

Reason: defined as a *cluster* where `clustsize > 10` AND average BBI
> 0.7 *for all accounts in cluster*. Cluster grain ≠ moderationaction
row grain; this is a cluster-level aggregate predicate. Status:
deferred to W4b R-MULTISTAGE encoding (group by cluster identifier
`platident`, compute avg BBI, then filter).

## KB 12 — Trusted Account

Reason: PCI > 0.8 AND **no** security detections in the past 180
days. The negation across child rows is an R-EXISTS-in-reverse
predicate over a date-windowed set of `securitydetection` rows.
Status: deferred to W4b R-MULTISTAGE encoding (NOT EXISTS query
joined back to account).

## KB 40 — High-Risk Bot Network

Reason: a Bot Network (KB #11, deferred) with CBR > 0.8 AND SRS > 0.7.
Status: deferred — cascades from KB #11.

## KB 43 — Network Security Threat

Reason: NTS < 0.3 AND part of a Bot Network (KB #11, deferred).
Status: deferred — cascades from KB #11.

## KB 44 — Content Manipulation Ring

Reason: a Sockpuppet Network (KB #14, encoded per-row) where **all**
accounts have CMS > 0.7. The "all members" universal-quantifier is a
cluster-level predicate. Status: deferred to W4b R-MULTISTAGE.

## KB 45 — Automated Spam Network

Reason: a Bot Network (deferred) where avg ABS > 0.8 AND **all**
accounts are Content Farms. Cluster-level + universal. Status:
deferred — cascades from KB #11.

## KB 46 — Cross-Platform Threat

Reason: a High-Risk Account with CPRI > 0.9 AND part of a Sockpuppet
Network (cluster-level membership). Status: deferred to W4b
R-MULTISTAGE.

## KB 47 — Behavioral Anomaly Cluster

Reason: cluster where avg BAS > 0.8 AND contains ≥1 Bot Network.
Cluster-level. Status: deferred to W4b R-MULTISTAGE.

## KB 48 — Mass Manipulation Campaign

Reason: a Content Manipulation Ring (KB #44, deferred) where CIS >
0.8 for all accounts. Cluster-level + universal. Status: deferred —
cascades from KB #44.

## KB 49 — Advanced Persistent Threat

Reason: a High-Risk Bot Network (KB #40, deferred) with NMI > 0.9 AND
TEI > 0.8. Status: deferred — cascades from KB #40.

## KB 50 — Temporal Pattern Deviation Score (TPDS)

Reason: chi-square sum over 24 hourly buckets of
`(obsfreq_i - expfreq_i)^2 / expfreq_i^2`. The schema does not carry
per-hour observed/expected frequency columns; `acttimedist` is a JSON
column whose structure varies. Status: deferred to W4b R-MULTISTAGE
encoding (would require parsing acttimedist hour-by-hour and a
declared baseline).

## KB 52 — Multi-Account Correlation Index (MACI)

Reason: average of pairwise `corr(i, j)` across linked accounts.
Pairwise correlations across n accounts cannot be expressed as a
single-stage SQL formula — needs a self-join over linked-account
pairs. Status: deferred to W4b R-MULTISTAGE.

## KB 53 — Reputation Volatility Index (RVI)

Reason: σ(reputscore)/μ(reputscore) × (1 + |Δreputscore|/Δt) over a
time series of reputscore values. Each account has only a single
moderationaction row in this dataset, so the time-series component
isn't expressible without a longitudinal table. Status: deferred to
W4b R-MULTISTAGE (time-bucketed STDDEV/MEAN + |last - first| / span).

## KB 54 — Content Distribution Pattern Score (CDPS)

Reason: 0.4*entropy(posttimes) + 0.3*burstiness + 0.3*(1-periodicity).
The schema has `postnum`/`postfreq`/`postintvar`, but no per-post
timestamp series and no `burstiness` or `periodicity` field. Status:
deferred — required input columns are not present in the schema.

## KB 55 — Behavioral Consistency Score (BCS)

Reason: (1-TPDS) × (1-RVI) × (1-patterndev/100). Depends on KB #50
(TPDS, deferred) and KB #53 (RVI, deferred); `patterndev` is also
absent from the schema. Status: deferred — cascades from KB #50/#53.

## KB 56 — Network Synchronization Index (NSI)

Reason: (Σ pairwise sync(i,j)) / clustsize × MACI. Pairwise sync
across cluster members + MACI (KB #52, deferred). Status: deferred to
W4b R-MULTISTAGE.

## KB 58 — Authentication Pattern Score (APS)

Reason: (1-TEI) × BCS × (1-authanom/100). Depends on KB #55 (BCS,
deferred); `authanom` is also absent from the schema. Status:
deferred — cascades from KB #55.

## KB 59 — Cross-Platform Correlation Score (CPCS)

Reason: CPRI × MACI × (1 + platformlinks/10). Depends on KB #52
(MACI, deferred); `platformlinks` is also absent from the schema.
Status: deferred — cascades from KB #52.

## KB 60 — Coordinated Influence Operation

Reason: NSI > 0.8 AND CAE > 0.7 AND ≥1 Content Manipulation Ring
inside the network. Depends on KB #56 (NSI, deferred) and KB #44
(deferred). Status: deferred — cascades.

## KB 61 — Behavioral Pattern Anomaly

Reason: BCS < 0.3 AND TPDS > 0.7 AND not a Trusted Account.
Depends on KB #55 (BCS, deferred), KB #50 (TPDS, deferred), and
KB #12 (Trusted, deferred). Status: deferred — cascades.

## KB 62 — Cross-Platform Bot Network

Reason: a Bot Network (KB #11, deferred) where CPCS > 0.8 AND
all accounts have similar MACI patterns. Status: deferred — cascades
from KB #11/#52/#59.

## KB 63 — Authentication Anomaly Cluster

Reason: cluster where avg APS < 0.3 AND ≥1 Authentication Risk
Account. Cluster-level + cascades from KB #58. Status: deferred to
W4b R-MULTISTAGE.

## KB 64 — Network Influence Hub

Reason: NIC > 0.8 AND CAE > 0.7 AND part of a Coordinated Influence
Operation (KB #60, deferred). Status: deferred — cascades from KB
#60.

## KB 65 — Reputation Manipulation Ring

Reason: a Content Manipulation Ring (KB #44, deferred) where all
accounts have RVI > 0.7 AND similar CDPS patterns. Status: deferred —
cascades from KB #44/#53/#54.

## KB 66 — Synchronized Behavior Cluster

Reason: cluster where NSI > 0.9 AND all accounts have similar BCS
patterns. Cluster-level. Depends on KB #56 (NSI, deferred) and KB
#55 (BCS, deferred). Status: deferred — cascades.

## KB 67 — Multi-Platform Threat Network

Reason: a Cross-Platform Threat (KB #46, deferred) where CPCS > 0.8
AND all accounts are part of a Synchronized Behavior Cluster (KB #66,
deferred). Status: deferred — cascades.

## KB 68 — Advanced Influence Campaign

Reason: a Mass Manipulation Campaign (KB #48, deferred) containing ≥1
Network Influence Hub (KB #64, deferred) and high NSI (KB #56,
deferred). Status: deferred — cascades.

## KB 69 — Persistent Pattern Anomaly

Reason: a Behavioral Pattern Anomaly (KB #61, deferred) that persists
for over 30 days. Persistence-over-time predicate; no longitudinal
account-state table in this schema. Status: deferred — cascades from
KB #61.

## KB 70 — TEI quartile

Reason: NTILE(4) OVER (ORDER BY TEI). A window-function-based
row-level dimension. Status: deferred to W4b R-MULTISTAGE (a
query-backed model that joins TEI back to its row + a quartile
window).

## KB 71 — Latest Bot Likelihood Score (LBS)

Reason: `botlikscore(argmax_t detecttime)` per account. Argmax over a
time-ordered child set is a window-function pattern (FIRST_VALUE OVER
… ORDER BY detecttime DESC). Status: deferred to W4b R-MULTISTAGE.

## KB 78 — Influence ranking by NIC

Reason: `rank_i = |{j : NIC_j > NIC_i}| + 1`. RANK / DENSE_RANK over
NIC ordered desc. Window-function, account-grain. Status: deferred to
W4b R-MULTISTAGE.

## KB 79 — TEI Risk Category

Reason: 'Low Risk'/'Moderate Risk'/'High Risk'/'Very High Risk' based
on the account's TEI Quartile (KB #70, deferred). Status: deferred —
cascades from KB #70.

## KB 85 — review priority

Reason: KB describes a field on the `account` table set to a sentinel
like `'Review_Inactive_Trusted'`, but no such column exists in the
`account` schema (`accindex`, `acctident`, `platident`, `plattype`,
`acctcreatedate`, `acctagespan`, `acctstatus`, `acctcategory`,
`authstatus`). Status: not encodable from current data — the field
the KB references is absent.

## KB 86 — Account Inactivity

Reason: `last_activity_proxy_time` (KB #84, encoded as a measure on
`securitydetection`) `< CURRENT_DATE - 90 days`. The condition is a
filter on the *aggregated* per-account max(detecttime); a row-level
column on `account` would need an account-grain multistage join.
Status: deferred to W4b R-MULTISTAGE encoding.
