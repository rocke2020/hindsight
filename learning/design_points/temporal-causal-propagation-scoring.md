# Monotonic Temporal-Causal Propagation Scoring

## Overview

1. Temporal-causal propagation keeps both temporal and active cause edges, gives an active cause edge an initial relation factor of `1.1`, and still decays with graph distance: the strongest full-weight causal hop retains `0.77` of its parent's traversal strength, while a full-weight temporal hop retains `0.70`.
2. Direct date evidence remains independent of graph propagation, so a memory may score highly because its own date is close to the requested window even when it is several hops away.
3. The initial `1.1` causal factor is intentionally conservative. A `1.2` factor would retain `0.84` per full-weight causal hop and keep a no-refresh chain above the `0.2` continuation threshold for about nine hops instead of six.
4. For the motivating chain `MU_MOVE --caused_by--> MU_RENT --caused_by--> MU_JOB`, when `MU_RENT` is both the direct cause and closer in date, the temporal arm must assign `MU_RENT` a higher score than `MU_JOB`.
5. This document is a proposed design, not current runtime behavior. The implementation still multiplies causal propagation by `2.0`, which can make scores grow at every hop, and the cross-fact-type temporal aggregation currently sorts on a field that `RetrievalResult` does not define.

## 1. Scope and Status

This design changes only PostgreSQL temporal spreading and temporal-arm ordering. It does not change causal extraction, stored link direction, Link Expansion graph activation, temporal-window parsing, candidate eligibility filters, Oracle behavior, fusion, reranking, database schema, or public API fields.

The current implementation initializes each entry point with propagation strength `1.0`, traverses eligible outgoing temporal and causal links, and assigns each reached candidate a `temporal_score`. PostgreSQL can continue from a candidate whose score is greater than `0.2`; Oracle currently returns entry points without this spreading traversal.

Implementation status: **proposed and not implemented**. The authoritative current paths are [`search/retrieval.py`](../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py) for temporal spreading, [`memory_engine.py`](../../hindsight-api-slim/hindsight_api/engine/memory_engine.py) for cross-fact-type aggregation and fusion input, and [`search/types.py`](../../hindsight-api-slim/hindsight_api/engine/search/types.py) for the `RetrievalResult` score fields.

## 2. Terms

The design separates a memory's own date evidence from relevance inherited through graph traversal, then combines them into one bounded temporal-arm score.

| Term | Definition |
|---|---|
| Entry point | A semantically relevant memory unit selected from the requested temporal window as a starting node for PostgreSQL temporal spreading. |
| Direct date proximity, `D(v)` | A value in `[0, 1]` derived from memory unit `v`'s own best date relative to the requested window; it does not use graph links. Existing missing-date fallbacks remain unchanged and are neutral defaults rather than observed proximity. |
| Link weight, `W(u, v)` | The stored `memory_links.weight` for an eligible edge from parent `u` to candidate `v`, constrained to `[0, 1]`. |
| Hop decay, `gamma` | The fixed multiplicative loss applied once per traversed edge. This design retains the existing value `0.7`. |
| Relation factor, `R(e)` | An internal query-time preference applied by edge type. The initial design uses `1.1` for the active cause relationship and `1.0` for temporal or legacy relationship names; it is separate from stored link weight and is not a database value. |
| Propagated score, `P(u, v)` | The relevance inherited by candidate `v` through one edge from parent `u`. |
| Temporal score, `T(v)` | The candidate's temporal-arm score: the stronger of its direct date proximity and its propagated score. |
| Hop depth | The number of traversed edges from the entry point to a candidate; entry points have depth `0`. |

## 3. Required Invariants

The design is correct only when all of these invariants hold.

1. **Bounded score:** every direct date proximity, propagated score, and temporal score stays in `[0, 1]`.
2. **Propagation decay:** for every traversed edge, `P(u, v) < traversal_strength(u)`. A graph hop never preserves or amplifies the strength it inherits from its parent; with the initial constants, the maximum retained fraction is `1.0 * 0.7 * 1.1 = 0.77`.
3. **Distance ordering:** along a descendant chain after the entry-point anchor, when nodes have equal link weights and none receives stronger direct date evidence, the shallower node has the higher temporal score.
4. **Date independence:** a deeper node may outrank a shallower node only when its own direct date evidence is stronger enough to do so; graph distance alone never creates that inversion.
5. **Controlled cause preference:** temporal and active cause edges remain eligible traversal types. The active cause relationship receives `R(e) = 1.1`; temporal edges and historical relationship names receive the neutral `R(e) = 1.0`. Every supported combination must satisfy `W(u, v) * gamma * R(e) < 1.0`.
6. **Score-to-rank closure:** the temporal arm is ordered by `temporal_score`, not insertion order or an unrelated field, before its ranks enter fusion.
7. **Deterministic ties:** equal temporal scores prefer lower hop depth, then higher query similarity, then stable memory-unit ID order.

## 4. Scoring Formula

The minimum sufficient change is to replace the amplifying causal boost with a bounded relation factor while retaining the existing stored link weight and `0.7` hop decay. Stored link weight remains in `[0, 1]`; the `1.1` cause preference is query-time scoring state rather than a persisted weight.

This design retains the current best-date precedence: use the midpoint of `occurred_start` and `occurred_end` when both exist, otherwise use `occurred_start`, then `occurred_end`, then `mentioned_at`. For a usable date and a non-zero-width requested window:

```text
D(v) = 1 - min(abs(best_date(v) - window_midpoint) / window_half_width, 1)
```

The value is `1.0` at the midpoint, decreases linearly to `0.0` at either boundary, and remains `0.0` outside the window. This proposal leaves the current no-date fallbacks unchanged: `0.5` for an entry point and `0.3` for a reached neighbor; these fallbacks express uncertainty, not measured date closeness.

For an entry point `s`:

```text
traversal_strength(s) = 1.0
temporal_score(s)     = D(s)
hop_depth(s)          = 0
```

The separate `1.0` traversal strength preserves the current ability to explore outward from every selected entry point even when the entry point lies near a window boundary. Its returned temporal score still represents its own date proximity.

For a first-seen eligible neighbor `v` reached from parent `u`:

```text
P(u, v) = traversal_strength(u) * W(u, v) * gamma * R(edge_type)
T(v)    = max(D(v), P(u, v))

where gamma = 0.7
      R(active cause) = 1.1
      R(temporal or legacy relationship name) = 1.0
```

If `v` passes the continuation threshold and enters the frontier:

```text
traversal_strength(v) = T(v)
hop_depth(v)          = hop_depth(u) + 1
```

Because `W(u, v) <= 1.0` and the largest initial combined edge factor is `1.0 * 0.7 * 1.1 = 0.77`, propagation strictly decreases the inherited score. A strong direct date proximity may refresh `T(v)` before the next hop, but that increase is attributable to the candidate's own date rather than graph traversal.

Link type continues to determine whether an edge is eligible. The stored weight remains the source of truth for link-specific strength, while the single internal `1.1` factor expresses only a modest preference for the active cause relationship. Historical names such as `enables` and `prevents` receive no dedicated preference; if compatibility code reads them, they use the neutral factor `1.0`. The factors are named internal constants, not public configuration.

## 5. Candidate Admission, Continuation, and Ordering

Admission, continuation, and ordering are separate decisions and must not share an ambiguous threshold meaning.

1. **Eligibility:** retain the current bank, fact-type, embedding, semantic-floor, tag, created-time, link-type, minimum-link-weight, per-source-neighbor, visited-node, iteration, and budget filters.
2. **Admission:** a first-seen eligible neighbor is appended to the temporal candidate list after its score is calculated. The continuation threshold does not retroactively reject that candidate.
3. **Continuation:** append the candidate to the next frontier only when budget remains and `T(v) > 0.2`. A score equal to `0.2` does not continue.
4. **Per-fact-type order:** sort candidates by `(-temporal_score, hop_depth, -similarity, id)` after spreading completes.
5. **Cross-fact-type order:** after concatenating fact-type results, sort by the same key before per-source capping and fusion. The implementation must read `temporal_score`; `RetrievalResult` has no `combined_score` field.
6. **Fusion boundary:** RRF consumes temporal rank, not the raw temporal score. The score determines the temporal list's order and traversal continuation but is not added to graph activation or another arm's raw score.

Traversal strength remains in the frontier's internal node-state map. Hop depth travels with a temporal candidate as an optional internal `temporal_hop_depth` field on `RetrievalResult` so cross-fact-type aggregation can apply the same tie-break; `ScoredResult.to_dict()` must continue to omit it from the public recall response. Neither value requires a database column.

## 6. Worked Example

This example proves the intended ordering when the immediate cause is also temporally closer. The facts and dates are illustrative design inputs, not captured runtime output.

Assume the requested window is January 1 through February 10. Its midpoint is January 21 and its half-width is 20 days. Assume semantic entry-point selection chooses only `MU_MOVE`; `MU_RENT` and `MU_JOB` are first discovered through causal traversal.

| Memory unit | Fact | Best date | Distance from midpoint | Direct date proximity |
|---|---|---:|---:|---:|
| `MU_MOVE` | Maya moved to a cheaper apartment. | February 1 | 11 days | `1 - 11 / 20 = 0.45` |
| `MU_RENT` | Maya could not pay rent. | January 20 | 1 day | `1 - 1 / 20 = 0.95` |
| `MU_JOB` | Maya lost her job. | January 2 | 19 days | `1 - 19 / 20 = 0.05` |

The stored causal rows point from each effect to its earlier cause:

```text
MU_MOVE --caused_by, weight=1.0--> MU_RENT
MU_RENT --caused_by, weight=1.0--> MU_JOB
```

`MU_MOVE` starts traversal with strength `1.0`. Its returned temporal score remains its own direct date proximity, `0.45`.

The first hop calculates `MU_RENT`:

```text
propagated(MU_RENT) = 1.0 * 1.0 * 0.7 * 1.1 = 0.77
temporal(MU_RENT)   = max(0.95, 0.77) = 0.95
hop_depth           = 1
```

Because `0.95 > 0.2`, `MU_RENT` enters the next frontier with traversal strength `0.95`. The second hop calculates `MU_JOB`:

```text
propagated(MU_JOB) = 0.95 * 1.0 * 0.7 * 1.1 = 0.7315
temporal(MU_JOB)   = max(0.05, 0.7315) = 0.7315
hop_depth          = 2
```

The temporal-arm ordering is therefore:

```text
MU_RENT  temporal_score=0.950  hop_depth=1
MU_JOB   temporal_score=0.7315 hop_depth=2
MU_MOVE  temporal_score=0.450  hop_depth=0
```

The required comparison holds: `MU_RENT > MU_JOB` because `MU_RENT` is both the direct cause of `MU_MOVE` and closer to the requested window midpoint. `MU_RENT` may also outrank the entry point because its own date evidence is stronger; this is allowed by the date-independence invariant.

Without direct date refresh, the same full-weight chain decays strictly by hop:

```text
entry traversal strength = 1.000000
depth 1 propagation      = 0.770000
depth 2 propagation      = 0.592900
depth 3 propagation      = 0.456533
```

### 6.1 Why the Initial Cause Factor Is `1.1`, Not `1.2`

The relation factor compounds at every hop, so the difference between `1.1` and `1.2` is much larger across a chain than it appears at one edge. For a full-weight chain with no stronger direct date evidence, depth `n` has propagated score `(0.7 * R)^n`.

| Relationship design | Effective full-weight hop factor | Depth 1 | Depth 3 | Depth 5 | Last depth strictly above `0.2` |
|---|---:|---:|---:|---:|---:|
| Temporal, `R = 1.0` | `0.70` | `0.700` | `0.343` | `0.168` | 4 |
| Initial cause factor, `R = 1.1` | `0.77` | `0.770` | `0.457` | `0.271` | 6 |
| Alternative cause factor, `R = 1.2` | `0.84` | `0.840` | `0.593` | `0.418` | 9 |

The initial design selects `1.1`: it makes a causal hop ten percent stronger than an otherwise identical temporal hop, yet the continuation threshold still prunes a full-weight, no-refresh causal chain after depth 6. The `1.2` alternative remains bounded, but at depth 5 it preserves `0.418` instead of `0.271` and continues for roughly three additional hops. Adopting `1.2` therefore requires retrieval-quality and traversal-cost evidence showing that useful causal evidence is being lost around depths 7 through 9.

## 7. Current Implementation Gap

The current PostgreSQL calculation selects a runtime multiplier of `2.0` for the active cause relationship and retains compatibility handling for historical relationship names, then multiplies by the common `0.7` factor. A full-weight causal hop therefore has a net multiplier of `1.4`:

```text
current depth 1 = 1.0 * 1.0 * 2.0 * 0.7 = 1.4
current depth 2 = 1.4 * 1.0 * 2.0 * 0.7 = 1.96
```

This violates bounded score, propagation decay, and distance ordering. The value behaves like amplifying traversal energy rather than relevance, but it is stored and traced as `temporal_score`, so the distinction is not safely contained.

The current cross-fact-type aggregation sorts temporal results by `combined_score` when present. `RetrievalResult` defines `temporal_score` and `temporal_proximity`, not `combined_score`, so every temporal result currently receives the same fallback sort key and retains concatenation order. Implementing the new formula without closing this ordering path would not guarantee the intended temporal rank at fusion.

## 8. Implementation Plan

This is the smallest implementation that realizes the design.

1. Introduce named internal constants for the existing `0.7` hop decay, the initial `1.1` active-cause factor, and the neutral `1.0` factor; do not add public configuration.
2. Replace the runtime `2.0` active-cause multiplier with `1.1`. Do not introduce tuned factors for historical relationship names; compatibility reads use the neutral `1.0` factor.
3. Track transient hop depth alongside traversal strength for each frontier node and carry it through aggregation as internal `RetrievalResult.temporal_hop_depth`; keep it out of `ScoredResult.to_dict()`.
4. Calculate every neighbor's propagated and temporal scores with the formula in Section 4 and retain the existing `> 0.2` continuation rule.
5. Sort per-fact-type and cross-fact-type temporal results by `temporal_score` with the deterministic tie-breaks in Section 5.
6. Keep fusion, reranking, token budgeting, persistence, and response schemas unchanged.
7. Synchronize [Graph Retrieval Flow](./graph-retrieval-flow.md) and [Hindsight Temporal Retrieval Flow](./temproral-retrieval-flow.md) in the implementation change so the main flow describes runtime behavior rather than this proposal alone.

## 9. Acceptance Criteria

Implementation is complete only when fail-capable tests establish these cases.

| Case | Inputs | Required result |
|---|---|---|
| Full-weight causal chain | Entry `1.0`, two active-cause links at weight `1.0`, no stronger direct date evidence | Depth 1 is `0.77`; depth 2 is `0.5929`; depth 1 ranks first. |
| Motivating example | Direct proximity `MU_RENT=0.95`, `MU_JOB=0.05` | `MU_RENT=0.95`; `MU_JOB=0.7315`; `MU_RENT` ranks first. |
| Weaker temporal link | Parent `1.0`, temporal link weight `0.5` | Propagated score is `0.35`, not a value above the parent. |
| Weaker causal link | Parent `1.0`, active-cause link weight `0.5` | Propagated score is `0.385`, not a value above the parent. |
| Cause-factor comparison | Full-weight causal chains with `R=1.1` and `R=1.2`, no direct-date refresh | `1.1` remains above `0.2` through depth 6; `1.2` remains above `0.2` through depth 9; the implementation default is `1.1`. |
| Direct-date override | Deeper candidate direct proximity exceeds inherited propagation | Candidate uses the higher direct value; the test identifies direct evidence as the reason for any depth inversion. |
| Score bounds | Supported edge types, weights `0.1` through `1.0`, up to five iterations | Every temporal score remains in `[0, 1]`. |
| Continuation boundary | Candidate scores `0.2` and immediately above `0.2` | Both are admitted; only the value above `0.2` enters the next frontier. |
| Cross-fact-type ordering | Temporal results supplied in deliberately incorrect concatenation order | Aggregation reorders them by `temporal_score`, then the documented tie-breaks. |
| Fusion input | `MU_RENT` and `MU_JOB` enter the temporal arm with the motivating scores | RRF sees `MU_RENT` at a better temporal rank than `MU_JOB`; raw temporal scores are not added to another arm's scores. |

No live-service or database claim is made by this document. Runtime availability and ranking behavior remain unverified until the implementation and the acceptance cases above are executed against the real PostgreSQL recall path.

## 10. Non-Goals and Deferred Questions

This design does not introduce learned weights, public scoring configuration, tuned factors for historical relationship names, arbitrary graph search, historical-score persistence, or cross-version replay machinery. The single `1.1` active-cause factor is the initial design default; changing it to `1.2` requires the evidence described in Section 6.1 rather than a speculative configuration surface.

The current traversal marks a node visited on first discovery rather than reconciling multiple parent paths. This proposal retains that behavior to keep the change bounded; choosing the strongest path is a separate design question and must not block the monotonic scoring correction.
