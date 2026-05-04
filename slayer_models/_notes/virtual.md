# virtual — KB entries not encoded as model entities

KB ids in the headers below are deliberately omitted from
`slayer_models/virtual/`. The verifier
(`scripts/verify_kb_coverage.py`) reads the `## KB <id> — …` headers to
distinguish "skipped on purpose" from "missed".

The auto-FK joins in this DB go child → parent, with these direction-FKs:

- `additionalnotes` → retentionandinfluence
- `commerceandcollection` → membershipandspending, engagement
- `engagement` → membershipandspending, interactions
- `eventsandclub` → socialcommunity, membershipandspending
- `loyaltyandachievements` → eventsandclub, engagement
- `membershipandspending` → fans
- `moderationandcompliance` → interactions, socialcommunity
- `preferencesandsettings` → membershipandspending, socialcommunity
- `retentionandinfluence` → engagement, loyaltyandachievements
- `socialcommunity` → engagement, commerceandcollection
- `supportandfeedback` → interactions, preferencesandsettings

Most calculated metrics live on `engagement` (the natural per-fan host
since it's 1:1 with fans via membership and reaches both
`socialcommunity` (via socialengagepivot reverse) and
`retentionandinfluence` directly). Domain-knowledge predicates are
encoded as boolean helper columns on the same model.

Composite predicates that require cross-fan aggregation or per-(fan,
idol) cardinality tests are deferred to W4b R-MULTISTAGE encoding.

## KB 29 — Multi-Idol Supporter

Reason: predicate is "interacted with at least 2 different
`interactidolpivot` values, with engrate > 0.4 for each idol".
Requires a per-(fan, idol) aggregation over `interactions` joined with
the per-fan `engagement.engrate` followed by a per-fan COUNT(DISTINCT
interactidolpivot) HAVING >= 2. Two-stage aggregation across the
fan↔idol pivot. Cannot be expressed as a single `Column.sql` on any
host model. Status: deferred to W4b R-MULTISTAGE encoding.

## KB 43 — Quality Inconsistent Creator

Reason: predicate is "has at least one content piece with
contqualrate > 8.5 BUT overall CQC < 5". The schema stores a single
aggregate `contqualrate` per fan in
`socialcommunity.community_engagement.content_creation.contqualrate`
— there is no per-content-piece grain table. The "at least one
piece" predicate cannot be expressed against the available schema.
Status: deferred — schema lacks per-content-piece grain that the KB
predicate requires.

