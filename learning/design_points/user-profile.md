# Hindsight User Profile: A Standing Answer That Maintains Itself

## Overview

Hindsight has no dedicated user-profile endpoint, table, or engine path. A user profile is a mental model whose id is conventionally `user-profile` and whose source query asks the reflect agent to synthesise who the user is from the bank's memories. Everything the feature offers — generation, cheap reads, staleness, and automatic refresh — is the generic mental-model machinery reused with that one convention, which is why this document describes the mechanism mostly in mental-model terms.

1. Generation is not a special call: `create_mental_model` with a profile-shaped source query submits a background operation that runs that query through the full agentic reflect loop, and the resulting text is stored as the model's content.
2. Reading is the performance pitch: `get_mental_model` is a database read that recomputes nothing. The answer is already written; recall with a live reflect at question time is the expensive alternative this replaces.
3. Freshness is data-driven, not time-driven: staleness compares the model's memory watermark against writes in its scope. No new memories means never stale, however much wall-clock time passes; there is no TTL.
4. Automatic refresh is opt-in: without a trigger, a stale model keeps serving its old content until a caller explicitly refreshes. With `refresh_after_consolidation` (or a cron schedule), the worker refreshes stale models on its own.
5. Changing the source query does not regenerate anything by itself: `update_mental_model` stores the new query; a separate `refresh_mental_model` runs it. Explicit refreshes ignore the staleness gate and always rerun.

Scope: static source trace of the `dev` branch (engine code in `hindsight-api-slim/hindsight_api/`), the Python client, the quick-start example, and the system-test story that pins the behaviour end to end. No live LLM run is claimed here; the cited tests are the evidence.

## Terminology

- **Mental model**: a per-bank document synthesised from the bank's memories by running a stored query through reflect; the standing answer to a recurring question.
- **User profile**: the conventional instance of a mental model with id `user-profile`, one bank per user, holding a factual profile of that user.
- **Source query**: the natural-language query stored on the mental model; each refresh runs it through reflect to regenerate content.
- **Reflect loop**: the agentic reasoning pass in which the model climbs a ladder of search tools (recall, mental-model search, observation search) and then synthesises an answer.
- **Watermark** (`last_memory_seen_at`): the newest in-scope memory the model's last successful refresh saw; staleness keys off this, never off the wall clock.
- **Stale**: a memory in the model's scope was written or updated after the watermark. It means "worth refreshing", not "wrong".
- **Scope**: the set of memories a staleness check or refresh considers, resolved from the model's tags (`tags` / `tags_match` / `tag_groups`) and fact-type filter. An untagged model defaults to matching any memory in the bank.
- **Trigger**: the model's refresh policy — `refresh_after_consolidation`, `refresh_cron`, or neither (the default).

## 1. The Feature Is One Convention

The client call that creates a user profile is the ordinary mental-model create with two fixed choices: the id and the source query. The quick-start example (`learning/quick_start/quick_start.py`) is the reference flow:

```python
client.create_mental_model(
    bank_id="user-alice",
    id="user-profile",                # the convention callers address the profile by
    name="User Profile",
    source_query=USER_PROFILE_SOURCE_QUERY,
    max_tokens=2048,
    trigger={"refresh_after_consolidation": True},
)
```

The source query is the feature's one piece of real product content — a prompt that constrains the reflect agent to retrieved memories only, treats repeated memories as duplicate evidence, forbids attributing the bank's own settings to the user, and marks unknowns as unknown. Everything else (id, name, max_tokens, trigger) is ordinary mental-model configuration.

One bank per user is the storage layout: Alice's memories and profile live in `user-alice`, openclaw's in `user-openclaw`. Bank isolation is strict, so the profile inherits per-user isolation for free.

## 2. Generation Runs Through Reflect

`create_mental_model` returns immediately with an operation id; the content is background work. The worker executes the refresh path (authoritative entry: `MemoryEngine.refresh_mental_model` and `_execute_mental_model_refresh` in `hindsight-api-slim/hindsight_api/engine/memory_engine.py`), which:

1. Resolves the model's row, including its stored source query and scope.
2. Runs the source query through the agentic reflect loop — the same ladder of forced search turns (recall, mental-model search, observation search) followed by a synthesising answer that any other reflect call walks. The agent reads the bank's facts, observations, and other mental models as evidence.
3. Stores the answer as the model's content, embeds the document, stamps `last_refreshed_at = NOW()`, and stamps the watermark (`last_memory_seen_at`) with the newest in-scope memory the refresh saw.
4. Keeps the previous content in the model's history, so "it used to say something else" stays answerable.

A refresh failure (an empty answer, a failed retrieval tool, a reflect that produced no answer) is typed and recorded on the operation, and leaves the previous content and watermark untouched — a retry reads the same window again. The model exists and is addressable before it has content, holding a visible placeholder rather than pretending to have an answer; a caller can tell "not written yet" from "nothing to say".

## 3. Reading Recomputes Nothing

`get_mental_model(bank, "user-profile", detail="content")` is a database read. No reflect turn, no LLM call, no recomputation — this is the economic argument for the whole feature, and the system-test story pins it directly: after generation, the test resets the LLM rulebook so any further reflect call would fail the test, then reads the profile twice and asserts identical content (`hindsight-system-tests/tests/test_34_user_profile.py`, `test_getting_the_profile_recomputes_nothing`).

The practical consequence for an agent integration: injecting the user profile into a prompt is a cheap, cacheable fetch, not a reasoning pass. Freshness is handled separately by the staleness and trigger machinery below, not by making reads expensive.

## 4. Staleness Is a Watermark, Not a TTL

Staleness is a question about data, not about clocks. The single-model check (`MemoryEngine.compute_mental_model_is_stale` in `memory_engine.py`) answers: was a memory in this model's scope written or updated after `last_memory_seen_at`?

- A cheap shortcut first compares the model's watermark against the bank's newest memory write; if nothing has been written anywhere in the bank since the model last read, the model is current and no scoped query runs.
- Otherwise a scoped existence check asks whether one of the writes since the watermark falls inside the model's scope (tags, tag groups, fact types). Writes outside the scope do not count.
- Both inserts and updates count as writes; a memory edit makes the model stale just as a new memory does.

There is no timeout and no TTL. A profile over an unchanged bank stays current forever, and a profile over an actively-written bank goes stale within seconds of a retain. `last_refreshed_at` exists but does not participate in staleness — refreshing a model must not, by itself, make it look current, which is why the watermark is stamped from the memories the refresh saw rather than from the clock.

Going stale does not change the answer. The old content keeps serving until a refresh replaces it; blanking it on staleness would leave a gap every time anything was retained. `is_stale` means "worth refreshing", and the flag is visible on every read so the caller can decide.

## 5. Automatic Refresh Is Opt-In

Staleness is computed automatically and unconditionally; regeneration of stale content is not. The model's trigger decides:

1. **No trigger (the default)**: a stale profile keeps serving old content indefinitely. A caller that wants the new facts must call `refresh_mental_model` itself. Reading `is_stale: true` is the signal to do so.
2. **`refresh_after_consolidation: true`**: after observations consolidation finishes, the worker selects the models with this flag that are actually stale — a tag prefilter followed by a per-model scoped check (authoritative entry: the consolidation flush in `hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py`) — and refreshes each through the same reflect path as generation. The trigger point is consolidation, not retain: new memories must pass through observations consolidation first.
3. **`refresh_cron`**: a UTC cron schedule. Each tick still checks staleness first and skips the LLM call when nothing in scope changed; a cron and `refresh_after_consolidation` are mutually exclusive because the two triggers would race and double-refresh.

Two refinements keep automatic refresh cheap:

- **`min_refresh_interval_seconds`** (default 0, i.e. no floor) is a per-model minimum spacing between automatic refreshes. A trigger arriving inside the window is not dropped but parked, and further triggers fold into the one queued refresh — a burst of retains costs one refresh, not one per retain.
- **The stale gate itself** is the anti-waste mechanism for scheduled refreshes: ticks over an unchanged bank do nothing.

Explicit refreshes — the API, MCP, and control-plane paths — ignore the staleness gate and the minimum interval, and run immediately. This is what makes "the prompt changed, regenerate now" a two-call operation.

## 6. Changing the Prompt Is Update, Then Refresh

`update_mental_model` with a new `source_query` writes the query to the model's row and does nothing else — no reflect, no regeneration. The stored content still reflects the old query until a refresh runs. The correct sequence, which the quick-start example performs before every refresh:

```python
client.update_mental_model(bank_id, "user-profile", source_query=NEW_SOURCE_QUERY)
client.refresh_mental_model(bank_id, "user-profile")   # runs the new query through reflect
```

Because explicit refresh ignores the staleness gate, the second call regenerates even when the model is not stale — prompt changes do not have to wait for new memories to justify the work. The two calls being separate is deliberate: an import or hand-authored edit can change the stored query without paying for an LLM run it does not want yet.

## 7. The Blackbox Story

The end-to-end behaviour is pinned in `hindsight-system-tests/tests/test_34_user_profile.py`, which drives a real `hindsight-api` process through the published Python client with a scripted LLM — no engine access, no SQL. The user is openclaw, the bank is `user-openclaw`, and the three stories are the feature's contract:

1. **Generation**: retain the user's memories (employer, preferred language), create the `user-profile` model with the profile source query, and assert the content is the synthesised profile drawn from the bank.
2. **Cheap reads**: read the profile twice with the LLM rulebook reset — any reflect turn would fail the test — and assert identical content both times.
3. **Refresh**: retain a new fact about the user, explicitly refresh, and assert the profile now includes it and is no longer stale.

The neighbouring stories pin the shared machinery: staleness semantics in `test_31_mental_model_staleness.py` (a later write makes the model stale, staleness alone does not change the answer, a refresh advances the watermark and clears the flag, history keeps the previous answer) and the generic model lifecycle in `test_30_mental_models.py` (creation is immediate, a refresh writes an answer drawn from the bank, deleting a model leaves the facts alone).
