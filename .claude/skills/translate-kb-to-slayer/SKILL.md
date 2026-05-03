---
name: translate-kb-to-slayer
description: Enrich auto-ingested SLayer models with knowledge from a BIRD-Interact mini-interact `*_kb.jsonl` file, using the SLayer MCP server. Use after the database has been auto-ingested so models already exist; this skill edits them in place. After running, benchmark tasks reduce to short, natural SLayer queries.
---

# Translate a BIRD-Interact KB into SLayer model enrichments via MCP

## Premise

By the time this skill runs:

- The mini-interact SQLite database has been registered as a SLayer
  datasource and **auto-ingested** — `mcp__slayer__create_datasource` with
  `auto_ingest=true`, or `mcp__slayer__ingest_datasource_models`.
- One SLayer model per table already exists, with **FK joins**, **column
  types**, **PK aggregation restrictions**, and **one row-level measure per
  non-id numeric column** populated.
- **Math/stat UDFs** (`ln`, `log10`, `exp`, `sqrt`, `pow`, `power`,
  `stddev_samp`, `stddev_pop`, `var_samp`, `var_pop`, `corr`) are
  registered on every SQLite connection (DEV-1317). Use them freely in
  formulas — no rewrite to `x*x` etc. needed.

This skill **edits the existing models in place** via the SLayer MCP
server. **Do not recreate** auto-ingested models. Only **create new
models** for cases that genuinely need them — almost always multistage
(query-backed) models that materialise an aggregation-then-row computation.

## Inputs

- `mini-interact/<db>/<db>_kb.jsonl` — KB entries.
- `mini-interact/<db>/<db>_column_meaning_base.json` — column meanings
  (used to resolve prose-only formulas onto column names).
- `mini-interact/<db>/<db>_schema.txt` — schema (used only when adding
  joins the auto-ingest missed).

## MCP tools (in order of preference)

1. `mcp__slayer__models_summary(datasource_name=<db>)` — list existing
   models for the datasource.
2. `mcp__slayer__inspect_model(model_name=<m>)` — see one model's
   dimensions, measures, custom aggregations, joins, sample data.
3. **`mcp__slayer__edit_model(...)`** — primary write path. Upserts
   `dimensions`, `measures`, `aggregations`, `joins`; appends/removes
   model `filters`; updates `description`. Re-runnable safely.
4. `mcp__slayer__create_model(name=…, query=[…])` — **only** for
   query-backed (multistage) models that have no host table.
5. `mcp__slayer__query(...)` — verification step.

## Recipe selection

For each KB entry, scan `definition` and `type`; pick the *first* recipe
whose trigger matches; apply it; move on.

| Recipe | Trigger |
|---|---|
| **R-DESCRIBE** | `type` is `domain_knowledge` or `value_illustration`; or any prose-only entry. |
| **R-JOIN** | Cross-table reference whose join chain isn't reachable through auto-FK joins. |
| **R-COL** | `calculation_knowledge`, row-level arithmetic over columns of one table; no Σ/AVG-over-rows; no anchor date; no quartile. |
| **R-CASE** | Definition maps an enum / numeric band to a label or scalar. |
| **R-FILTER** | "Count of rows matching X" / "sum where X" / ratio whose numerator is a filtered count of the same table. |
| **R-MEASURE** | Named metric is a single-column aggregate (Σ, AVG, MIN, MAX, COUNT, COUNT DISTINCT) over rows of one table; not parametrized. |
| **R-AGG** | Named metric is an aggregation that needs more than one column or has tunable parameters (MKT, weighted avg with explicit weight, …). |
| **R-RESOLVE** | Definition contains "where X is the …" or any unqualified reference to another KB metric by name. |
| **R-MULTISTAGE** | Row-level expression references an aggregate of child rows; one stage of arithmetic must run after a stage of aggregation. |
| **R-WINDOW** | "Top quartile / above median / rank ≤ N / percentile ≥ p" used as a row-level dimension or filter. |
| **R-EXISTS** | "Exists ≥1 child meeting X", "all children meet X", "% of children meeting X" as a Boolean attribute on the parent. |
| **R-VAR** | Definition depends on a "report date" / "as of" / "past N months" — anything that's a query parameter, not data. |
| **R-HOST** | Boolean predicate composes facts from multiple tables; no obvious host model. |
| **R-PROSE** | `calculation_knowledge` but definition is prose, not algebra. |

## Workflow

Process the KB in this pass order so each pass uses the previous pass's
output. Skip a pass entirely when the KB has no entries of that flavour.

### Step 0 — orient

```
mcp__slayer__models_summary(datasource_name="<db>")
# for each model the KB references:
mcp__slayer__inspect_model(model_name="<m>")
```

Build a mental map: KB entry → host model.

### Pass 1 — descriptions (R-DESCRIBE)

For every `domain_knowledge` / `value_illustration` entry, attach the KB
knowledge as `description` text. `edit_model` upserts by name, so
updating a column's description doesn't disturb its SQL or type.

```
mcp__slayer__edit_model(
  model_name="<m>",
  description="…<model-level prose>…",
  dimensions=[{"name": "<existing_col>", "description": "<column-level prose>"}],
)
```

### Pass 2 — missing joins (R-JOIN)

Auto-ingest already encoded every FK as a `ModelJoin`. Add joins only
when a KB definition references a cross-table relationship the schema
doesn't have as an FK (rare in mini-interact). Confirm against
`<db>_schema.txt`.

```
mcp__slayer__edit_model(
  model_name="<host>",
  joins=[{"target_model": "<other>", "join_pairs": [["<src_col>", "<tgt_col>"]]}],
)
```

### Pass 3 — row-level enrichments (R-COL, R-CASE, R-FILTER)

**R-COL.** Trigger above. Encode as a new dimension (or upsert an
existing one) on the host model.

```
# alien#0   SNQI = SnrRatio − 0.1 × |NoiseFloorDbm|
mcp__slayer__edit_model(
  model_name="signal_observations",
  dimensions=[{
    "name": "snqi",
    "type": "number",
    "sql": "SnrRatio - 0.1 * ABS(NoiseFloorDbm)",
    "description": "Signal-to-Noise Quality Indicator (SNQI) — KB #0",
  }],
)
```

**R-CASE.** Trigger above.

```
# households#44   Brickwork=4, Apartment=3, other=1
mcp__slayer__edit_model(
  model_name="households",
  dimensions=[{
    "name": "dwelling_type_score",
    "type": "number",
    "sql": "CASE dwellingType WHEN 'Brickwork' THEN 4 WHEN 'Apartment' THEN 3 ELSE 1 END",
    "description": "Dwelling Type Score — KB #44",
  }],
)
```

**R-FILTER.** Trigger above. Encode by adding a custom Aggregation that
wraps the predicate, OR — if the metric is itself a ratio — encode the
whole ratio as a custom Aggregation that returns it directly.

```
# labor_cert#26   ECR = applications with attorney / total
mcp__slayer__edit_model(
  model_name="applications",
  aggregations=[{
    "name": "external_counsel_rate",
    "formula": "CAST(COUNT(CASE WHEN attorney_id IS NOT NULL THEN 1 END) AS REAL) / NULLIF(COUNT(*), 0)",
    "description": "External Counsel Rate (ECR) — KB #26",
  }],
)
# query: fields=[{"formula": "id:external_counsel_rate", "name": "ECR"}]
```

### Pass 4 — named aggregations (R-MEASURE, R-AGG, R-RESOLVE)

**R-MEASURE.** Trigger above. Add a custom Aggregation whose `formula`
is `<agg>({value})` with the metric's name; the agent calls
`<col>:<name>`.

```
# cold_chain#0   TED = Σ tᵢ
mcp__slayer__edit_model(
  model_name="excursion_events",
  aggregations=[{
    "name": "ted",
    "formula": "SUM({value})",
    "description": "Temperature Excursion Duration (TED) — KB #0",
  }],
)
# query: fields=[{"formula": "duration:ted", "name": "TED"}]
```

**R-AGG.** Trigger above.

```
# cold_chain#26   MKT
mcp__slayer__edit_model(
  model_name="excursion_events",
  aggregations=[{
    "name": "mkt",
    "formula": "(-{deltaH}/{R}) / ln(SUM(exp(-{deltaH}/({R} * {value}))) / COUNT(*))",
    "params": [
      {"name": "deltaH", "sql": "83144"},
      {"name": "R",      "sql": "8.314"},
    ],
    "description": "Mean Kinetic Temperature (MKT) — KB #26",
  }],
)
# query: fields=[{"formula": "temperature_kelvin:mkt", "name": "MKT"}]
```

**R-RESOLVE.** Trigger above. Apply the referenced KB entry's recipe
*first*, then reference its encoded name. Cycles are rejected by SLayer.

### Pass 5 — multistage / query-backed models (R-MULTISTAGE, R-WINDOW, R-EXISTS, R-VAR)

The only pass that uses `create_model`. Use it only when the KB formula
needs aggregation-then-row semantics — there's no host table whose
row-level columns alone can carry the expression.

**R-MULTISTAGE.**

```
# VRA = VRI × RES, where VRI is an avg over child rows
mcp__slayer__create_model(
  name="vendor_risk_amplification",
  query=[
    {
      "name": "vri_per_vendor",
      "source_model": "vendor_security_assessments",
      "fields": [{"formula": "VendSecRate:avg", "name": "vri"}],
      "dimensions": ["vendor_id"],
    },
    {
      "source_model": {
        "source_name": "vendors",
        "joins": [{"target_model": "vri_per_vendor",
                   "join_pairs": [["id", "vendor_id"]]}],
      },
      "dimensions": ["id"],
      "fields": [{"formula": "vri_per_vendor.vri:avg * RES:avg",
                  "name": "vra"}],
    },
  ],
)
```

**R-WINDOW.**

```
mcp__slayer__create_model(
  name="account_with_tei_quartile",
  query=[
    {
      "name": "tei_per_account",
      "source_model": "accounts",
      "fields": [{"formula": "tei", "name": "tei_v"}],
      "dimensions": ["id"],
    },
    {
      "source_model": {
        "source_name": "accounts",
        "joins": [{"target_model": "tei_per_account",
                   "join_pairs": [["id", "id"]]}],
        "dimensions": [{
          "name": "tei_quartile",
          "type": "number",
          "sql": "NTILE(4) OVER (ORDER BY tei_per_account.tei_v DESC)",
        }],
      },
      "dimensions": ["id", "tei_quartile"],
    },
  ],
)
```

**R-EXISTS.**

```
mcp__slayer__create_model(
  name="sites_with_high_fidelity_mesh",
  query=[
    {
      "name": "hifi_mesh_count_per_site",
      "source_model": "meshes",
      "dimensions": ["site_id"],
      "fields": [{"formula": "*:count", "name": "n_hifi"}],
      "filters": ["fidelity_score >= 0.9"],
    },
    {
      "source_model": {
        "source_name": "sites",
        "joins": [{"target_model": "hifi_mesh_count_per_site",
                   "join_pairs": [["id", "site_id"]]}],
      },
      "dimensions": ["id"],
      "filters": ["hifi_mesh_count_per_site.n_hifi >= 1"],
    },
  ],
)
```

**R-VAR.** For "rolling 30 days" against a normal model, use the
built-in window inside a plain query (`{"formula":
"revenue:sum(window='30d')"}`) — no new model. Use this recipe only
when the metric needs a parameterised anchor date.

```
mcp__slayer__create_model(
  name="active_customers_recent",
  query=[
    {
      "source_model": "orders",
      "dimensions": ["customer_id"],
      "fields": [{"formula": "*:count", "name": "order_count"}],
      "filters": [
        "created_at > date('{as_of_date}', '-6 months')",
        "created_at <= date('{as_of_date}')",
      ],
    },
  ],
)
# at query time:
# mcp__slayer__query(source_model="active_customers_recent", variables={"as_of_date": "2025-04-01"})
```

### Pass 6 — host placement (R-HOST)

Trigger above. Place the encoded column / measure on the model whose PK
matches the predicate's grain. Cross-table refs come via dotted joined
paths. Avoid coarse predicates on fine-grained models.

## Constraints & gotchas

- **Idempotency**: `edit_model` upserts each list by name. Re-running the
  skill on the same KB is safe and the recommended way to refine.
- **`create_model` collisions**: same name twice errors. Use a fresh name
  or `delete_model` first.
- **Naming**: `name` is `snake_case` ASCII (no `.`, no `__`). The KB
  display name (e.g., "Account Health Index (AHI)") goes in `description`
  / `label`.
- **Per-task ambiguity (HARD-8)**: out of scope here — the task runner
  handles `knowledge_ambiguity[*].deleted_knowledge` per task.
- **Verification**: after Pass 4 / 5, hit a few tasks for the database
  in `mini_interact.jsonl` and confirm the natural agent query is just a
  measure list + dimensions + filters — no per-task formula re-derivation.
