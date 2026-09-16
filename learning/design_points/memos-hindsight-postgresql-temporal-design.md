# Memos + Hindsight: Generative Temporal Indexing and Non-Generative PostgreSQL Recall

## Overview

1. The specified Memos checkout is `usememos/memos`, not MemTensor/MemOS. Its temporal behavior is document-time browsing: filter and order memos by mutable `created_ts` or `updated_ts`. It has no event-time interval, mention time, time-aware semantic rank, temporal graph, or temporal spreading.
2. Hindsight separates event time (`occurred_start` / `occurred_end`), mention time (`mentioned_at`), and processing time, then adds a temporal recall arm. Its normal fact/event extraction during indexing is generative, while its current default recall window analyzer and retrieval path are non-generative.
3. The new design deliberately keeps this latency boundary: an allowlisted generative indexer may extract atomic facts, event/reference roles, and implicit or relative time once during asynchronous indexing, while recall makes no generative call. PostgreSQL plus optional pgvector applies an explicit `time_basis = event | referenced | mentioned | created | updated` and strict window to every candidate, then returns ranked evidence rather than generating an answer.
4. The first version does not persist temporal-proximity edges or run multi-hop spreading. PostgreSQL range and timestamp indexes answer the required window and nearest-time queries directly, avoiding graph maintenance, direction ambiguity, and out-of-window expansion. Hindsight's coverage-aware selection remains useful and is reused over the bounded in-window candidate pool.

This design incorporates the current flow and caveats documented in [`temproral-retrieval-flow.md`](./temproral-retrieval-flow.md), then rechecks them against the current source. The filename's existing `temproral` spelling is preserved only in the link; this document uses “temporal.”

## Terminology and Scope

- **Source created/updated time**: The document timestamps exposed by Memos. They are user/import mutable in the current API and must not be described as immutable ingestion clocks.
- **Event time**: When the described event happened, stored as an `event` time-span annotation.
- **Referenced time**: A date or period mentioned by the source that is not asserted as the occurrence time of the indexed fact.
- **Mention time**: When the source recorded or mentioned the content. It remains distinct from event time even when only one of them is known.
- **Index time**: When the retrieval projection was published. It is operational metadata, not a user-facing temporal recall basis.
- **Time basis**: The timestamp family selected by the caller: `event`, `referenced`, `mentioned`, `created`, or `updated`.
- **Temporal window**: A validated half-open UTC interval `[start, end)` applied to the selected time basis.
- **Temporal coverage**: Deterministic selection across populated portions of a wide time window so one dense period does not monopolize every result.
- **Deterministic analyzer**: Explicit date rules plus `dateparser`; it performs no token generation and makes no model call.
- **Generative indexer**: An asynchronous, schema-constrained model call that derives atomic facts and temporal annotations from one source chunk. Its output is a rebuildable projection, never authoritative source text.
- **Non-generative encoder**: An embedding or cross-encoder model that returns vectors or relevance scores rather than generated text. The design permits these components but fixes their model identity per projection.

Scope: static source comparison of Hindsight `93a32072f2285735e50a20cae418a3fb3b216a11` and Memos `019ca26bd316c9dea7f18b90b05d1df5e2f4c1dc`, followed by a new PostgreSQL design. No live database plan, latency, recall-quality, parser-accuracy, or multilingual evaluation is claimed.

## 1. Source-Backed Comparison

Memos offers useful time-field filtering and deterministic UI range construction; Hindsight offers richer generative event/fact indexing and relevance-aware temporal retrieval. Neither current system exactly implements the proposed combination of targeted generative indexing and strict non-generative recall.

| Concern | Memos | Hindsight | New design |
|---|---|---|---|
| Retrieval unit | Whole memo | LLM-extracted fact, observation, or raw chunk in chunks mode | Grounded extracted fact with raw-chunk fallback, revision, and ordinal |
| Time fields | Mutable create/update timestamps | Event interval, mention time, derived compatibility `event_date`, create/update time | Keep event, referenced, mention, create, update, and index time separate |
| Event-time indexing | None | Usually extracted by a generative LLM; chunks mode has no event extraction | Explicit metadata first; targeted generative fact/time extraction with validation and source provenance; deterministic fallback |
| PostgreSQL time indexes | Space/status/create-time composite index | B-tree/partial indexes on event and mention fields; stored temporal edges | GiST annotation spans plus point-time B-trees; no temporal edges in v1 |
| Query window | CEL created/updated range | Explicit window or default non-generative dateparser analysis | Explicit window is authoritative; deterministic analysis is optional fallback |
| Window meaning | Strict filter on chosen document timestamp | Seeds only the temporal arm; other arms and spread targets may be outside it | Strict eligibility predicate for every arm and candidate |
| Relevance | Pinned/time sort; content substring filters | Vector-gated temporal entries, coverage selection, graph spreading, RRF/rerank | Dense + FTS relevance, optional final in-window coverage diversification, optional non-generative rerank |
| Graph behavior | None | Temporal/causal multi-hop spreading in PostgreSQL | None initially; nearest-time and overlap are computed directly |
| Generative call | None for list/filter | Normal retain extraction uses an LLM; default recall date analysis does not | Allowed only during asynchronous indexing; prohibited during recall |

### 1.1 Memos

Memos stores `created_ts` and `updated_ts` as epoch-second columns on each memo. PostgreSQL's main memo index is `(space_id, row_status, created_ts DESC, id DESC)`; there is no corresponding current index for `updated_ts`, event intervals, or temporal relevance.

Both timestamps are document attributes rather than immutable system history. Create accepts supplied timestamp values, and update masks allow callers to replace both `create_time` and `update_time`. A temporal design must therefore label them source/display time and preserve their provenance instead of treating them as trusted ingestion order.

`updated_ts` is also caller-path dependent rather than trigger-maintained: the standard web editor includes `update_time`, and dedicated relation/attachment setters advance it, but a direct API content update that omits the field need not change it. It is useful organization metadata, not a complete change log.

`ListMemos` accepts CEL predicates over `created_ts` and `updated_ts`, applies access and state predicates, then orders by pinned plus either create or update time with ID as the final tie-break. The calendar UI converts a local day or month into a half-open epoch range and filters the selected time basis. This is deterministic and useful for browsing, but it is not event-time extraction or relevance-ranked temporal recall.

References and comments do not add time semantics. Comments are excluded from the ordinary list by default, and relation lookup does not traverse or rank by timestamps.

### 1.2 Hindsight

Hindsight's normal retain path asks a generative model to classify event facts and produce `occurred_start` / `occurred_end` relative to the source date. The writer stores those fields, stores `mentioned_at`, and derives compatibility `event_date` as `occurred_start` when present, otherwise `mentioned_at`. It also constructs bounded temporal-proximity links among same-bank, same-fact-type units.

Those proximity links do not have one uniform symmetry/window contract. Cross-batch PostgreSQL linking writes new-source-to-selected-target edges and does not enforce the nominal 24-hour window before flooring far-neighbor weight at `0.3`; within-batch construction produces both directional candidates before each source's top-20 cap. Maintenance applies a different 24-hour filter. These inconsistencies strengthen the case for direct indexed time predicates in the first version.

Hindsight also has a zero-generative indexing fallback: `retain_extraction_mode="chunks"` turns each deterministic chunk into one raw unit, uses the source `event_date` as `mentioned_at`, extracts no entities or occurred dates, and reports zero LLM token usage. Setting the LLM provider to `none` forces this mode and disables observations. The new design preserves this degraded path but uses schema-constrained generative indexing when richer fact and event-time recall is needed.

Current retain also adds small per-fact offsets to occurred and mention timestamps to preserve ordering. The new design rejects that approach: factual time remains unchanged, and a separate ordinal plus stable ID resolves ties.

At recall, an explicit `TemporalWindow` skips natural-language analysis. Without it, the default `DateparserQueryAnalyzer` uses rules and `dateparser`, not a generative model; the optional transformer analyzer is a different injected implementation and is excluded from the new design.

The temporal arm retrieves up to 60 similarity-ranked in-window rows per fact type, selects up to 10 entry points across 8 time buckets, then PostgreSQL may spread over outgoing temporal and causal links. The window predicate admits either an overlapping event interval or a mention/start/end point inside the window. It does not distinguish an `event` query from a `mentioned` query.

The current window is not a strict result filter. Semantic, keyword, and ordinary graph arms remain unconstrained by it, and temporal spreading reapplies update-time filters but not the event/mention window. Consequently an in-window entry can retrieve an outside-window linked target. That is useful for related context but is the wrong default for a request whose contract is “recall evidence in this time range.”

Current temporal score metadata also has downstream gaps: the temporal list is not actually re-sorted by its `temporal_score`, and RRF keeps the first arm's result object for duplicate IDs without merging temporal proximity. The new design merges matching annotation evidence by ID and does not use a hidden midpoint multiplier.

### 1.3 Reuse, Correct, and Omit

Reuse from Memos:

- Explicit create/update time basis, half-open calendar ranges, authorization before pagination, stable ID tie-breaks, and ordinary chronological browsing.

Reuse from Hindsight and `temproral-retrieval-flow.md`:

- Asynchronous generative fact/event extraction, separate event intervals and mention time, caller-supplied windows, default non-generative query analysis, vector/lexical relevance, coverage-aware selection, and RRF.

Correct in the new design:

- Select exactly one explicit time basis; never OR mention time into an event-time query.
- Apply the same strict window predicate to dense, lexical, coverage, hydration, and rerank candidates.
- Treat generated facts and temporal annotations as rebuildable, source-grounded projections: validate their schema and source spans, preserve extractor identity, and retain raw chunks as evidence and fallback.
- Preserve factual timestamps exactly and use `unit_ordinal` for deterministic ordering.
- Treat Memos timestamps as mutable source fields and Hindsight `event_date` as a compatibility key, not an independent time truth.
- Publish deterministic parsing and embeddings only for the current document revision.

Omit from the first version:

- Observation consolidation, causal inference, temporal link construction, multi-hop spreading, and Hindsight's final temporal multiplier. Each omitted mechanism must earn its way back through a concrete retrieval need and measured quality gain.

Generative calls are permitted only in the indexing projection for grounded fact and temporal extraction. Generative query analysis, query rewriting, reranking, Reflect-style retrieval, and answer generation remain excluded from recall because they add request-path latency and nondeterminism.

## 2. Design Goals and Non-Goals

Goals:

1. Use generative calls only for high-value asynchronous indexing work; execute the complete recall path without a generative model call. Deterministic parsing, embeddings, and a scoring-only cross-encoder remain allowed.
2. Keep event, referenced, mention, source-created, source-updated, and index time semantically separate.
3. Make the query's time basis and half-open UTC window explicit, stable for the whole request, and strict across every retrieval arm.
4. Use PostgreSQL as the only durable query store, with indexed interval overlap, point-time range filtering, FTS, and optional pgvector.
5. Preserve source revision, exact timestamp origin, precision, timezone interpretation, and source span so every returned time is explainable.
6. Bound candidate work before hydration and keep chronological browsing useful when semantic encoders are unavailable.

Non-goals for the first version:

- Generating an answer or query at recall time, inferring causal graphs, or synthesizing observations.
- Treating source-created or source-updated time as event time.
- Temporal graph edges, recursive traversal, decay propagation, or Neo4j.
- Exhaustive natural-language date understanding across all languages and domain calendars.
- Bitemporal transaction-history queries, time travel over every edit, or a general audit ledger.
- Automatically pulling evidence outside the requested time window because it is linked to an in-window unit.

## 3. PostgreSQL Data Model and Indexes

The authoritative document and its current retrieval projection remain separate. The projection copies source timestamps for indexed access but never becomes their source of truth.

```text
documents
  scope_id, document_id, current_revision, original_text,
  source_created_at, source_updated_at, indexed_at, visibility
                |
                | 1:N current deterministic chunks
                v
temporal_units
  scope_id, unit_id, document_id, source_revision, unit_ordinal,
  unit_kind, extraction_origin, extractor_version, parent_chunk_id,
  text, source_span, mentioned_at, source_created_at,
  source_updated_at, indexed_at, embedding, search_vector
                |
                | 1:N explicit event or textual date annotations
                v
unit_time_annotations
  scope_id, annotation_id, unit_id, role, time_span,
  granularity, meaning, origin, raw_text, evidence_span,
  parser_version, reference_time, interpreted_timezone
```

### 3.1 Time columns

`unit_time_annotations.time_span` is a non-empty PostgreSQL `tstzrange`. An exact timestamp uses the singleton range `[t,t]`. A day, month, or year with no exact instant uses a half-open possible-period range such as `[2024-03-01,2024-04-01)` rather than pretending the event happened at midnight on March 1. An actual duration uses its declared bounds. `granularity` records `instant`, `day`, `month`, or `year`, while `meaning` distinguishes the cases.

An annotation `role` is either `event` or `date_reference`. Caller-supplied structured metadata may assert `event`; a deterministic parser emits `date_reference` unless an explicit supported grammar ties the date to the event. This prevents a chunk such as “In 2024 we discussed cancelling the 2025 plan” from becoming one invented 2024–2025 event.

`meaning` distinguishes an `instant`, an actual `duration`, and a `possible_period` such as an event known only to have happened sometime in a month. A broad possible period is returned as uncertainty; it is not rendered as an event that lasted the whole month.

`mentioned_at`, `source_created_at`, `source_updated_at`, and `indexed_at` are independent point timestamps on the unit projection. If no event is supplied, no `event` annotation exists; mention or create time is never silently copied into one.

`origin` is one of `caller`, `generative_extraction`, `deterministic_rule`, or `source_metadata`. Derived units and annotations retain their raw chunk or parent chunk, exact supporting source byte/character span, extractor/parser version, reference time, and interpreted timezone. This is enough to inspect or rebuild the current projection without adding a history ledger.

The database enforces the following logical constraints; a migration must name constraints and adapt types to the chosen scope/document identifiers:

```sql
ALTER TABLE documents
  ADD PRIMARY KEY (scope_id, document_id);

ALTER TABLE temporal_units
  ADD PRIMARY KEY (scope_id, unit_id),
  ADD UNIQUE (scope_id, document_id, source_revision, unit_ordinal),
  ADD FOREIGN KEY (scope_id, document_id)
    REFERENCES documents(scope_id, document_id) ON DELETE CASCADE;

ALTER TABLE unit_time_annotations
  ALTER COLUMN time_span SET NOT NULL,
  ADD PRIMARY KEY (scope_id, annotation_id),
  ADD CHECK (NOT isempty(time_span)),
  ADD FOREIGN KEY (scope_id, unit_id)
    REFERENCES temporal_units(scope_id, unit_id) ON DELETE CASCADE;
```

### 3.2 Query indexes

The initial index set is:

```sql
CREATE INDEX temporal_units_mentioned_at
  ON temporal_units (scope_id, mentioned_at, unit_id)
  WHERE mentioned_at IS NOT NULL;

CREATE INDEX temporal_units_source_created_at
  ON temporal_units (scope_id, source_created_at, unit_id);

CREATE INDEX temporal_units_source_updated_at
  ON temporal_units (scope_id, source_updated_at, unit_id);

CREATE INDEX temporal_units_fts
  ON temporal_units USING gin (search_vector);

CREATE INDEX unit_time_annotations_scope_role_unit
  ON unit_time_annotations (scope_id, role, unit_id);

CREATE INDEX unit_time_annotations_span_gist
  ON unit_time_annotations USING gist (time_span);
```

An optional cosine HNSW index serves the fixed embedding model. One projection uses one model identity, version, dimension, tokenizer, and normalization contract; changing any of them rebuilds the projection. Filtered ANN Recall@K must be compared with exact vector search for realistic scope/window distributions before HNSW becomes the default plan.

The first slice deliberately avoids `btree_gist`, partitioning, per-user partial vector indexes, and a composite GiST until real scope/selectivity plans show they are needed. PostgreSQL can combine the scope B-tree and range GiST through bitmap plans; this must be verified rather than assumed.

No `temporal_links` table is required. Overlap comes from GiST, while chronological and nearest-before/after queries for mention/create/update bases use their B-trees. Event/reference browsing first applies the overlap index and then performs a bounded sort by the selected intersection lower bound; GiST alone is not claimed to provide that order. Add an expression B-tree only if a real plan shows it is needed. If later evidence proves a persisted relation valuable, it must represent more than a date-distance cache that SQL can recompute.

## 4. Hybrid Indexing Flow

Indexing spends generative-model latency only where it adds durable retrieval value. All model work happens outside the user-facing recall path, and every derived unit remains traceable to immutable source evidence.

1. In one short transaction, authorize the write, lock the document, increment `current_revision`, store exact Memos-style source created/updated timestamps plus their provenance, and enqueue an idempotent job for `(scope_id, document_id, revision, indexer_version)`.
2. A worker claims the job and releases the database connection. It chunks the source deterministically by existing text/structured boundaries and stores each raw chunk as authoritative evidence and a recall-eligible fallback unit. A chunk remains eligible even when only part of it is represented by accepted facts.
3. Caller-supplied structured event metadata creates authoritative `event` annotations before model extraction and should identify an exact source span or explicit structured item. After extraction, an annotation moves to an accepted fact only when that fact's supporting span covers the annotation span; an unmapped or chunk-level annotation remains attached to the recall-eligible raw chunk. Generated annotations for the same supported assertion cannot replace or compete with the caller value in recall; conflicting generated values are rejected from the published projection and counted for evaluation.
4. When the generative indexer is enabled, call it independently for each bounded chunk with the captured reference time and timezone. Its strict output schema contains atomic fact text, an exact supporting source span, and zero or more temporal annotations with `role`, bounds, granularity, meaning, and supporting span. The useful jobs are fact boundary extraction, event-versus-reference classification, and implicit or relative time resolution; observation synthesis, answer generation, and unused causal inference remain disabled.
5. Validate generated output before persistence: roles and enum values must be allowlisted, ranges must be valid, supporting spans must resolve inside the chunk, and quoted evidence must match the source. Reject an invalid fact or annotation independently. The raw chunk remains searchable for facts, text spans, and caller annotations not covered by accepted extracted facts rather than failing ingestion or assuming partial extraction is complete.
6. An optional deterministic parser supplements missing explicit date references and provides the no-model fallback. It normally emits `date_reference`; it emits `event` only for a narrow grammar that deterministically asserts occurrence. Identical spans are deduplicated by role and range, while a legitimate event/reference distinction remains as two annotations with visible origins.
7. `mentioned_at` comes only from an explicit caller/source field. Memos `source_created_at` may be used as a caller-declared mention time, but the mapping is recorded; it is not silently treated as an event.
8. Assign `unit_ordinal` in document order. Extracted facts link to their parent chunk and use a stable sub-ordinal. Equal timestamps retain their exact values and sort by ordinal/ID; unlike current Hindsight, indexing never adds artificial seconds to factual time. Raw chunks and accepted facts may both enter candidate retrieval: an extracted fact is preferred only when it represents the same source span and matched temporal annotation, while distinct or uncovered raw evidence remains independently eligible.
9. Build the PostgreSQL text-search vector and, when enabled, one embedding with the fixed non-generative encoder. Generative extraction, deterministic parsing, and encoding all happen outside the publish transaction.
10. In one publish transaction, lock the document and compare its current revision with the job revision. A mismatch discards the stale projection. A match batch-inserts the chunks, accepted facts, and time annotations, then marks the revision ready.
11. Old projection rows become ineligible immediately through `source_revision = documents.current_revision` and may be cleaned later in small batches.

The simplest degraded deployment uses raw chunks, FTS, caller times, and deterministic date references. Enabling the generative indexer improves fact granularity and event-time interpretation without adding recall latency or changing the strict temporal contract.

## 5. Non-Generative Recall Flow

The core temporal API accepts a structured `window` and mandatory `time_basis`. A convenience adapter may run Hindsight-style rules plus `dateparser` before calling the core, but parser failure never silently broadens a request that required temporal filtering.

```text
query_text: optional
time_basis: event | referenced | mentioned | created | updated
window: {start, end} in UTC, start < end
reference_time/timezone: required only by the optional deterministic adapter
limit: bounded
cursor: available only for time-only browsing; tied to basis, window, sort, and scope
```

### 5.1 One whitelisted predicate per basis

The query compiler selects one indexed predicate; it does not use a runtime `CASE` or combine unrelated clocks with `OR`:

```sql
-- event: EXISTS an overlapping annotation with role='event'
time_span && tstzrange($start, $end, '[)')

-- referenced: EXISTS an overlapping annotation with role='date_reference'
time_span && tstzrange($start, $end, '[)')

-- mentioned
mentioned_at >= $start AND mentioned_at < $end

-- created
source_created_at >= $start AND source_created_at < $end

-- updated
source_updated_at >= $start AND source_updated_at < $end
```

The two range branches differ by an indexed `role` predicate even though their overlap operator is the same. Every branch also requires the caller's scope and visibility, a non-deleted source, and `unit.source_revision = document.current_revision`. These predicates execute before all candidate limits.

### 5.2 Ranked recall

1. Validate and freeze scope, authorization, time basis, window, timezone interpretation, and absolute deadline.
2. Start lexical FTS immediately. If an encoder is enabled, compute one query embedding and then run dense retrieval with the identical strict temporal predicate.
3. Return narrow candidate rows containing unit ID, arm, relevance, selected-basis time/range, document ID, revision, and ordinal. Do not hydrate full text for candidates that may be discarded.
4. Fuse dense and lexical ranks with RRF. For `event`/`referenced`, collect all matching annotations per unit, intersect each `time_span` with the query span, and choose the earliest intersection with annotation-ID tie-break as that unit's deterministic coverage position while returning every matching annotation as evidence. Before later caps, collapse only candidates with the same source chunk, supporting span, selected time basis, and matched annotation identity; prefer the extracted fact over the raw chunk for that exact duplicate. Do not collapse distinct or uncovered raw spans merely because another fact from the chunk was extracted.
5. Apply the per-document cap. When the request explicitly asks for coverage across a broad window, use bounded final diversification: select the highest fused-rank candidate from each populated time bucket before a bucket contributes a second candidate, then fill unused slots by fused relevance. Coverage changes membership within the already bounded pool; it is not a second retrieval arm or extra RRF vote and does not promise every bucket survives later result limits.
6. Hydrate the survivors in one query that rechecks scope, authorization, current revision, and the same temporal predicate. Optionally run one bounded scoring-only cross-encoder when the shared deadline allows it; it may reorder but does not widen or add candidates. Return evidence with its selected time basis, range, role, origin, granularity, meaning, and source span. When several annotations match, merge them by annotation ID rather than keeping whichever retrieval-arm object appeared first.

The Hindsight starting values of a 60-candidate temporal pool, 8 coverage buckets, and 10 coverage selections are reasonable experiment defaults for explicit coverage mode, not measured constants for this design. They must be tuned against recall quality and query plans rather than copied as universal limits.

### 5.3 Time-only browsing

When `query_text` is absent, skip embeddings, FTS, RRF, and reranking. Use the selected basis index and keyset pagination. Event/reference results order by the lower bound of the earliest matching `time_span * query_span` intersection, then annotation ID, ordinal, and unit ID; point-time bases order by their timestamp plus unit ID. This preserves the useful Memos calendar/list path without offset pagination drift on unchanged rows. Ranked recall is a bounded top-result operation and does not reuse this chronological cursor.

## 6. Ranking, Coverage, and Time Semantics

Temporal eligibility and temporal preference are separate. The strict predicate decides whether a unit may appear; ranking decides which eligible units best answer the query.

- Dense and lexical arms measure content relevance only inside the selected window.
- Optional final coverage diversification rewards representation of populated periods without pretending that proximity to the window midpoint is relevance.
- RRF combines ranks without adding cosine similarity, FTS score, timestamp distance, and parser confidence as if they shared a calibrated scale.
- `origin`, `granularity`, and `meaning` are explanation fields, not hidden score multipliers. A parser-derived month is not automatically less relevant than a caller-supplied day.
- A time-only query uses chronological order, not semantic scores.

Basis semantics are exact:

| Basis | Eligibility | Representative time for coverage/order |
|---|---|---|
| `event` | An `event` annotation overlaps the query range | Midpoint of the selected annotation/window intersection for bucketing; intersection lower bound for chronological order |
| `referenced` | A `date_reference` annotation overlaps the query range | Midpoint of the selected annotation/window intersection for bucketing; intersection lower bound for chronological order |
| `mentioned` | `mentioned_at` lies in `[start, end)` | `mentioned_at` |
| `created` | `source_created_at` lies in `[start, end)` | `source_created_at` |
| `updated` | `source_updated_at` lies in `[start, end)` | `source_updated_at` |

A local calendar day is resolved once by the caller or adapter into a timezone-aware half-open UTC range, preserving Memos's correct DST-sensitive calendar behavior. Server-side field accessors must not reinterpret that range in UTC calendar terms.

## 7. Updates, Authorization, and Failure Behavior

The following are invariants:

1. All candidate-producing branches filter scope, authorization, deletion state, current source revision, and the selected temporal window before their caps. Hidden or stale units cannot consume a cap or alter coverage.
2. Updating a document increments its revision. The prior projection is immediately ineligible, and a worker may publish only the revision it claimed.
3. Source created/updated timestamps remain mutable user/source metadata. `indexed_at` records projection publication but is never substituted into recall.
4. The same browse request keeps one frozen window and reference time across pages. Keyset cursors bind the scope, basis, window, sort direction, and last tuple, preventing offset drift only while indexed rows stay unchanged; live edits may legitimately change later pages and are reauthorized on every request.
5. The optional parser is deterministic and versioned. If temporal recall requires a window and parsing fails, return a validation result with no query execution rather than broad recall.
6. Embedding failure degrades to FTS plus optional coverage; FTS failure degrades to dense plus optional coverage; both unavailable degrade to strict chronological recall with `content_relevance_unavailable=true`. Authorization failure fails closed.
7. All SQL and the optional reranker consume one absolute deadline. A fallback receives only the remaining time.
8. Result metadata states which arms ran or degraded and whether the window was caller-supplied or deterministically parsed.
9. Configuration closure separates the two dependency graphs. Indexing may reach only the allowlisted schema-constrained extractor and disables observation consolidation or unused causal generation; recall allowlists only non-generative analyzers and rejects query rewriting, Reflect, generative reranking, and answer generation. A fail-on-call provider test on the recall service proves no generative adapter is reachable from a recall request.

## 8. Worked Example

Generative indexing adds value by separating two grounded facts and their temporal roles from one ambiguous source chunk; recall then uses only the stored PostgreSQL projection.

Assume one current memo revision contains:

```text
“In 2024 we discussed cancelling the 2025 trip.
 The replacement planning meeting happened on March 10, 2026.”
```

Its source timestamps are:

```text
source_created_at = 2026-01-12T09:00:00+08:00
source_updated_at = 2026-09-05T18:00:00+08:00
mentioned_at      = 2026-01-12T09:00:00+08:00
```

The schema-constrained indexer produces two facts whose supporting spans resolve exactly inside the raw chunk:

```text
U1 fact="We discussed cancelling the 2025 trip."
   support="In 2024 we discussed cancelling the 2025 trip."
   A1 role=event          time_span=[2024-01-01, 2025-01-01) meaning=possible_period origin=generative_extraction
   A2 role=date_reference time_span=[2025-01-01, 2026-01-01) meaning=possible_period origin=generative_extraction

U2 fact="The replacement planning meeting happened on March 10, 2026."
   support="The replacement planning meeting happened on March 10, 2026."
   A3 role=event          time_span=[2026-03-10, 2026-03-11) meaning=possible_period origin=generative_extraction
```

The stored facts behave differently under each explicit recall basis:

1. `event` + calendar year 2024 returns `U1` through `A1`.
2. `referenced` + calendar year 2025 returns `U1` through `A2`, with `possible_period` and the exact source span exposed.
3. `event` + calendar year 2025 does not return `U1`; the trip's year is referenced, not the time of the discussion.
4. `event` + March 2026 returns `U2` through `A3`.
5. `created` + January 2026 returns both units from `source_created_at`; `updated` + September 2026 returns them from `source_updated_at`.
6. `mentioned` + March 2026 returns neither unit because the source mention timestamp is in January.

No generative call occurs for any of these recall queries. If indexing generation fails, the raw chunk remains searchable, and the deterministic parser may preserve `2024`, `2025`, and `March 10, 2026` as date references; event-basis recall may be weaker, but ingestion remains available and the system does not invent event roles.

## 9. Incremental Delivery and Acceptance Gates

Delivery should prove grounded generative indexing and the strict non-generative PostgreSQL recall path before adding optional reranking or graph behavior.

1. **Timestamp baseline:** Capture the current Memos created/updated filters and the current Hindsight temporal-arm behavior on a fixed corpus, including the distinction that Hindsight's window is not global.
2. **Schema and explicit metadata:** Add document revisions, raw chunks, extracted-fact units, point timestamps, `unit_time_annotations`, B-tree/GiST/FTS indexes, keyset cursors, and caller-supplied event ranges. Run time-only browsing and FTS recall with generation disabled.
3. **Grounded generative indexing:** Add the one-chunk schema-constrained extractor for atomic facts, event/reference roles, and relative-time resolution. Validate source spans and temporal values independently, preserve extractor identity, and prove failure falls back to the raw chunk.
4. **Deterministic supplement:** Add a narrow rules/dateparser adapter that supplies explicit `date_reference` annotations and only grammar-proven `event` annotations when the generator is disabled or omits them. Version it and preserve conflicts rather than silently selecting one truth.
5. **Strict ranked recall:** Add dense retrieval with the exact same basis/window predicate, RRF, optional bounded temporal coverage, per-document caps, narrow candidate rows, and one hydration query. The recall process has no generative provider dependency.
6. **Optional reranker:** Add a scoring-only cross-encoder only if it improves relevance without violating the shared deadline or temporal eligibility.
7. **Reassess omitted mechanisms:** Compare the completed direct-index design with a temporal-edge experiment only if a concrete query set still lacks reachable evidence.

Required fail-capable cases are:

- Source created time and event time differ by a year; each basis returns only its own result.
- An event is outside the window while its mention time is inside; `event` excludes it and `mentioned` includes it.
- One chunk contains several facts and unrelated dates; accepted facts have exact supporting spans, each date is preserved separately, and none becomes one invented interval.
- Malformed, ungrounded, timed-out, and partially valid extractor outputs reject only invalid derived records and leave the raw chunk searchable.
- One chunk contains facts A and B, the caller attaches an event annotation to B's exact span, and the generator accepts only A; strict event recall still returns B through the raw chunk and does not treat A as coverage of B.
- Caller annotations are not overwritten or made ambiguous in recall by conflicting generated annotations; rejected conflicts are counted, and every published origin remains visible.
- Day, month, year, exact instant, duration, unknown time, leap day, and DST-transition windows have correct half-open boundaries.
- Caller-supplied local day boundaries convert independently to UTC and never assume every day is 24 hours.
- Equal timestamps remain unchanged and order deterministically by ordinal/ID.
- A stale indexing job cannot publish after the source revision changes.
- Private, deleted, wrong-scope, and old-revision units neither appear nor consume candidate/coverage caps.
- Parser failure cannot silently turn a required temporal request into unrestricted recall.
- Embedding timeout falls back within the same strict window; authorization failure fails closed.
- Keyset pagination has no gaps or duplicates for a frozen window/reference time on an unchanged corpus; live-edit behavior is documented and reauthorized rather than presented as snapshot isolation.
- Exact vector search and filtered ANN are compared for Recall@K before ANN is accepted.
- `EXPLAIN (ANALYZE, BUFFERS)` verifies actual scanned/returned rows and index usage for narrow/broad ranges, high-cardinality scopes, and sparse ACL filters.
- Indexing instrumentation records the allowlisted extractor calls and versions; a fail-on-call provider attached to the recall process proves no generative provider is invoked by any recall request.

Success is improved temporal evidence recall or browsing over the Memos baseline without losing the strict window, plus equal or better relevance than FTS-only retrieval. No target latency or quality number is asserted before the corpus and workload are defined.

## 10. Deferred Work

Defer until measured evidence requires it:

- Temporal-proximity edges, causal edges, recursive spreading, propagation decay, or Neo4j.
- Automatic conflict resolution among caller, generative, and deterministic temporal annotations without evaluation evidence.
- Recurring-event rules, business/fiscal calendars, timezone geocoding from place names, and Allen interval algebra.
- Bitemporal history, valid-time corrections across every source revision, and a general lineage ledger.
- Composite GiST via `btree_gist`, table partitioning, per-scope HNSW indexes, and adaptive plan selection before query-plan evidence.
- Automatic expansion through Memos references/comments or Hindsight graph relations outside the requested strict window.
- Recency decay as a universal relevance signal; chronology remains an explicit browse mode.

Generative fact/date extraction is part of indexing. Observation consolidation, unused causal inference, generative query analysis, query rewriting, generative reranking, Reflect-style retrieval, and answer generation are outside the recall boundary and require a separate latency and product decision.

## 11. Final Comparison and Summary

The design keeps Hindsight's useful asynchronous semantic extraction but replaces its permissive temporal expansion with an explicit, strictly filtered, non-generative PostgreSQL recall contract.

| Area | Memos | Hindsight | New design |
|---|---|---|---|
| Temporal capability | Browse/filter mutable memo create or update time | Generatively extract facts and event intervals, then use temporal retrieval and spreading | Generatively extract grounded facts/times once, then recall through strict PostgreSQL predicates |
| Indexing unit | Whole memo | Extracted fact, observation, or raw chunk | Extracted fact linked to an exact raw-chunk span, with raw-chunk fallback |
| Generative work | None for time browsing | Normal indexing uses it | Allowed only in asynchronous indexing for fact boundaries, temporal roles, and implicit/relative time |
| Recall work | Timestamp filtering and ordering | Non-generative default query analysis plus semantic, keyword, graph, and temporal arms | Non-generative FTS/pgvector, RRF, optional coverage, and scoring-only reranking |
| Window contract | Strict for the selected create/update field | Temporal seeds are in-window, but other arms and spread targets may be outside | One explicit basis and window constrain every candidate-producing and hydration stage |
| Temporal graph | None | Stored temporal links and bounded spreading | None in v1; GiST overlap and B-tree point-time queries compute the relationship directly |
| Failure behavior | No event-time interpretation | Depends on configured retain mode and model extraction | Invalid extraction falls back to the raw chunk; recall remains available and does not invent event roles |

The shared Hindsight components are event intervals distinct from mention time, caller-supplied windows, non-generative default date analysis, vector and lexical relevance, RRF, and coverage-aware selection. The differences are source-span validation and raw fallback for generated facts, separate `event`/`referenced`/`mentioned` bases, a strict global temporal eligibility predicate, exact timestamps with ordinal tie-breaking, and no temporal edge maintenance or spreading.

For the Section 8 memo, Memos alone can find the record by January creation or September update but cannot answer when its two described events occurred. Hindsight can extract the 2024 discussion and March 2026 meeting, but a temporal query can still receive results from unconstrained arms or outside-window spread targets. The new design performs the useful fact/time extraction during indexing, then an `event + March 2026` recall reaches only the stored meeting fact through PostgreSQL while `referenced + 2025` reaches only the trip reference; neither query invokes a generative model.

In one sentence: **Hindsight uses inferred temporal facts to expand recall; this design uses generated but source-grounded temporal facts to strictly constrain non-generative recall.**

## 12. Source Map and Verification Boundary

Both the primary design pass and the requested GPT-6 subagent read all 323 lines of [`temproral-retrieval-flow.md`](./temproral-retrieval-flow.md), then rechecked its flow and caveats against the current source. The new design reuses generative fact/event extraction at index time, its time vocabulary, explicit-window path, non-generative default analyzer, bounded candidate pool, and coverage selection; it replaces mixed effective time, temporal edges/spreading, midpoint boosting, and timestamp offsets with grounded annotations and a strict recall predicate.

Memos `019ca26bd316c9dea7f18b90b05d1df5e2f4c1dc`:

- Memo timestamps and the only current memo time index: `/Users/rocke_dong/codes/memos/store/migration/postgres/LATEST.sql:53-79`.
- Custom create/update timestamps at insert: `/Users/rocke_dong/codes/memos/store/db/postgres/memo.go:35-65`.
- Mutable `create_time` and `update_time`: `/Users/rocke_dong/codes/memos/server/api/v1/memo_service.go:404-418`.
- Caller-path-dependent update-time maintenance: `/Users/rocke_dong/codes/memos/store/db/postgres/memo_attachment.go:181-225` and `/Users/rocke_dong/codes/memos/web/src/components/MemoEditor/services/memoService.ts:32-58`.
- Time ordering and stable ID tie-break: `/Users/rocke_dong/codes/memos/server/api/v1/memo_service_query.go:11-66` and `/Users/rocke_dong/codes/memos/store/db/postgres/memo.go:170-184`.
- Calendar day/month to half-open local-time range: `/Users/rocke_dong/codes/memos/web/src/lib/calendar-utils.ts:19-72`.
- CEL timestamp fields and range rendering: `/Users/rocke_dong/codes/memos/filter/schema.go:130-157` and `/Users/rocke_dong/codes/memos/filter/render.go:313-351`.
- Access, state, filter, and pagination before relation hydration: `/Users/rocke_dong/codes/memos/server/api/v1/memo_service.go:81-154` and `/Users/rocke_dong/codes/memos/server/api/v1/memo_service_converter.go:224-332`.

Hindsight `93a32072f2285735e50a20cae418a3fb3b216a11`:

- Generative event-time extraction semantics: `hindsight-api-slim/hindsight_api/engine/retain/fact_extraction.py:255-280,1245-1293`.
- Existing zero-LLM chunks mode and provider-none forcing: `hindsight-api-slim/hindsight_api/engine/retain/fact_extraction.py:3163-3220,3260-3263` and `hindsight-api-slim/hindsight_api/config.py:3853-3859`.
- Current artificial temporal offsets: `hindsight-api-slim/hindsight_api/engine/retain/fact_extraction.py:3447-3471`.
- Compatibility `event_date = occurred_start else mentioned_at`: `hindsight-api-slim/hindsight_api/engine/memories/pg/writes.py:76-86`.
- Temporal-link construction and caps: `hindsight-api-slim/hindsight_api/engine/retain/link_utils.py:60-180,455-570` and `hindsight-api-slim/hindsight_api/engine/db/ops_postgresql.py:840-897`.
- Caller window, default non-generative analyzer, and parser failure behavior: `hindsight-api-slim/hindsight_api/engine/response_models.py:299-332`, `hindsight-api-slim/hindsight_api/engine/search/temporal_extraction.py:64-146`, and `hindsight-api-slim/hindsight_api/engine/search/retrieval.py:852-871`.
- Entry overlap, 60-row pool, 8-bucket/10-entry coverage, and spreading: `hindsight-api-slim/hindsight_api/engine/search/retrieval.py:401-457,534-607,658-788`.
- Temporal-score ordering and RRF object-retention gaps: `hindsight-api-slim/hindsight_api/engine/memory_engine.py:8077-8085` and `hindsight-api-slim/hindsight_api/engine/search/fusion.py:50-105`.
- Temporal date indexes: `hindsight-api-slim/hindsight_api/alembic/versions/b3c4d5e6f7g8_add_temporal_date_indexes.py:1-68`.

This document is a static source comparison and unimplemented design. No PostgreSQL migration, query plan, parser, embedding, service, latency test, or answer-quality evaluation was run. All proposed schema, caps, ranking behavior, and delivery gates remain unverified until implemented and measured.
