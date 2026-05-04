# news — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/news/`. The verifier (`scripts/verify_kb_coverage.py`)
reads the `## KB <id> — …` headers to distinguish "skipped on
purpose" from "missed".

The auto-FK joins in this DB go child → parent (devices/articles →
users; sessions → users/devices; recommendations → articles;
interactions → sessions/recommendations; interactionmetrics →
interactions; systemperformance → devices/sessions). Composite
metrics that pull columns from peer tables that don't share an FK
(e.g. `articles` + `sessions`, or `recommendations` + `sessions`)
can't be inlined as a single `Column.sql` — they need a multistage /
query-backed model (R-MULTISTAGE) that joins each peer to a common
ancestor (typically through `interactions`) then composes.

The KB also contains many domain-knowledge "criteria" entries that
prose-describe a predicate without pinning numeric thresholds (e.g.
"high engagement", "above the threshold"). Without specific
threshold values, these can't be encoded as boolean columns —
they're flagged below with `Status: deferred — undefined threshold`.

## KB 2 — Recommendation Relevance Score (RRS)

Reason: RRS = (recscore + confval + recutil) / 3. The first two are
on `recommendations`; `recutil` lives on `sessions` (it's a
session-grain column whose name suggests recommendation grain). No
FK from `recommendations` to `sessions` — the path is
recommendations ← interactions → sessions, a peer-join through
`interactions`. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 31 — Real-Time Session Efficiency (RTSE)

Reason: RTSE = CIE / SBRA. CIE is an aggregate over interaction
rows (per-session AVG of `seqval`); SBRA is a row-level expression
on `sessions`. Multistage: aggregate `news_interactions` to one CIE
per session, then divide by sessions.SBRA on the same session id.
Status: deferred to W4b R-MULTISTAGE encoding.

## KB 32 — Dynamic Content Value (DCV)

Reason: DCV = (AQI + RRS + (100 - ARS)) / 3. AQI and ARS are
article-level (encoded on `news_articles`); RRS lives at
recommendation grain. No direct FK between `news_articles` and
`news_recommendations` for an article — recommendations.artlink
points the other way (recommendations → articles). The ARS-vs-RRS
grain mismatch (one article can have many recommendations) is what
forces the multistage. Cascades on KB #2 (RRS deferred). Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 33 — Optimized Recommendation Score (ORS)

Reason: ORS = RRS × SPI / k. RRS on recommendations (deferred), SPI
on `news_systemperformance`, peer-join via `news_sessions`. The
normalisation constant `k` is also unspecified. Status: deferred to
W4b R-MULTISTAGE encoding.

## KB 34 — Adjusted Read Time Estimator (ARTE)

Reason: ARTE = readsec × ARS / UER. readsec and ARS are
article-level; UER is session-level. Cross-table peer-join via
`news_interactions`. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 35 — Personalization Accuracy Metric (PAM)

Reason: PAM = (RRS + PP) / 2. PP (KB #11) is a prose-only
domain-knowledge criterion with no numeric definition; RRS is
deferred (KB #2). Status: deferred — depends on KB #2 (deferred)
and KB #11 (prose-only).

## KB 36 — Conversion Impact Factor (CIF)

Reason: CIF = UER / ITI. ITI (KB #19) is a prose-only "promptness"
indicator with no concrete column. Status: deferred — depends on
KB #19 (prose-only, no numeric definition).

## KB 37 — Adjusted Bounce Ratio (ABR)

Reason: ABR = SBRA × (RTSE factor). The "RTSE factor" is itself
not defined precisely (the KB hand-waves it). RTSE itself is
deferred (KB #31). Status: deferred — cascades from KB #31.

## KB 38 — Composite System Stability (CSS)

Reason: CSS = sqrt(SPI × DPM). DPM (Device Performance Metric) is
not defined anywhere in the KB or schema. Status: deferred — DPM
undefined.

## KB 39 — Interactive Content Amplifier (ICA)

Reason: ICA = CIE + α × RRS. α is an unspecified weight; RRS is
deferred (KB #2). Status: deferred — cascades from KB #2; α
undefined.

## KB 40 — High Engagement Indicator (HEI)

Reason: predicate over UER and CIE thresholds, neither pinned by
the KB ("above the threshold", "high"). Status: deferred —
undefined threshold.

## KB 41 — Premium Article Distinction (PAD)

Reason: predicate over AQI threshold (unspecified) and KB #10 PCR
(prose-only). Status: deferred — undefined threshold; depends on
KB #10 prose-only criterion.

## KB 42 — Targeted Personalization Benchmark (TPB)

Reason: predicate over KB #11 PP (prose-only) and PAM (KB #35,
deferred). Status: deferred — cascades from KB #11 and KB #35.

## KB 43 — User Churn Predictor (UCP)

Reason: combines KB #13 ECP (prose-only "consistent engagement")
and KB #18 SSAD (prose-only "unusually short", no quantified
threshold). Status: deferred — depends on prose-only criteria with
no concrete numeric definitions.

## KB 44 — Content Virality Threshold (CVT)

Reason: thresholds on DCV (KB #32, deferred) and ICA (KB #39,
deferred), neither pinned. Status: deferred — cascades from KB #32
and KB #39.

## KB 45 — System Resilience Factor (SRF)

Reason: predicate over CSS (KB #38, deferred — DPM undefined) and
SPI (encoded). Threshold for "strong performance" not specified.
Status: deferred — cascades from KB #38; undefined threshold.

## KB 46 — Session Drop-off Risk (SDR)

Reason: predicate over RTSE (KB #31, deferred) and ABR (KB #37,
deferred). Status: deferred — cascades.

## KB 47 — Conversion Potential Indicator (CPI)

Reason: predicate over CIF (KB #36, deferred) and ICA (KB #39,
deferred). Status: deferred — cascades.

## KB 48 — Content Consumption Consistency (CCC)

Reason: predicate over ARS, UER (encoded) and KB #11 PP
(prose-only); the "steady patterns" rule has no numeric
formulation. Status: deferred — depends on prose-only KB #11;
undefined "steady" threshold.

## KB 49 — Subscription Valuation Rule (SVR)

Reason: prose-only "comprehensive user valuation" — combines USV
(KB #17, encoded) with engagement and demographic factors but with
no specific weighting or threshold. Agent can compose at query
time using `news_users.user_subscription_value`,
`news_users.user_demographic_score` and the desired session-level
engagement metrics. Status: deferred — undefined weights.

# Implementation notes (not deferred KB ids)

## Encoded but value range is suspect: KB #5 ARS / KB #57 Readability Segmentation

KB #5 defines ARS = readsec × log(wordlen) / w, with w from KB #56
(Basic=1, Intermediate=1.5, Advanced=2, others=1.2). KB #57 then
buckets ARS into Low (<50), Medium (50–100), High (>100).

With this DB's data — readsec in [25, 1200] and wordlen in [104,
5000] — both interpretations of "log" produce ARS values far above
100 for the vast majority of articles:

- log10: ARS ranges roughly 25 .. 6500, median ~600.
- ln (natural): ARS ranges roughly 60 .. 15000.

Either way, almost every article ends up in the "High" bucket and
the Low/Medium thresholds rarely fire. The encoding uses `log10`
(SLayer's registered SQLite UDF) and matches the KB's algebra; the
thresholds in KB #57 simply don't fit the actual data ranges. This
is encoded but the agent should treat the segmentation labels with
caution. Status: encoded (KB #5 on
`news_articles.article_readability_score`, KB #57 on
`news_articles.readability_segment`); value range suspect; threshold
not adjusted because KB #57 pins the numeric cuts.

## Naming convention: `news_<table>` prefix on every model

Every news model is named `news_<table>` (e.g. `news_users`,
`news_articles`) rather than the bare table name. This is because
the SLayer storage layer keys models by name only, and several other
mini-interact DBs (crypto, virtual, hulushows, …) ingest tables
called `users`, `interactions`, `articles`, etc. into the same
storage. Using bare table names caused parallel-agent overwrites of
my `users` model with crypto's data; using a `news_` prefix ensures
news's models don't collide with anyone else's.

## Real bug found in SLayer MCP: measure `meta` not persisted

`mcp__slayer__edit_model` and `mcp__slayer__create_model` accept
`meta` on `measures` entries and report success, but the field is
never written to YAML storage. Verified by inspecting
`~/.local/share/slayer/models/news_users.yaml` after a clean
`create_model` call that included `measures=[{name, formula,
description, meta: {kb_id: 55}}]`: every other field landed,
`meta` did not.

Workaround used here: stamp the KB id on a row-level Column instead
of the ModelMeasure (the verifier walks both). KB #9 CIE → kb_id
on `news_interactions.seqval`; KB #55 cohort_percentage → kb_id on
`news_users.testgrp`. The semantics is slightly off (KB describes a
measure, not a column) but verifier coverage is satisfied. Worth
filing upstream — this would silently drop bookkeeping on every
saved measure.

