# Temporal First-Discovery Policy and Latency

## Overview

1. The current PostgreSQL temporal arm uses a `visited` set to admit each memory once and expand it at most once per fact type. This bounds repeated work when several edges or paths reach the same memory.
2. The same check also fixes a newly discovered memory's score on its first encounter: later paths cannot improve the score or reconsider whether that memory should continue expanding. Avoiding repeated expansion and accepting the first score are distinct decisions, although the current implementation couples them.
3. Deduplication runs after the neighbor query returns. It skips Python processing and prevents duplicate frontier entries, but does not eliminate the current batch's SQL work or transfer of duplicate target rows.
4. First discovery can reduce later exploration when the first score falls below the continuation threshold. That also changes which paths are explored; it does not establish lower latency at equivalent retrieval coverage.
5. The source supports these work-count conclusions, but does not establish the size of an end-to-end latency improvement or the maintainers' motivation. A significant latency benefit from permanently accepting the first score remains unverified.

Scope: analysis of the built-in PostgreSQL temporal recall implementation at `d5c912748c761ed3d7c95e7b81a17364d3087674`. This document explains current behavior and its costs. It contains no database, latency, or recall-quality experiment results.

Related context: [Temporal Retrieval Flow](./temproral-retrieval-flow.md). The intent and ordering question is recorded in [upstream issue #4536](https://github.com/vectorize-io/hindsight/issues/4536).

## Terms

| Term | Meaning in this document |
|---|---|
| Entry memory | A memory selected using the requested date window and query semantic similarity, from which temporal spreading starts. |
| Source node | A memory whose outgoing edges are being queried in the current batch. It can be an entry memory or a previously discovered candidate. |
| Frontier | The ordered list of source nodes waiting to be expanded. |
| Returned edge row | One neighbor-query result carrying a source ID, target memory, edge type, and stored weight. Different rows can point to the same target. |
| First discovery | The first returned row processed for a target not already in `visited`. This refers to processing order, not event or ingestion time. |
| Propagated score | Strength inherited from the parent through the current edge, stored locally as `propagated_temporal`. Temporal and causal edges both use this calculation. |
| Combined score | `max(target_date_proximity, propagated_temporal)`, assigned to the candidate's `temporal_score` and used to decide continuation. |

## 1. What the Current Loop Does

The loop fetches a batch of neighbors before making any first-discovery decision. Each new target is admitted before its continuation threshold is checked.

1. Select entry memories, add their IDs to `visited`, and initialize their traversal strength to `1.0`. Each entry's returned score still represents its own date proximity.
2. Take up to 20 source IDs from the frontier and issue one neighbor query. It selects up to 10 outgoing edges per source, across temporal and causal types, then joins and filters the target memories.
3. Await the returned list. The SQL receives no `visited` set and has no predicate excluding previously visited targets.
4. For each returned row, check the target ID. If already visited, skip the row before computing its score.
5. Otherwise, mark the target visited, consume one candidate-budget slot, calculate its score, and append one result object.
6. If the combined score is greater than `0.2` and candidate budget remains, record that score as its traversal strength and append the target to the frontier. Future expansion also requires the outer loop's iteration limit to permit another batch.

```text
Query and receive the neighbor batch
  -> For each returned edge row
       -> Already visited? Skip this row
       -> Otherwise: mark visited, consume one budget slot, score, append result
       -> Score > 0.2 and budget remains? Append target to frontier
  -> Process the next frontier batch if loop limits permit
```

A candidate rejected for continuation still remains in `visited` and in the candidate results. A later stronger path cannot reactivate it. Entry memories are already visited before spreading, so incoming edges do not rescore them either.

Authoritative paths: [entry initialization](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L624), [batch query](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L691), and [deduplication, scoring, and continuation](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L734).

## 2. Which Work Is Avoided, and Which Is Already Paid For

First-discovery deduplication saves work after a duplicate row reaches Python and prevents the target from being scheduled for duplicate expansion. The current batch's database work precedes that decision.

| Work | Effect of the current `visited` check |
|---|---|
| Reading and selecting outgoing edges for the current batch | Already performed; the Python check cannot remove this work. |
| Joining targets and applying SQL filters, including query-vector similarity | Already performed for the returned rows. The query does not exclude visited targets. |
| Transferring and decoding returned rows | Already performed before the Python loop consumes the returned list. |
| Converting a row's target ID and checking membership | Still performed for each row the loop examines, including duplicates. |
| Choosing the target's date and calculating proximity | Skipped for duplicates. |
| Selecting the relation multiplier and calculating propagation | Skipped for duplicates. |
| Constructing and appending a candidate result | Performed once per newly discovered target. |
| Scheduling the same target for expansion again | Prevented, even if a later path would produce a higher score. |

For example, five returned edges to B are five rows from one batch query, not five separate database round trips. Processing only the first B row avoids four repetitions of the Python scoring path. It does not undo the SQL and transfer work for the other four rows. B may also be returned again as a target in later batches from other source nodes, even though B itself is expanded at most once.

The duplicate path skips date arithmetic, scalar score calculations, and result-object construction. It does not skip an LLM call or a new embedding-model invocation: neither occurs inside this per-neighbor scoring block. Their absence prevents attributing model-inference savings to this check.

Source: [neighbor SQL and processing order](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L707), [database fetch wrapper](../../hindsight-api-slim/hindsight_api/engine/db/postgresql.py#L116), and [result construction](../../hindsight-api-slim/hindsight_api/engine/search/types.py#L109).

## 3. The Comparison Baseline Determines the Claimed Benefit

Avoiding repeated expansion has a clear work-count benefit, but that benefit does not by itself justify freezing the first score. The following comparison baselines distinguish the costs attributable to the current policy.

| Comparison baseline | Work the current policy avoids | What this comparison establishes |
|---|---|---|
| Every arrival scores and schedules the target again | Duplicate scoring, duplicate queue entries, and repeated outgoing-edge queries | Deduplication prevents redundant traversal through converging paths and cycles. |
| Scores from rows already returned in one batch are compared, while each target is still scheduled at most once | Additional local score calculations and comparisons | Selecting among already available rows does not inherently require another query for that batch. Later scores can still change subsequent exploration. |
| A stronger path found later updates the target and propagates the improvement through its descendants | Score revisions and possible additional propagation work | Permanently accepting the first score can avoid revisiting an already explored part of the graph. |

The current score calculation has no `await` or database call inside the row loop. Comparing more of the already returned rows would therefore add local processing, rather than necessarily adding database round trips. The source does not quantify that local cost or its share of recall latency.

Deduplication also preserves candidate budget for distinct memories: a duplicate row does not consume another slot. As a result, fewer redundant operations do not imply fewer total queries in every comparison. A traversal that incorrectly spends its budget on duplicates could stop earlier while covering fewer distinct memories.

The defensible conclusion is about bounded redundant work. Whether the first-score policy is faster at equivalent retrieval coverage requires evidence beyond these control-flow facts.

## 4. A Lower First Score Can Save Exploration by Suppressing a Path

The first score can decide whether a target's outgoing edges are ever queried. This is where score selection can change both later work and reachable candidates.

Assume A is a source node with traversal strength `0.5`; B is unvisited and has direct date proximity `0.1`. Both of the following A-to-B edges pass the filters and fit within the per-source limit. Budget and loop iterations remain after B is admitted.

```text
A --temporal,  weight=0.5--> B
A --caused_by, weight=1.0--> B
```

The current calculation is:

```text
propagated_temporal = parent_strength * stored_weight * relation_multiplier * 0.7
combined_temporal  = max(target_date_proximity, propagated_temporal)
```

Here `relation_multiplier` denotes the source variable `causal_boost`: `1.0` for temporal and `2.0` for caused_by.

| First eligible row processed | B's combined score | B admitted? | B scheduled for expansion? |
|---|---|---|---|
| `temporal` | `max(0.1, 0.5 * 0.5 * 1.0 * 0.7) = 0.175` | Yes | No |
| `caused_by` | `max(0.1, 0.5 * 1.0 * 2.0 * 0.7) = 0.7` | Yes | Yes |

In the first case, the later causal row is skipped, so B does not become a source node through this traversal. If C could only be reached by expanding B, that route to C is lost. Other paths or recall arms might still retrieve C; this example does not establish a final-answer regression.

These are alternative outcomes derived from the source formula, not observed query outputs. The inner `ORDER BY weight DESC` governs per-source edge selection, but the outer query does not specify a final processing order. Even a weight-only final order would not resolve equal-weight relations with different multipliers.

When different possible scores both exceed `0.2`, the immediate scheduling decision is the same: B is scheduled once. Its inherited strength can still affect the scores and continuation decisions of its descendants. First discovery therefore does not uniformly reduce the number of later queries; the outcome depends on the first path and the graph.

Source: [relation multipliers, combined score, and continuation](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L765).

## 5. Independent Limits Already Bound the Traversal

The current temporal arm also has explicit limits on candidate admission and expansion batches. First discovery is one cost-control mechanism among these constraints.

| Limit | Current behavior |
|---|---|
| Entry memories | At most 10 per fact type. |
| Source batch | At most 20 source IDs per expansion query. |
| Outgoing rows | At most 10 edges per source before target filtering. |
| Expansion queries | At most 5 batches per fact type, with earlier termination when the frontier empties or candidate budget is exhausted. |
| Candidate budget | Entry memories and newly admitted targets consume the fact type's budget; skipped duplicate rows do not. |
| Continuation | Only targets with combined score greater than `0.2` and remaining budget enter the frontier. |

An expansion query can return at most 200 edge rows from 20 sources with 10 selected edges each; target filters may reduce that number. This bounds returned candidates, not all database-internal work: the database still has to find the selected edges, join targets, and evaluate filters. The five-iteration cap counts processed batches, not a clean five-hop depth.

Candidate budget exhaustion can stop Python processing before all fetched rows are examined, but the batch has already been fetched. A frontier entry can also remain unexpanded when the iteration limit is reached.

Source: [entry-point limit](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L401), [batch and edge limits](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L659), and [loop termination](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L691).

## 6. Evidence Boundary and Maintainer Question

The source establishes that first discovery skips repeated Python scoring and prevents duplicate expansion. It does not establish a measured latency improvement or prove that permanently ignoring stronger paths is necessary for low latency.

Claims of significant end-to-end speedup, unchanged retrieval quality, or an intentional latency motivation remain unverified. A useful performance comparison would need to distinguish local score-processing cost, expansion-query count and duration, and the distinct memories reached; a faster traversal that explores fewer useful paths is a different trade-off from removing redundant work at equal coverage.

The maintainer question is therefore specific: is permanently accepting the first discovered path a deliberate approximation to bound work, and is the lack of a final relation-processing priority part of that intended behavior? [Issue #4536](https://github.com/vectorize-io/hindsight/issues/4536) asks this without asserting a measured performance or quality regression.
