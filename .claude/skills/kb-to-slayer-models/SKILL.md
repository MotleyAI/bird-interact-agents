---
name: kb-to-slayer-models
description: Translate a structured knowledge base (calculation entries, descriptions, enum bands, multistage formulas) into edits on a SLayer datasource via the v0.4.0+ MCP server. A recipe book — a caller picks the recipe whose trigger matches each KB entry and applies it. Domain-agnostic; downstream wrappers add domain bookkeeping.
---

# Translate a KB into SLayer model enrichments via MCP

## Premise

By the time this skill runs:

- The target database has been registered as a SLayer datasource and
  **auto-ingested** — `mcp__slayer__create_datasource` with
  `auto_ingest=True`, or `mcp__slayer__ingest_datasource_models`.
- One SLayer model per table already exists, with **FK joins**, **column
  types**, and one **Column** per source column populated.
- **SLayer 0.4.0+ MCP** is the runtime. `edit_model` and `create_model`
  expose the v3 unified `columns` list and the v3 named-formula
  `measures` list with `formula` (not `sql`).

This skill **edits the existing models in place** via the SLayer MCP
server. **Do not recreate** auto-ingested models. Reserve `create_model`
for query-backed (multistage) models that have no host table.

This skill is **domain-agnostic**. It says nothing about JSONL files,
KB ids, notes files, or verifiers. Wrappers (e.g.
`translate-mini-interact-kb`) layer that bookkeeping on top by passing
their own `meta=…` payloads through the recipes.

## MCP tools (in order of preference)

1. `mcp__slayer__models_summary(datasource_name=<db>)` — list existing
   models for the datasource.
2. `mcp__slayer__inspect_model(model_name=<m>)` — see one model's
   columns, named-formula measures, custom aggregations, joins, sample
   data.
3. **`mcp__slayer__edit_model(...)`** — primary write path. Upserts
   `columns`, `measures` (named formulas), `aggregations`, `joins`;
   appends/removes model `filters`; updates `description`. Re-runnable
   safely (upsert by name on each list).
4. `mcp__slayer__create_model(name=…, query=[…])` — **only** for
   query-backed (multistage) models that have no host table.
5. `mcp__slayer__query(...)` — verification step at the end.

## v3 vocabulary cheat-sheet

| Concept | Where it lives | Shape |
|---|---|---|
| Row-level expression on a model (used as group-by dim or aggregation source) | `model.columns` | `{name, sql, type, primary_key, allowed_aggregations, filter, label, description, hidden, meta}` |
| Named formula on a model (a saved metric) | `model.measures` | `{name, formula, label, description, meta}` — `formula` is e.g. `"revenue:sum / *:count"` or `"duration:sum"` |
| Custom (parametrized) aggregation | `model.aggregations` | `{name, formula, params: [{name, sql}], description, meta}` — `formula` uses `{value}` and named params |
| Joined-table reference in raw SQL | inside `Column.sql` / `Column.filter` / model `filters` | `target_alias.col` (single dot) or `path__alias.col` (multi-hop) |
| Joined-table reference in queries | `dimensions` / `measures` strings | `model.col` or `model.subpath.col` (dots) |

`meta` on every entity is an open `Dict[str, Any]`. Recipes here pass
through whatever `meta` the caller supplies; the caller decides
semantics (KB ids, owner tags, source links, etc.).

## Recipe selection

For each KB entry, scan `definition` (the formula / description) and
`type`; pick the **first** recipe whose trigger matches; apply it; move
on.

| Recipe | Trigger |
|---|---|
| **R-DESCRIBE** | Prose narrative with no algebraic formula. |
| **R-JOIN** | Cross-table reference whose join chain isn't reachable through auto-FK joins (rare — check the schema first). |
| **R-COL** | Row-level arithmetic over columns of one host table; no Σ/AVG-over-rows; no anchor date; no quartile. |
| **R-CASE** | Definition maps an enum / numeric band to a label or scalar. |
| **R-FILTER** | "Count of rows matching X" / "sum where X" / a ratio whose numerator is a filtered count of the same table. |
| **R-MEASURE** | Named metric is a single-column aggregate (Σ, AVG, MIN, MAX, COUNT, COUNT DISTINCT) over rows of one table; not parametrized. |
| **R-AGG** | Named metric is an aggregation that needs more than one column or has tunable parameters (MKT, weighted_avg with a non-default weight column, trimmed_mean with bounds, …). |
| **R-RESOLVE** | Definition contains "where X is the …" or any unqualified reference to another already-encoded metric by name. |
| **R-MULTISTAGE** | A row-level expression references an aggregate of child rows; one stage of arithmetic must run after a stage of aggregation. |
| **R-WINDOW** | "Top quartile / above median / rank ≤ N / percentile ≥ p" used as a row-level dimension or filter. |
| **R-EXISTS** | "Exists ≥1 child meeting X", "all children meet X", "% of children meeting X" as a Boolean attribute on the parent. |
| **R-VAR** | Definition depends on a "report date" / "as of" / "past N months" — anything that's a query parameter, not data. |
| **R-HOST** | Boolean predicate composes facts from multiple tables; no obvious host model — pick by predicate grain. |
| **R-PROSE** | Algebraic intent expressed only in prose — resolve column refs from the surrounding column-meaning metadata, then emit via R-COL / R-MEASURE / R-AGG. |

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

For every prose-only entry, attach the text as `description`. `edit_model`
upserts by name, so updating a column's description doesn't disturb its
SQL or type.

```
mcp__slayer__edit_model(
  model_name="<m>",
  description="…<model-level prose>…",
  columns=[
    {"name": "<existing_col>",
     "description": "<column-level prose>",
     "meta": {…caller bookkeeping…}},
  ],
)
```

### Pass 2 — missing joins (R-JOIN)

Auto-ingest already encoded every FK as a `ModelJoin`. Add joins only
when a definition references a cross-table relationship the schema
doesn't have as an FK. Confirm against the schema first.

```
mcp__slayer__edit_model(
  model_name="<host>",
  joins=[{"target_model": "<other>", "join_pairs": [["<src_col>", "<tgt_col>"]]}],
)
```

### Pass 3 — row-level enrichments (R-COL, R-CASE, R-FILTER)

**R-COL.** Encode the synthetic index as a Column on the host model.

```
# Example: SNQI = SnrRatio − 0.1 × |NoiseFloorDbm|
mcp__slayer__edit_model(
  model_name="signal_observations",
  columns=[{
    "name": "snqi",
    "type": "number",
    "sql": "SnrRatio - 0.1 * ABS(NoiseFloorDbm)",
    "description": "Signal-to-Noise Quality Indicator (SNQI)",
    "meta": {…caller bookkeeping…},
  }],
)
```

**R-CASE.** Same path; `sql` carries a CASE WHEN.

```
# Example: Brickwork=4, Apartment=3, other=1
mcp__slayer__edit_model(
  model_name="households",
  columns=[{
    "name": "dwelling_type_score",
    "type": "number",
    "sql": "CASE dwellingType WHEN 'Brickwork' THEN 4 WHEN 'Apartment' THEN 3 ELSE 1 END",
    "description": "Dwelling Type Score",
    "meta": {…caller bookkeeping…},
  }],
)
```

**R-FILTER.** Use `Column.filter` directly — it wraps the column in a
`CASE WHEN` inside any aggregation at query time. Then a named formula
expresses the ratio.

```
# Example: ECR = applications with attorney / total
mcp__slayer__edit_model(
  model_name="applications",
  columns=[{
    "name": "with_attorney",
    "sql": "id",
    "type": "number",
    "filter": "attorney_id IS NOT NULL",
    "description": "Filtered count helper: rows with an attorney",
    "meta": {…caller bookkeeping…},
  }],
  measures=[{
    "name": "external_counsel_rate",
    "formula": "with_attorney:count / *:count",
    "description": "External Counsel Rate (ECR)",
    "meta": {…caller bookkeeping…},
  }],
)
# query: measures=[{"formula": "external_counsel_rate", "name": "ECR"}]
```

### Pass 4 — named aggregations (R-MEASURE, R-AGG, R-RESOLVE)

**R-MEASURE.** Save the named metric as a ModelMeasure formula. The
agent calls it by **bare name**.

```
# Example: TED = Σ tᵢ across child rows (per parent)
mcp__slayer__edit_model(
  model_name="excursion_events",
  measures=[{
    "name": "ted",
    "formula": "duration:sum",
    "description": "Temperature Excursion Duration (TED)",
    "meta": {…caller bookkeeping…},
  }],
)
# query: measures=[{"formula": "ted", "name": "TED"}]
```

**R-AGG.** Parametrized aggregation — needs more than one column or
tunable parameters.

```
# Example: MKT (uses ln/exp UDFs registered by SLayer 0.4.1+)
mcp__slayer__edit_model(
  model_name="excursion_events",
  aggregations=[{
    "name": "mkt",
    "formula": "(-{deltaH}/{R}) / ln(SUM(exp(-{deltaH}/({R} * {value}))) / COUNT(*))",
    "params": [
      {"name": "deltaH", "sql": "83144"},
      {"name": "R",      "sql": "8.314"},
    ],
    "description": "Mean Kinetic Temperature (MKT)",
    "meta": {…caller bookkeeping…},
  }],
)
# query: measures=[{"formula": "temperature_kelvin:mkt", "name": "MKT"}]
```

**R-RESOLVE.** Definition references another already-encoded metric by
name in prose ("where AHI is the Account Health Index"). Apply the
referenced entry's recipe **first** (so it has a name in the model),
then reference its bare name in the new formula. Cycles are rejected by
SLayer at save time.

### Pass 5 — multistage / query-backed models (R-MULTISTAGE, R-WINDOW, R-EXISTS, R-VAR)

The only pass that uses `create_model`. Use it only when the formula
needs aggregation-then-row semantics — there's no host table whose
row-level columns alone can carry the expression.

Each stage in the `query=[…]` list is a SlayerQuery dict. Use `measures`
(not `fields`) for the aggregated SELECTs.

`meta` on a query-backed model goes on the model itself via a separate
`edit_model(meta=…)` call after `create_model`.

**R-MULTISTAGE — composite that crosses an aggregation boundary.**

```
# Example: VRA = VRI × RES, where VRI is an avg over child rows
mcp__slayer__create_model(
  name="vendor_risk_amplification",
  query=[
    {
      "name": "vri_per_vendor",
      "source_model": "vendor_security_assessments",
      "measures": [{"formula": "VendSecRate:avg", "name": "vri"}],
      "dimensions": ["vendor_id"],
    },
    {
      "source_model": {
        "source_name": "vendors",
        "joins": [{"target_model": "vri_per_vendor",
                   "join_pairs": [["id", "vendor_id"]]}],
      },
      "dimensions": ["id"],
      "measures": [{"formula": "vri_per_vendor.vri:avg * RES:avg",
                    "name": "vra"}],
    },
  ],
)
mcp__slayer__edit_model(model_name="vendor_risk_amplification",
                        meta={…caller bookkeeping…})
```

**R-WINDOW — quartile / rank / percentile as a row predicate.**

```
mcp__slayer__create_model(
  name="account_with_tei_quartile",
  query=[
    {
      "name": "tei_per_account",
      "source_model": "accounts",
      "measures": [{"formula": "tei", "name": "tei_v"}],
      "dimensions": ["id"],
    },
    {
      "source_model": {
        "source_name": "accounts",
        "joins": [{"target_model": "tei_per_account",
                   "join_pairs": [["id", "id"]]}],
        "columns": [{
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

**R-EXISTS — ∃ child meeting predicate.**

```
mcp__slayer__create_model(
  name="sites_with_high_fidelity_mesh",
  query=[
    {
      "name": "hifi_mesh_count_per_site",
      "source_model": "meshes",
      "dimensions": ["site_id"],
      "measures": [{"formula": "*:count", "name": "n_hifi"}],
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

**R-VAR — time-anchor parameter.** For "rolling 30 days" against a
normal model, prefer the built-in window inside a plain query
(`{"formula": "revenue:sum(window='30d')"}`) — no new model needed.
Use this recipe only when the metric needs a parameterised anchor
date.

```
mcp__slayer__create_model(
  name="active_customers_recent",
  query=[
    {
      "source_model": "orders",
      "dimensions": ["customer_id"],
      "measures": [{"formula": "*:count", "name": "order_count"}],
      "filters": [
        "created_at > date('{as_of_date}', '-6 months')",
        "created_at <= date('{as_of_date}')",
      ],
    },
  ],
  variables={"as_of_date": "today"},
)
# at query time:
# mcp__slayer__query(source_model="active_customers_recent", variables={"as_of_date": "2025-04-01"})
```

### Pass 6 — host placement (R-HOST)

Place the encoded column / measure on the model whose PK matches the
predicate's grain. Cross-table refs come via dotted joined paths. Avoid
coarse predicates on fine-grained models — fan-out distorts aggregations.

## Constraints & gotchas

- **Idempotency**: `edit_model` upserts each list by name. Re-running
  the skill is safe and the recommended way to refine.
- **`create_model` collisions**: same name twice errors. Use a fresh
  name or `delete_model` first.
- **Naming**: `name` is `snake_case` ASCII (no `.`, no `__`). Display
  names go in `description` / `label`.
- **`meta` is opaque to this skill**: pass through whatever the caller
  supplies; this skill takes no position on its content.
- **Verification**: after Pass 4 / 5, hit a representative query and
  confirm the natural agent expression is short — measure list +
  dimensions + filters, no per-call formula re-derivation.
