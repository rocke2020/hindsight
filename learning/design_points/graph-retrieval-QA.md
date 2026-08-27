# Graph Retrieval Q&A: Nine Questions on the Flow Doc

> **TL;DR:** All nine questions are answered against the `dev@278cde1` code, and every claim in the companion flow doc's disputed lines (92, 111, 115-121, 129) is **confirmed correct**. The graph is not causal-only; Link Expansion is one bounded pass with three additive scores; ordinary retain writes only `caused_by` while retrieval still reads the legacy `causes/enables/prevents` types; Oracle's temporal arm returns only entry points because it skips the `unnest`-based spreading loop. One real code defect was found: the module header of `link_expansion_retrieval.py` is stale prose that contradicts its own implementation.

Scope: companion to [graph-retrieval-flow.md](graph-retrieval-flow.md). Answers were produced by two independent readers — direct code reading plus a read-only Codex consultation — and merged; the two agreed on every point. Paths below are relative to `hindsight-api-slim/hindsight_api/` unless a `tests/` prefix is present.

## Terminology

- **Fact type**: the retrieval category stored on each memory unit. The complete current set is `world` (objective or external facts, including user preferences, rules, constraints, people, and events), `experience` (actions, experiences, or observations the assistant/agent actually performed), and `observation` (an evidence-backed belief produced by consolidating supporting facts). Retain-time extraction creates `world` and `experience` units; consolidation creates `observation` units. Mental models are separate objects, not a fact type. Thus, “same-fact-type” in §2 means the ANN pass only links a seed to a neighbor whose category is identical; it never creates a semantic edge across these three categories.
- **Posting table**: a junction table that materializes a membership relation as rows — here `unit_entities(unit_id, entity_id)` posting which facts mention which canonical entities.
- **Entry point**: an in-window, similarity-gated memory unit chosen to start the temporal arm; the only thing Oracle's temporal arm returns.
- **Frontier**: the mutable worklist of a BFS-style loop. Link Expansion has none; the Postgres temporal arm does.
- **Activation**: the graph arm's internal ranking score, the sum of the entity/semantic/causal signal scores.
- **Stale header**: a module docstring that documents behavior the code no longer has.

## 1. Is the graph only used for causal analysis?

No — causal links are just one of the graph's uses, and not the largest. The stored graph (`memory_links` + `unit_entities`) is read by:

1. **The Link Expansion recall arm** — all three signals: shared entities via `unit_entities`, semantic links, and causal links (`search/link_expansion_retrieval.py:293-338`, `db/ops_postgresql.py:788-887`).
2. **The Postgres temporal recall arm** — its spreading loop follows outgoing `temporal` plus all four causal link types (`search/retrieval.py:719-724`).
3. **Reflect** — indirectly: it has no direct `memory_links` access, but its `recall()` tool runs the full arm set, graph included.
4. **Retain-time maintenance** — `graph_maintenance.py` relinks temporal/semantic edges; entity resolution itself consumes the `entity_cooccurrences` cache derived from the graph.

`entity_cooccurrences` is never a recall traversal source — recall's entity signal reads `unit_entities`.

## 2. What are semantic graph links?

A semantic link is a directed `memory_links` row `(from_unit_id, to_unit_id, link_type='semantic', weight)` where **weight is the cosine similarity measured at retain time**. Construction:

- During streaming retain, per-batch semantic links are skipped; after all batches commit, a best-effort final ANN pass treats each new unit as a seed, searches same-bank, same-fact-type units with `top_k=20` ("Recall uses at most 20 neighbors", `retain/orchestrator.py:1969-1975`), clamps similarity to [0,1], and keeps only edges at or above `semantic_link_min_similarity` (default **0.7**, `config.py:1038`) — see `retain/link_utils.py:629-664`.
- Within-batch similarities are computed in numpy with the same threshold, no DB needed (`link_utils.py:673-729`).
- Failure of this pass does not roll back retained facts — vector recall still works, but semantic graph edges stay incomplete until an explicit relink/repair.

At recall the rows are read **in both directions** (the stored graph is not assumed symmetric), and each candidate's semantic score is the `MAX(weight)` across all seed connections (`ops_postgresql.py:833-871`).

## 3. What is the chunk size?

`DEFAULT_RETAIN_CHUNK_SIZE = 3000` **characters** (not tokens), `config.py:1243`, exposed as `HINDSIGHT_API_RETAIN_CHUNK_SIZE` / hierarchical field `retain_chunk_size`. It bounds each chunk handed to fact extraction (`retain/fact_extraction.py:2004`); plain text splits on sentence/separator boundaries, JSON conversations and JSONL prefer turn/line boundaries. A separate optional `retain_structured_chunk_size` (default unset) can let one structured turn/line stay whole; when unset it falls back to the same 3000-char limit. Unrelated to graphs — this is the retain ingestion knob.

## 4. What is canonical entity resolution?

It is the mapping of every entity mention (extracted or caller-supplied) onto **one persistent `entities` row**, reusing that row's id and stored `canonical_name`, so that "Python", "python", and "Python language" all post to the same node. Flow:

1. `retain/entity_processing.py` merges extractor entities with caller-supplied ones per fact and dedups case-insensitively. Extracted names default to fuzzy resolution; caller names can opt out (`resolve: False` → literal, case-insensitive exact match only, never merged — #3479).
2. `retain/link_utils.py:196-301` normalizes whitespace, drops empty names, flattens mentions, and attaches same-fact peers as `nearby_entities` context.
3. `EntityResolver` fetches candidate canonical rows — indexed pg_trgm trigram lookup on PostgreSQL, exact matching for label entities (`entity_resolver.py:703-790`).
4. Each candidate passes name-compatibility gates (word-level similarity, so "John Smith"/"Jane Smith" do not merge), then is scored: **name similarity ×0.5 + co-occurrence overlap ×0.3 + temporal proximity ×0.2, reuse threshold 0.6** (`entity_resolver.py:1177-1210`).
5. If nothing clears the threshold, a new entity is inserted (with intrabatch near-duplicate clustering, cutoff 0.5), then Phase 2 writes the `(unit_id, entity_id)` postings into `unit_entities` inside the fact transaction (`retain/orchestrator.py:549-571`).

Resolution quality directly changes graph topology: a wrongly split or merged entity changes which facts count as "shared-entity" neighbors at recall.

## 5. `unit_entities`, and the causal link types — is the doc's line 92 right?

Yes, line 92 is correct on both claims.

`unit_entities` is the many-to-many **posting table** between memory units and canonical entities (PK `(unit_id, entity_id)`, FKs to both parents, written in `orchestrator.py:571`). It is the entity-recall truth source: Link Expansion self-joins it to find facts sharing entities (`ops_postgresql.py:788-819`). `entity_cooccurrences` is only a derived statistics cache (used by resolution and the UI graph view).

**Concrete example — entity registry versus fact membership.** Suppose retain extracts these two memory units; the IDs below are shortened only for readability:

| `memory_units.id` | Fact text |
|---|---|
| `MU_A` | Alice builds REST APIs with Python at TechCorp. |
| `MU_B` | Bob trains fraud-detection models with Python at DataSoft. |

Entity resolution creates one canonical row per distinct entity in the bank. In particular, both mentions of “Python” resolve to the same `E_PYTHON` row:

| `entities.id` | `entities.canonical_name` |
|---|---|
| `E_ALICE` | Alice |
| `E_BOB` | Bob |
| `E_PYTHON` | Python |
| `E_TECHCORP` | TechCorp |
| `E_DATASOFT` | DataSoft |

`unit_entities` then records every fact-to-entity membership:

| `unit_entities.unit_id` | `unit_entities.entity_id` |
|---|---|
| `MU_A` | `E_ALICE` |
| `MU_A` | `E_PYTHON` |
| `MU_A` | `E_TECHCORP` |
| `MU_B` | `E_BOB` |
| `MU_B` | `E_PYTHON` |
| `MU_B` | `E_DATASOFT` |

The difference is now visible: `entities` says **what canonical things exist**; `unit_entities` says **which memory units mention each thing**. Starting from seed `MU_A`, Link Expansion follows `MU_A -> E_PYTHON -> MU_B`. The shared `E_PYTHON` posting is what makes `MU_B` an entity-expanded candidate; the `entities` row alone cannot show that the two facts share Python.

On causal types: ordinary retain writes **only `caused_by`** — the extraction schema constrains `relation_type` to it, and the writer accepts only `CANONICAL_CAUSAL_LINK_TYPES`, each edge at weight `1.0` (`causal_links.py:11-18`, `retain/link_utils.py:811-830`, `874-910`). `causes`, `enables`, `prevents` are **legacy** types: new rows of those types can only be created by transfer-archive import via `restore_legacy_causal_links_batch` (`link_utils.py:833-852`), but retrieval keeps reading all four (`ops_postgresql.py:883`, `retrieval.py:721`) so existing banks keep their semantics. So "old version used `causes`/`enables`/`prevents`" — yes, and those rows are still honored at read time.

## 6. Is Link Expansion really one pass, not multi-hop?

Yes — confirmed in code, and yes, the design intent is a simple, fast online query. The whole expansion for a fact type is **one SQL statement** (`_expand_combined`, `link_expansion_retrieval.py:293-359`): a CTE union of entity/semantic/causal expansions over the *fixed* seed set, one roundtrip, one connection slot. Candidates it discovers are never fed back as a new frontier. The bounds:

- **20 seeds** — `GRAPH_SEED_LIMIT = 20` (`link_expansion_retrieval.py:44`); seeds come from the shared semantic pool when thresholds allow, else the retriever runs its own seed query.
- **200 candidates per entity** — `DEFAULT_LINK_EXPANSION_PER_ENTITY_LIMIT = 200` (`config.py:1236`) applied inside the per-entity LATERAL subquery *before* aggregation.
- **Recall budget** — each signal's CTE ends `LIMIT $3` (the budget), and Python cuts the final merged list to `budget` again.

Contrast: the **temporal arm** is the only recall path with a mutable frontier and iteration (batch 20, 10 neighbors per source, max 5 iterations — `retrieval.py:663-695`). The rationale for one-pass: online recall must stay low-latency and bounded; multi-hop fan-out is exactly the cost a 10-second timeout and the LATERAL caps exist to prevent. Deeper traversal is deliberately left to the temporal arm's tightly-budgeted loop and to consolidation (offline).

## 7. `semantic_link_weight` vs `causal_link_weight`, and the three scores

The two weights are **stored column values** in `memory_links.weight`, not retrieval-time multipliers:

- **semantic weight** = the cosine similarity that created the edge at retain time, ∈ [0,1] by construction (floor 0.7 to exist at all);
- **causal weight** = the explicit edge weight from extraction; ordinary retain writes a constant `1.0` (legacy imported edges may carry other values).

The three per-candidate scores (`link_expansion_retrieval.py:227-262`):

```text
entity_score   = tanh(distinct_shared_entity_count * 0.5)   # saturating: 1→0.46, 2→0.76, 3→0.91
semantic_score = max(semantic_link_weight)                   # best edge from any seed, either direction
causal_score   = max(causal_link_weight)                     # best outgoing edge from any seed

activation     = entity_score + semantic_score + causal_score   # ∈ [0, 3]
```

The design point of each shape: `tanh` makes entity co-occurrence saturate (one more shared entity matters less the more you already have); `max` (not sum) for semantic/causal means the strength of the *best evidence* counts, so a candidate linked by many weak edges does not outrank one strong edge; the additive sum rewards **convergent evidence** — a fact reachable by two independent signals beats a fact with one strong signal. This activation ranks only the graph arm; fusion downstream uses rank positions, not raw activation.

**Known stale prose:** the module header of `link_expansion_retrieval.py` (lines 5-16) claims all three signals live in `memory_links` and that causal score is `weight + 1.0`. Both statements are false for the current code (entity expansion reads `unit_entities`; the merge step at lines 246-254 uses raw `weight`). The flow doc's "source caution" (its line 243) already flags this; the header itself is the drift source and is worth a cleanup PR.

## 8. Link Expansion end-to-end: flow, target, benefit, example

**Target:** recover structurally connected evidence that flat vector search ranks poorly or misses, as one bounded candidate arm — not a GraphRAG answer pipeline, not a query-entity graph walk.

**Flow:**

1. Recall embeds the query; semantic + BM25 run in one combined SQL.
2. Up to 20 semantic candidates above `graph_seed_min_similarity` (default 0.3) become graph seeds (a stricter semantic floor triggers the retriever's own seed query so entry points are not silently lost).
3. From the unchanged seed set, one CTE query expands: shared entities (via `unit_entities`), semantic links (bidirectional), causal links (outgoing).
4. Python dedups by unit id, computes the additive activation, sorts, cuts to budget; tag filters apply after the cut.
5. The graph list joins semantic, BM25, and (if a time window exists) temporal lists in RRF/interleave fusion → optional cross-encoder rerank → recency/temporal/proof boosts → token-budget packing. Graph rank 1 guarantees neither final rank 1 nor inclusion.

**Benefit:** it gives a second, *structural* retrieval route into the same bank. A fact that shares an entity or an edge with a seed can enter the fused pool even when its query-vector similarity is weak — recall (finding it at all) improves even if the cross-encoder later demotes it. It also costs one extra SQL roundtrip per fact type, which is why it stays one pass.

**End-to-end example** (illustrative, same setup as the flow doc §4): retain three facts — A "Alice builds REST APIs with Python at TechCorp", B "Bob trains fraud-detection models with Python at DataSoft", C "Alice and Bob co-lead Project Orion for TechCorp". Retain builds `unit_entities` A→{Alice, Python, TechCorp}, B→{Bob, Python, DataSoft}, C→{Alice, Bob, Orion, TechCorp}, plus a retain-time ANN edge A–C with weight 0.82. Query: "What machine-learning work is connected to Alice through tools she uses?" Suppose only A clears the 0.3 seed floor, so {A} is the seed set:

| Candidate | Signals found | Score |
|---|---|---|
| C | shares Alice + TechCorp (entity), 0.82 semantic edge | tanh(2×0.5) + 0.82 ≈ **1.582** |
| B | shares Python only (entity) | tanh(1×0.5) ≈ **0.462** |

Graph arm returns `[C, B]`. The key moment is B: its text has weak query-vector similarity (fraud-detection vs "Alice's tools"), so semantic/BM25 rank it low or miss it — but the stored `Python` topology routes it into the fused pool, where RRF + reranking then decide. That rescue of structurally-obvious-but-semantically-distant facts is the whole point of the arm. Verified mechanics: `tests/test_link_expansion_scoring.py` (3 passed) exercises these formulas.

## 9. Line 129: what does Oracle's temporal arm actually return?

Oracle's temporal arm returns **only the temporal entry points** — the in-window, similarity-gated, coverage-spread starting units — and never spreads. Both backends share the entry-point stage (`retrieval.py:538-660`): per fact type, fetch a pool of up to 60 similarity-ranked in-window candidates (`_TEMPORAL_POOL_SIZE`), then narrow to ≤10 entry points spread across 8 time buckets (`_TEMPORAL_ENTRY_POINTS`, `_TEMPORAL_COVERAGE_BUCKETS`), each returned as a full result with `temporal_score`/`temporal_proximity` computed from its position inside the window.

Postgres then runs the bounded multi-hop loop: frontier initialized from the entry points, following outgoing `temporal`/`causal` edges, 20 nodes per batch, 10 neighbors per source, ≤5 iterations, budget-bounded, re-enqueueing only neighbors with combined score > 0.2 (`retrieval.py:663-790`).

Oracle skips that loop entirely: `supports_unnest = getattr(conn, "backend_type", "postgresql") != "oracle"` (`retrieval.py:693`) — the spreading query is built on `FROM unnest($2::uuid[]) CROSS JOIN LATERAL`, which has no Oracle translation, so the `while` loop never executes and the entry points are the whole result. The code comment states the tradeoff explicitly: semantic/keyword/graph arms cover the rest, so Oracle degrades gracefully rather than erroring.

Note the distinction with the `fetch_temporal_neighbors` methods in `ops_oracle.py:506` / `ops_postgresql.py:721`: those are **retain-time** helpers that find dated neighbors when *constructing* temporal links (Oracle runs per-unit backward/forward queries). Oracle can therefore store temporal links even though its recall never traverses them iteratively.

## Verification Appendix

What was actually run on `dev@278cde1` (worktree `hindsight2`):

- `uv run pytest tests/test_link_expansion_scoring.py` → **3 passed** (exercises the tanh/max/additive-activation formulas of Q7).
- `uv run pytest tests/test_recall_time_range_graph.py tests/test_observation_expansion_scoring.py` → 3 passed (observation expansion), 5 errors in `test_recall_time_range_graph.py`. The errors are an **environment mismatch, not a code failure**: the local test database at `127.0.0.1:5556` has a 1024-dim `vector` column (created under a different embedding model), while the local provider `BAAI/bge-small-en-v1.5` emits 384 dims (`asyncpg DataError: expected 1024 dimensions, not 384`). Not repaired here — fixing it means altering the local test DB schema.
- All `file:line` citations above were read directly in source; Codex's independently-derived numbers (entity-resolution weights 0.5/0.3/0.2, threshold 0.6; temporal pool 60/10/8) were spot-checked against `entity_resolver.py:1177-1210` and `retrieval.py:408-410` before being included.

Answer provenance: host (direct code reading + test runs) and g-c consultant (read-only Codex consult, session `01a040e6`) produced independent answers to all nine questions; they agreed on every substantive point, and the merged doc above is the result.
