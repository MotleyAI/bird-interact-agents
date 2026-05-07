---
name: translate-mini-interact-kb
description: Translate one BIRD-Interact mini-interact database's `*_kb.jsonl` knowledge base into SLayer model enrichments via the SLayer MCP, then export the result to YAML at `bird-interact-agents/slayer_models/<db>/`. Wraps the domain-agnostic `kb-to-slayer-models` skill with mini-interact-specific bookkeeping (KB ids, per-DB notes file, verifier gate).
---

# Translate one mini-interact KB into a SLayer model directory

This skill orchestrates translation of a single BIRD-Interact
mini-interact database's KB into SLayer models. The actual recipes for
encoding KB entries live in the **`kb-to-slayer-models` skill** —
defer to it for any "how do I encode this entry" question. This file
covers only the mini-interact-specific bookkeeping wrapped around the
generic recipes.

## When to use

Apply once per mini-interact database, after auto-ingesting it through
the SLayer MCP. The user typically invokes by naming the DB
("translate the credit DB", "run on households", etc.).

## Inputs (per DB)

- `mini-interact/<db>/<db>_kb.jsonl` — KB entries (id, knowledge,
  description, definition, type, children_knowledge).
- `mini-interact/<db>/<db>_column_meaning_base.json` — column meanings;
  use to resolve prose-only formulas onto column names.
- `mini-interact/<db>/<db>_schema.txt` — schema; use only when the KB
  references a cross-table relationship that auto-FK ingestion may have
  missed (rare).

## Outputs (per DB)

- `bird-interact-agents/slayer_models/<db>/*.yaml` — exported SLayer
  models for the DB.
- `bird-interact-agents/slayer_models/_notes/<db>.md` — per-DB problems
  file. One Markdown section per KB entry left unencoded; section
  header format is **load-bearing** (the verifier parses it):

  ```
  ## KB <id> — <KB.knowledge>

  Reason: <why this entry isn't encoded — "ambiguous prose", "needs
  a join not present in the schema", "blocked on …", etc.>

  Status: <"deferred", "won't fix", "encoded after follow-up", etc.>
  ```

  Multiple sections in one file. The body of each section is free-form
  Markdown; only the header is parsed.

## The mandatory `meta.kb_id` / `meta.kb_ids` annotation

When invoking any recipe from `kb-to-slayer-models` to encode a KB
entry, **always pass `meta={"kb_id": <id>}`** where `<id>` is the
source entry's numeric id from `<db>_kb.jsonl`.

If a single entity covers **multiple KB entries** (a common case: one
JSON column whose description aggregates several `value_illustration`
entries about distinct sub-fields), pass `meta={"kb_ids": [<id1>,
<id2>, …]}` instead. The verifier accepts either form and unions
them.

This is non-optional:

- The W1c verifier matches encoded entities to KB ids by walking
  `meta.kb_id` across every column / measure / aggregation / model.
  Missing → false-negative "unaccounted KB id".
- The W5 HARD-8 preprocessor drops entities whose `kb_id` is in the
  task's `deleted_knowledge` list. Missing → entity stays visible to
  the agent in tasks where it should be hidden.

For query-backed models (R-MULTISTAGE / R-WINDOW / R-EXISTS / R-VAR),
attach `meta={"kb_id": <id>}` on the *model* itself via a follow-up
`mcp__slayer__edit_model(model_name=…, meta={"kb_id": <id>})` call,
since `create_model(query=…)` doesn't expose `meta` directly.

When one KB entry produces multiple entities (a Column + a
ModelMeasure for an R-FILTER ratio, say), every one of them carries
the same `kb_id`. The verifier deduplicates.

## Workflow

### 1. Read the inputs

Load `<db>_kb.jsonl`, `<db>_column_meaning_base.json`, and
`<db>_schema.txt`. Build a working list of KB entries to process.

### 2. Encode each entry

Invoke `kb-to-slayer-models` recipes per entry. Pick the recipe whose
trigger matches the entry's `definition` and `type`. Pass
`meta={"kb_id": <id>}` on every entity created. Follow the 6-pass
order from the generic skill so dependencies (descriptions → joins →
columns → measures → multistage → host placement) resolve cleanly.

If an entry can't be encoded for any reason, skip it and queue it for
step 4.

### 3. Sanity-check the result

Pick one or two representative tasks for this DB from
`mini_interact.jsonl` (filter by `selected_database == "<db>"`). For
each, write the natural agent SLayer query that would answer the
task's `amb_user_query`. The query should be short — measure list +
dimensions + filters — with no per-task formula derivation. If a task
needs derivation, that's a sign the relevant KB entry didn't get
encoded; loop back to step 2.

### 4. Write the per-DB notes file

For every KB entry queued in step 2, create a section in
`bird-interact-agents/slayer_models/_notes/<db>.md` with the header
format above. If no entries were skipped, the file should still exist
with a one-line body ("All KB entries encoded.") so the verifier finds
it.

### 5. Export to YAML

```
python bird-interact-agents/scripts/export_slayer_models.py --db <db>
```

This reads the live SLayer storage (the one the MCP writes to —
`~/.local/share/slayer` by default, override via `$SLAYER_STORAGE`)
and writes a YAMLStorage-shaped tree at
`bird-interact-agents/slayer_models/<db>/` containing exactly the
models with `data_source == "<db>"` plus the datasource itself.
Layout:

```
bird-interact-agents/slayer_models/<db>/
├── datasources/
│   └── <db>.yaml
└── models/
    ├── <model_a>.yaml
    └── <model_b>.yaml
```

Idempotent: re-runs overwrite the destination directory, so this also
serves as the canonical refresh after fixing a recipe and re-applying.

### 6. Run the verifier — definition of done

```
python bird-interact-agents/scripts/verify_kb_coverage.py --db <db>
```

The DB is "done" when this exits 0. Anything else means at least one
KB id is unaccounted for or one KB id is in both the encoded set and
the notes file. Fix the offender and re-run until green.

## Verifier contract (so step 6 is unambiguous)

The verifier reads:

- The KB JSONL → set of all `id` values.
- The exported YAML directory → every `meta.kb_id` value across
  Columns, ModelMeasures, Aggregations, and SlayerModels.
- The notes file → KB ids parsed from `## KB <id> — …` headers.

Pass condition: every KB id is in **exactly one** of {encoded,
documented}. The verifier exits 1 (with a list of offending ids) if
any id is in zero or both sets.

## Constraints & gotchas

- **Don't recreate auto-ingested models.** Use `edit_model` to enrich
  what's already there. Only `create_model` for query-backed
  multistage models that have no host table.
- **Peer-join limitation.** Auto-ingested joins go child → parent
  (the table holding the FK reaches the referenced table). Two
  per-aspect tables that both join to the *same* parent (e.g.
  `thermalsolarwindandgrid` and `waterandwaste` both joining to
  `equipment` in the polar DB) cannot reach each other through
  bare `Column.sql` references. A composite metric that pulls
  columns from both peers needs an R-MULTISTAGE encoding (a
  query-backed model that joins both peers to the parent
  separately, then composes). When this comes up, defer the
  composite to the notes file with `Status: deferred to W4b
  R-MULTISTAGE encoding` rather than try to inline it.
- **KB ambiguity surfaces during sanity-queries, not in the
  verifier.** The verifier checks KB-coverage, not semantic
  correctness. If a sanity-query produces nonsense values
  (negative scores, exploded ranges), the encoding has a
  KB-interpretation bug — fix the formula, but the verifier will
  still pass either way. Flag the issue in the notes file under
  the KB id with `Status: encoded but value range is suspect; see
  …` if you can't immediately resolve.
- **Datasource name = DB name.** `mcp__slayer__create_datasource(name="<db>", …)`.
  The W4 fan-out depends on this — parallel agents pick distinct names
  this way.
- **Notes file always exists.** Even if zero KB entries were skipped.
  Empty body is fine; presence is what the verifier looks at.
- **Re-runnable.** `edit_model` upserts by name; re-running the skill
  on a DB updates the YAML in place. Diff-review-friendly.
