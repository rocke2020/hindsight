# Hindsight Graph Retrieval Q&A

## Overview

This document answers the main implementation questions raised by [Hindsight Graph Retrieval: Retain-Time Links to Recall-Time Evidence](graph-retrieval-flow.md). The answers follow the current `dev@ef1179c65` executable paths: retain-time graph construction, semantic seed selection, one-pass Link Expansion, PostgreSQL temporal spreading, and downstream fusion and scoring.

The central distinction is simple: Link Expansion is a semantic-seeded, one-pass candidate retriever over entity, semantic, and outgoing causal connections; it is not a general graph walk or answer generator. Causal links are also consumed separately by PostgreSQL temporal spreading when recall has a time window.

Scope: static source analysis of the built-in PostgreSQL and Oracle stores. Examples use concrete IDs and values for explanation, but they are not captured live LLM, embedding, database, latency, or answer-quality evidence.

## Terminology

- **Fact type**: The retrieval category of a memory unit. The complete recall set is `world`, `experience`, and `observation`.
- **Graph seed**: A semantically matched memory unit used as a fixed Link Expansion starting point.
- **Posting table**: A junction table representing membership as rows; `unit_entities(unit_id, entity_id)` records which facts mention which canonical entities.
- **Activation**: The graph arm's internal additive score across entity, semantic, and causal evidence.
- **Entry point**: An in-window, similarity-gated memory unit that starts the temporal arm.
- **Frontier**: The worklist used by PostgreSQL temporal spreading; Link Expansion has no mutable frontier.

## 1. Which fact types participate in recall?

Recall accepts exactly three fact types:

| Fact type | Meaning | Producer |
|---|---|---|
| `world` | Objective or external facts, including user preferences, rules, corrections, constraints, people, and events | Retain-time extraction |
| `experience` | Actions, experiences, discoveries, or observations the assistant or agent actually performed | Retain-time extraction; the extractor's internal `assistant` label is persisted as `experience` |
| `observation` | Consolidated knowledge synthesized from supporting facts | Consolidation |

Mental models are separate objects, not another recall fact type. Semantic-link construction and Link Expansion stay within one fact type per call; a semantic graph edge is not created across `world`, `experience`, and `observation` categories.

## 2. Is the graph only used for causal analysis?

No. The graph recall arm combines three independent structural signals:

1. Shared canonical entities through `unit_entities`.
2. Retain-time semantic-neighbor rows in `memory_links`.
3. Explicit causal rows in `memory_links`.

PostgreSQL temporal retrieval is a separate fourth recall arm that can also traverse temporal and causal links when a time window exists. Therefore causal evidence is one graph signal and one temporal-spreading input; it is not the entire graph and not a separate fifth arm.

`entity_cooccurrences` does not drive entity recall. It is derived statistics used by entity resolution and graph-related views; Link Expansion reads `unit_entities` directly.

## 3. How is an ordinary causal link created, and which way does it point?

Ordinary LLM-based retain emits only `caused_by`, and each reference must point to an earlier fact in the same extraction group. Both endpoints are columns of the shared `memory_links` table (alongside `link_type`, `weight`, and an optional `entity_id`); temporal, semantic, and causal edges all live in that one table and are distinguished by `link_type`.

The endpoint mapping is fixed by the writer. The fact that carries the reference becomes `from_unit_id`; the referenced target becomes `to_unit_id`:

```text
Fact 0: Maya lost her job.              -> MU_JOB
Fact 1: Maya could not pay rent.        -> MU_RENT
        causal_relations=[{target_index: 0, relation_type: caused_by}]

Stored row (memory_links):
from_unit_id = MU_RENT   (fact 1, the effect, carries causal_relations)
to_unit_id   = MU_JOB    (target_index 0, the cause being referenced)
link_type    = caused_by
weight       = 1.0
```

Equivalently: `from_unit_id` is the effect, `to_unit_id` is the cause, so the edge reads `MU_RENT --caused_by, weight 1.0--> MU_JOB`. The mnemonic is "from = the fact holding the reference; to = the fact it points at". One fact can hold both roles across different edges: it is `from_unit_id` for the cause it cites, and `to_unit_id` for a later effect that cites it.

Link Expansion follows causal rows only from a seed's `from_unit_id` to `to_unit_id`. An effect seed `MU_RENT` can therefore retrieve its cause `MU_JOB`; a cause seed `MU_JOB` does not retrieve `MU_RENT` through that same row. Entity or semantic expansion may still connect them independently.

Transfer import can restore historical `causes`, `enables`, and `prevents` rows. Normal retain does not create those types, but Link Expansion and PostgreSQL temporal spreading continue to read all four causal types.

## 4. Can ordinary causal extraction connect facts from different chunks?

No. Causal references are fact indices local to one extraction group. Separate chunks are extracted independently, so a fact in one group cannot name a fact index from another group and ordinary retain cannot materialize a direct causal edge between them.

The default retain chunk limit is 3000 characters, not tokens. Plain text prefers structural boundaries such as paragraphs and sentences; structured conversations and JSONL prefer complete turn or line boundaries while those units fit the configured structured limit. An oversized split can therefore weaken causal continuity even when all text is retained.

A larger recall budget cannot reconstruct an edge that extraction never created. If cross-boundary continuity matters, it must be addressed at retain/extraction design rather than hidden behind deeper graph traversal.

## 5. What are `entities`, `unit_entities`, and `entity_cooccurrences`?

They serve different roles:

- `entities` is the bank's canonical entity registry: one row per resolved entity identity.
- `unit_entities` is the many-to-many membership table between memory units and canonical entities; it is the entity-recall source of truth.
- `entity_cooccurrences` is derived pairwise statistics used to help future entity resolution and graph views; it is not traversed by Link Expansion.

Assume two facts resolve both “Python” mentions to the same canonical entity:

```text
memory_units:
  MU_A = Alice builds REST APIs with Python.
  MU_B = Bob trains fraud models with Python.

entities:
  E_ALICE, E_BOB, E_PYTHON

unit_entities:
  MU_A -> E_ALICE
  MU_A -> E_PYTHON
  MU_B -> E_BOB
  MU_B -> E_PYTHON
```

Starting from seed `MU_A`, entity expansion follows `MU_A -> E_PYTHON -> MU_B`. The `E_PYTHON` registry row alone cannot establish that the two facts share Python; the two posting rows do.

Canonical resolution attempts to reuse an existing entity based on compatible names plus contextual signals such as co-occurrence and time. It is probabilistic matching, not a guarantee that every spelling variant merges correctly, so false splits and false merges directly change the recall topology.

## 6. What is a semantic graph link, and why is it read in both directions?

A semantic link is a directed row `(from_unit_id, to_unit_id, link_type='semantic', weight)` whose weight is the clamped cosine similarity measured during link construction. The streaming retain path creates these rows in a post-commit, best-effort ANN pass using same-bank, same-fact-type neighbors, up to 20 per seed, at the default `0.7` similarity floor.

Stored direction reflects which unit initiated indexing, not a directional meaning relationship. Recall therefore checks both sides:

```text
stored: MU_A --semantic, 0.82--> MU_C

seed MU_A: outgoing lookup returns MU_C with semantic score 0.82
seed MU_C: incoming lookup returns MU_A with semantic score 0.82
```

When several seeds connect to the same candidate, Link Expansion keeps `MAX(weight)`, not the sum. A failed final ANN pass leaves vector semantic recall usable but makes semantic graph expansion incomplete until relinking, reprocessing, or repair supplies the missing rows.

## 7. How are graph seeds selected?

Each requested fact type gets at most 20 semantic seeds at the default graph seed floor `0.3`. Link Expansion does not extract entity names from the query; the query embedding selects memory-unit entry points.

The combined semantic/BM25 query normally fetches enough semantic candidates for both the semantic arm and graph seeding. That shared pool is reusable when the semantic result floor is less than or equal to the graph seed floor.

If the request makes the semantic floor stricter than the graph seed floor, the shared pool may omit valid graph seeds. `LinkExpansionRetriever` then runs its own ANN seed query at the graph floor. A `None` seed list requests this fallback; an explicitly empty compatible list means the shared query found no seeds and must not trigger a duplicate query.

No seed means no graph-arm result for that fact type.

## 8. Is Link Expansion really one pass rather than multi-hop?

Yes. For each fact type, Link Expansion runs one combined database query over the fixed seed IDs:

1. Entity expansion self-joins `unit_entities` through the seeds' canonical entities.
2. Semantic expansion reads both outgoing and incoming semantic links.
3. Causal expansion reads outgoing causal links.
4. Python merges and ranks those rows.

Discovered candidates never become a second seed frontier. The main bounds are 20 seeds per fact type, 200 candidates per entity by default, one budget limit per signal query, and a final graph-result cut to the same recall budget.

This is different from PostgreSQL temporal spreading. When a time window exists, the temporal arm starts from up to 10 entry points selected from a 60-candidate in-window semantic pool distributed across 8 time buckets, then can process a mutable frontier in batches of 20, with 10 neighbors per source and at most 5 iterations.

## 9. How does temporal retrieval use causal links?

PostgreSQL temporal spreading reads outgoing `temporal`, `causes`, `caused_by`, `enables`, and `prevents` links. Every target must still pass fact-type, semantic-similarity, tag, and update-time filters before it is admitted.

Propagation uses the parent temporal score, stored link weight, a causal multiplier, and a common `0.7` decay:

```text
causes / caused_by: multiplier 2.0
enables / prevents: multiplier 1.5
temporal:           multiplier 1.0

propagated_temporal = parent_temporal_score * link_weight * multiplier * 0.7
```

A candidate whose combined temporal score exceeds `0.2` can enter the next frontier, so this arm can follow a causal chain beyond one edge. It remains bounded by the temporal recall budget, frontier batch size, per-source neighbor limit, and iteration cap.

This traversal does not make Link Expansion multi-hop; the two arms can return some of the same facts for different reasons and RRF can reward that agreement.

## 10. How is graph activation calculated, and is it the final score?

Link Expansion deduplicates candidates by memory-unit ID and combines the strongest contribution from each graph signal:

```text
entity_score   = tanh(distinct_shared_entity_count * 0.5)
semantic_score = max(semantic_link_weight), or 0
causal_score   = max(causal_link_weight), or 0

activation = entity_score + semantic_score + causal_score
```

The entity transform gives approximately `0.462`, `0.762`, `0.905`, and `0.964` for one through four shared entities. Semantic and causal signals each contribute up to `1.0`, so activation approaches `3.0` when the signals converge.

Activation is not the final recall score. It orders only the graph arm. RRF normally consumes graph rank using `1 / (60 + rank)` and combines it with semantic, BM25, and optional temporal ranks; it never compares raw graph activation directly with vector similarity or BM25 scores.

After fusion, candidates may be trimmed, hydrated, cross-encoder reranked, adjusted for recency, temporal proximity, proof count, and configured strategy priority, filtered by minimum scores, and cut by result and token budgets. A graph rank of 1 guarantees neither final rank 1 nor inclusion.

Interleave is the exception to normal downstream scoring: it round-robins the arm lists, skips the cross-encoder and combined recency/temporal/proof scoring, and preserves interleave order through budget and token selection.

## 11. How are observation graph candidates found?

Observations inherit entity evidence from the facts that support them rather than relying on direct observation-to-entity postings. Their entity path is:

```text
seed observation -> source facts -> source entities -> connected source facts
                 -> observations supported by those connected facts
```

Semantic and causal observation expansion still reads `memory_links` directly between observation units. Each backend combines observation entity, semantic, and causal expansion into one database fetch and returns the same three signal groups to the Python activation merge.

PostgreSQL stores observation provenance in the `source_memory_ids` array on `memory_units`; Oracle uses the `observation_sources` junction table. The storage shape differs, but the logical entity path above is the same.

## 12. What differs between PostgreSQL and Oracle?

PostgreSQL is the default built-in backend; Oracle 23ai is optional. Both implement semantic-seeded Link Expansion, including shared-entity expansion, bidirectional semantic-link reads, outgoing causal-link reads, and one fused observation expansion fetch.

The material differences in this flow are:

| Area | PostgreSQL | Oracle |
|---|---|---|
| Ordinary Link Expansion | Combined entity + semantic + causal query with a 10-second entity-timeout fallback | Combined entity + semantic + causal query; no matching timeout fallback |
| Observation provenance | `memory_units.source_memory_ids` array | `observation_sources` junction table |
| Temporal entry points | Similarity-gated, time-windowed entry points | Same logical entry-point selection |
| Temporal spreading | Runs the bounded `unnest`/lateral frontier loop | Skips spreading and returns entry points only |

Oracle can still construct and store temporal links at retain time. What it lacks in this path is iterative recall-time traversal of those links.

## 13. How does the graph path degrade when data or queries are incomplete?

The failure modes are scoped rather than all-or-nothing:

- Missing causal extraction means no causal edge; other recall arms can still find the facts.
- A chunk or extraction-group boundary can prevent a causal relation from being created.
- A failed post-commit ANN pass weakens semantic graph expansion but does not remove retained facts or direct vector recall.
- Entity-resolution errors change shared-entity neighborhoods.
- Non-observation Link Expansion timeout drops entity expansion for that attempt and keeps semantic plus causal expansion.
- Observation expansion has no equivalent timeout fallback.
- Expanded candidates are cut to budget before final tag filtering, so rejected candidates are not backfilled.
- Causal traversal direction can make an edge reachable from the effect but not the cause.
- Fusion, reranking, score filters, and token packing can remove a graph candidate after retrieval.

The main defaults are a `0.3` graph seed floor, 20 seeds per fact type, a `0.7` semantic-link floor, 200 candidates per entity, a 10-second non-observation timeout, fixed low/mid/high thinking budgets of `100/300/1000`, a disabled per-arm candidate cap (`0`), and an effective reranker candidate cap of 300 unless a per-budget override is configured.

## 14. Is this a standalone GraphRAG pipeline, and which code is authoritative?

No. Hindsight uses graph structure to expand recall candidates, but this path does not parse query entities, perform arbitrary graph walks, build community summaries, or generate an answer. The accurate implementation name is **graph retrieval with Link Expansion**.

The executable query builders and Python merge are authoritative when nearby comments disagree. In the current source, the module header of `engine/search/link_expansion_retrieval.py` still says all three signals are stored in `memory_links` and describes causal score as `weight + 1.0`; the implementation instead reads entity membership from `unit_entities` and uses raw causal weight. Those header statements are stale and must not be used to interpret runtime behavior.

Source paths are relative to `hindsight-api-slim/hindsight_api/`:

- Fact types and causal extraction: `engine/response_models.py`, `engine/retain/fact_extraction.py`, `engine/causal_links.py`.
- Entity resolution and postings: `engine/entity_resolver.py`, `engine/retain/link_utils.py`, `engine/retain/orchestrator.py`.
- Recall orchestration and temporal spreading: `engine/memories/postgres.py`, `engine/search/retrieval.py`.
- Link Expansion and SQL: `engine/search/link_expansion_retrieval.py`, `engine/db/ops_postgresql.py`, `engine/db/ops_oracle.py`.
- Fusion and final scoring: `engine/search/fusion.py`, `engine/search/recall_boost.py`, `engine/search/reranking.py`, `engine/memory_engine.py`.

This Q&A documents current source semantics. Live extraction quality, embedding similarity, query plans, latency, recall quality, and final answer quality require separate runtime or benchmark evidence.
