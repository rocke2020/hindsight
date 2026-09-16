# Graph Seed Reuse Gate

## Overview

1. The current reuse gate is a good conservative design: it reuses the combined semantic query only when that query's score floor is broad enough to cover every eligible graph seed, and otherwise preserves `LinkExpansionRetriever`'s dedicated seed query.
2. The design has one small efficiency weakness: when a stricter semantic query has already returned 20 ordered candidates, those candidates already fill the graph seed limit, but the current code still runs a second semantic seed query at the lower graph floor.
3. The recommended refinement is a post-query completeness check: retain the existing floor-based gate, additionally reuse any stricter-floor pool containing at least 20 candidates, and keep the existing fallback for pools containing fewer than 20. This does not require increasing `semantic_fetch`.

## 1. Terms and Invariants

The **semantic floor** is the minimum similarity accepted by the ordinary semantic recall arm. A request-level `min_scores.semantic` overrides the configured default for that request.

The **graph seed floor** is the independent minimum similarity used to select entry points for Link Expansion. Link Expansion accepts at most `GRAPH_SEED_LIMIT = 20` seeds per fact type.

The **shared semantic pool** is the ordered semantic result set produced by the combined semantic/BM25 query. It can serve both the semantic recall arm and graph seeding when it contains enough eligible candidates.

A shared pool is **complete for graph seeding** when it is sufficient to determine the graph arm's entire top-20 seed set. Completeness can be proven in either of two ways:

1. The semantic floor is less than or equal to the graph seed floor, so the shared query covers the complete graph-eligible score range and can be filtered at the graph floor.
2. The semantic floor is stricter than the graph seed floor, but the ordered shared pool already contains at least 20 candidates. Because all 20 clear the stricter floor, lowering the floor can add only lower-ranked candidates and cannot displace them from the graph top 20.

Both proofs assume the same bank, fact type, tags, tag groups, time bounds, query embedding, and similarity ordering. The current PostgreSQL shared and dedicated seed paths carry these same filters.

## 2. Current Conservative Design

The combined semantic/BM25 query decides before execution whether its semantic results are reusable as graph seeds. When `semantic_floor <= graph_seed_floor`, it fetches at least 20 semantic rows, filters them at the graph floor, and passes up to 20 candidates to `LinkExpansionRetriever`.

When `semantic_floor > graph_seed_floor`, the current code marks the shared graph seed pool as `None` regardless of how many semantic candidates the query later returns. `PostgresMemories.recall_unified` passes that value to `LinkExpansionRetriever`, which interprets `None` as a request to run its dedicated semantic seed query at the graph floor.

An explicitly empty list has a different meaning. It says that a compatible shared query covered the graph floor but found no graph seeds, so `LinkExpansionRetriever` does not issue a duplicate seed query. This `None` versus empty-list contract is simple and preserves correctness.

The current gate is good because it never mistakes a threshold-truncated pool for a complete graph seed set. For example, if the semantic floor is `0.6`, the graph floor is `0.3`, and the shared query returns only 12 candidates, candidates scoring from `0.3` through `0.6` may still fill the remaining eight graph seed positions. The dedicated graph-floor query is therefore necessary.

The reason for that fallback is pool completeness: the stricter threshold may omit eligible candidates, and the shared query's fetch budget may expose fewer than the graph seed limit. HNSW approximation does not justify rerunning the query after a stricter-floor pool has already filled all 20 seed positions.

## 3. Small Weakness: A Redundant Query for a Full Pool

The current pre-query gate cannot use result cardinality because it runs before the database returns the shared semantic pool. Consequently, it also falls back when the stricter-floor query returns 20 or more ordered candidates.

Consider a request semantic floor of `0.6`, a graph seed floor of `0.3`, and at least 20 shared results:

```text
shared semantic pool: S1 ... S20, each similarity >= 0.6
graph seed capacity:  20
dedicated seed range: similarity >= 0.3
```

`S1 ... S20` already occupy every graph seed position. A second query at `0.3` can discover additional candidates, but each new candidate ranks below the 20 already returned and cannot enter the bounded seed set. The second ANN query therefore adds latency and database work without changing the seed set needed by the graph arm.

This is a small performance weakness rather than a correctness bug. Requests with fewer than 20 stricter-floor matches still need the fallback, and ordinary requests whose semantic and graph floors are compatible already reuse the shared pool.

## 4. Recommended Minimal Refinement

Keep the existing pre-query floor gate because it proves reuse before results exist and ensures that compatible queries fetch at least 20 rows. Add one result-based proof after semantic candidates have been grouped:

```python
if graph_seed_threshold is not None:
    # Existing path: the shared query covered the graph floor.
    graph_seeds = candidates_at_or_above_graph_floor[:GRAPH_SEED_LIMIT]
elif len(candidates) >= GRAPH_SEED_LIMIT:
    # New path: a stricter-floor pool already fills every seed position.
    graph_seeds = candidates[:GRAPH_SEED_LIMIT]
else:
    # The lower graph floor may supply missing seeds.
    graph_seeds = None
```

Do not increase `semantic_fetch` for the new branch. In the stricter-floor path, `semantic_fetch` already equals the caller's recall `limit`. If that existing query returns at least 20 candidates, the new proof applies. If its limit or result count is below 20, the proof does not apply and the existing dedicated query remains responsible for finding the complete graph seed set.

The default fixed recall limits are already 100, 300, and 1,000 for low, mid, and high budgets, while the adaptive default has a minimum of 20. Therefore, the normal fetch capacity already permits the post-query proof; whether a particular request actually has 20 matches above a strict floor is data-dependent and should not be assumed rare without runtime measurements.

This refinement preserves the `None` versus empty-list contract, changes no graph expansion semantics, adds no configuration, and does not broaden the shared query solely for this optimization.

## 5. Acceptance Criteria

The refinement is correct only if all of the following fail-capable cases pass:

1. With `semantic_floor > graph_seed_floor` and at least 20 ordered shared candidates, the first 20 are passed to `LinkExpansionRetriever`, its dedicated `_find_semantic_seeds` query is not called, and graph expansion still runs.
2. With `semantic_floor > graph_seed_floor` and 19 shared candidates, `graph_seeds` remains `None` and the dedicated graph-floor seed query runs.
3. With `semantic_floor <= graph_seed_floor`, existing filtering and reuse behavior remains unchanged, including fetching enough rows for the 20-seed cap when the recall limit is smaller.
4. A compatible query that finds zero seeds passes an empty list and does not trigger a duplicate query.
5. Bank, fact type, tag, tag-group, and time-window isolation remain identical between shared and fallback selection.

These cases require focused unit tests for the reuse decision and one retrieval-path test proving whether `_find_semantic_seeds` is called. They do not require a new configuration flag or a broader recovery mechanism.

## 6. Authoritative Source Map

- `hindsight-api-slim/hindsight_api/engine/search/retrieval.py`: `GRAPH_SEED_LIMIT` consumption, `semantic_fetch`, the floor-based reuse gate, and construction of `graph_seeds`.
- `hindsight-api-slim/hindsight_api/engine/search/link_expansion_retrieval.py`: `GRAPH_SEED_LIMIT`, `_find_semantic_seeds`, and the `None` fallback behavior in `LinkExpansionRetriever.retrieve`.
- `hindsight-api-slim/hindsight_api/engine/memories/postgres.py`: propagation of the shared seed pool into the graph retriever.
- `hindsight-api-slim/hindsight_api/engine/memory_engine.py`: resolution and propagation of `thinking_budget` as the retrieval limit.
- `hindsight-api-slim/hindsight_api/config.py`: fixed and adaptive recall budget defaults.
- `hindsight-api-slim/tests/test_multilingual_bm25.py`: shared-pool reuse and stricter-floor fallback unit coverage.
- `hindsight-api-slim/tests/test_hnsw_indexes.py`: retrieval-path coverage for the presence or absence of the dedicated seed query.
