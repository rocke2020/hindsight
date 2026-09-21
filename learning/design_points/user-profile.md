# Hindsight User Profile: A Standing Answer That Maintains Itself

## Overview

Hindsight has no dedicated user-profile endpoint, table, or engine path. A user profile is a mental model whose id is conventionally `user-profile` and whose source query asks the reflect agent to synthesise who the user is from the bank's memories. Everything the feature offers — generation, cheap reads, staleness, refresh modes, and automatic refresh — is the generic mental-model machinery reused with that one convention.

1. Generation is not a special call: `create_mental_model` creates the model and submits a background refresh that runs its stored source query through the agentic reflect pipeline.
2. Refresh behavior comes from the model's persisted `trigger.mode`, not from a per-refresh argument. `full` is the generic mental-model default and regenerates from the whole eligible history; `delta` uses the current document as a baseline and restricts memory retrieval to writes after the previous watermark.
3. Delta mode is incremental but not simply "append the latest memory": it first reflects over new or edited memories, then asks a second LLM call to emit structured operations against the existing profile. The normal first generation is full because no usable baseline exists, and changing the source query also forces a full regeneration.
4. Reading is the performance pitch: `get_mental_model` is a database read that recomputes nothing. The answer is already written; recall with a live reflect at question time is the expensive alternative this replaces.
5. Freshness is data-driven, not time-driven: staleness compares the model's memory watermark against writes in its scope. No new memories means never stale, however much wall-clock time passes; there is no TTL.
6. Automatic refresh is opt-in: without a trigger, a stale model keeps serving its old content until a caller explicitly refreshes. With `refresh_after_consolidation` or a cron schedule, the worker refreshes stale models using their stored mode.
7. Delta usually reduces the memory context for small updates, but it does not guarantee lower total tokens or better profile quality: it adds a merge call and carries the current document, while full mode can reconsider the whole history but can also omit previously captured details under retrieval and output limits.
8. An integration restricted to the Reflect API can still generate multiple views, such as a user profile and relevant follow-up questions, by making one reflect call per target with a different `query`. Those results are on-demand responses, not persisted mental models: Reflect provides no stored `source_query`, watermark, staleness state, automatic refresh, or cheap read path.

Scope: static source trace of the `dev` branch (engine and HTTP code in `hindsight-api-slim/hindsight_api/`), the Python client, the quick-start example, and the system tests that pin full and delta behaviour. No live LLM comparison or claim that one mode has higher user-profile accuracy is made here; the cited tests prove mechanics, not comparative quality.

## Terminology

- **Mental model**: a per-bank document synthesised from the bank's memories by running a stored query through reflect; the standing answer to a recurring question.
- **User profile**: the conventional instance of a mental model with id `user-profile`, one bank per user, holding a factual profile of that user.
- **Source query**: the natural-language question stored on the mental model. Full mode regenerates an answer to it; delta mode uses it as the topic that constrains edits to the existing answer.
- **Reflect query**: the transient natural-language prompt supplied to one Reflect API call. It is not stored by Reflect and has no refresh lifecycle; in a Reflect-only integration it serves the targeting role that a mental model's persisted source query otherwise serves.
- **Full mode**: the default refresh mode. The whole eligible memory history is available to retrieval, no lower watermark bound is applied, and the resulting synthesis replaces the stored document.
- **Delta mode**: an opt-in refresh mode. The current document is the baseline, memory retrieval is bounded to writes after the previous watermark, and structured operations integrate the new evidence without rewriting untouched sections.
- **Reflect loop**: the agentic reasoning pass in which the model climbs a ladder of search tools (recall, mental-model search, observation search) and then synthesises an answer.
- **Watermark** (`last_memory_seen_at`): the newest in-scope memory the model's last successful refresh saw. It is both the staleness boundary and, in delta mode, the lower bound for new or edited memories.
- **Stale**: a memory in the model's scope was written or updated after the watermark. It means "worth refreshing", not "wrong".
- **Scope**: the set of memories a staleness check or refresh considers, resolved from the model's tags (`tags` / `tags_match` / `tag_groups`) and fact-type filter. An untagged model defaults to matching any memory in the bank.
- **Trigger**: the model's persisted refresh configuration, including `mode`, `refresh_after_consolidation`, `refresh_cron`, throttling, and retrieval options.

## 1. The Feature Is One Convention

The client call that creates a user profile is the ordinary mental-model create with two fixed choices: the id and the source query. The quick-start example (`learning/quick_start/user_profile.py`) is the reference flow:

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

Because that trigger omits `mode`, the API fills the generic default `mode: "full"`. Each refresh in the current quick-start therefore regenerates the profile with the whole eligible history available to retrieval; the watermark decides whether an automatic refresh is needed, but does not narrow a full refresh.

To make routine refreshes incremental, the model must persist delta mode explicitly:

```python
client.create_mental_model(
    bank_id="user-alice",
    id="user-profile",
    name="User Profile",
    source_query=USER_PROFILE_SOURCE_QUERY,
    max_tokens=2048,
    trigger={
        "mode": "delta",
        "refresh_after_consolidation": True,
    },
)
```

The source query is the feature's one piece of profile-specific product content — a prompt that constrains the reflect agent to retrieved memories only, treats repeated memories as duplicate evidence, forbids attributing the bank's own settings to the user, and marks unknowns as unknown. Everything else (id, name, max tokens, refresh mode, trigger, and retrieval scope) is ordinary mental-model configuration.

One bank per user is the storage layout: Alice's memories and profile live in `user-alice`, openclaw's in `user-openclaw`. Bank isolation is strict, so the profile inherits per-user isolation for free.

## 2. Each Refresh Uses the Stored Mode

The refresh API chooses no mode of its own. `POST /v1/default/banks/{bank_id}/mental-models/{mental_model_id}/refresh` has no request body, and the Python client's `refresh_mental_model` accepts only the bank and model ids. The worker loads the model, reads `trigger.mode`, defaults a missing value to `full`, and executes that mode. Automatic refreshes and explicit refreshes therefore use the same persisted policy.

This no-per-request-options rule is also part of refresh-queue deduplication: a pending refresh can safely cover another submission only because both will perform the same stored work. A caller can change the mode through `update_mental_model`, but that changes persistent model configuration rather than overriding one generation call.

### 2.1 Full Mode Rebuilds the Document

Full mode makes the whole eligible memory history available to the reflect search tools by omitting a lower time bound. "Whole history" does not mean every raw memory is copied into one prompt: the agent still retrieves and ranks evidence under recall, context, iteration, and output limits. The final synthesis replaces the stored profile, previous content moves into history, and the successful run advances `last_memory_seen_at` to the newest in-scope memory visible at the refresh snapshot.

Full mode is the normal first-generation path. A newly created API model contains only the pending placeholder, so even a model configured for delta has no usable document to edit and falls back to full. Delta also falls back to full when the stored source query differs from the query used by the previous successful refresh, because the old document may answer a different question.

### 2.2 Delta Mode Edits the Current Document with Later Evidence

Delta mode requires usable current content and an unchanged source query. It opens the memory window at `last_memory_seen_at` (falling back to `last_refreshed_at` for older rows), caps it at a database-time snapshot, and runs reflect with that window. Although the API names these bounds `created_after` and `created_before`, retrieval applies them to `updated_at`, so both newly added and edited memories re-enter the window.

The model being refreshed is excluded from mental-model search, so reflect does not rediscover the user profile as evidence. Sibling mental models remain searchable unless `exclude_mental_models` or `exclude_mental_model_ids` removes them; the watermark window applies to memories, not to those sibling documents.

After reflect synthesises what the new evidence says, a second structured-output call receives the current profile, that new-information synthesis, the supporting facts from this run, the source query, and the document budget. It emits operations such as adding, replacing, moving, or removing blocks. The engine applies valid operations to the current structured document and renders the result; sections no operation touches remain physically unchanged. Historical supporting facts are retained in grounding metadata but are not resent to the delta operation prompt.

Delta also handles a previously cited memory that no longer exists. Before integrating new evidence, a retraction pass can remove statements grounded in the missing fact; when replacement facts are still pending consolidation, removal is deferred so a re-ingest does not temporarily erase a still-true claim.

If there is no new supporting evidence and no retraction to apply, the current document is preserved. If the operation call fails or every proposed operation is rejected, the engine refuses to write a delta-window synthesis as the whole profile, leaves the previous content and watermark untouched, and lets a retry read the same window again.

### 2.3 Refresh Failure Preserves the Last Good Profile

Both modes are snapshot-bounded: memories committed after the cutoff remain newer than the persisted watermark and are eligible for the next refresh. A failed retrieval, missing answer, empty candidate, or failed delta application does not replace the profile or advance its watermark. The operation records a typed failure, while the last good profile remains readable.

## 3. Reading Recomputes Nothing

`get_mental_model(bank, "user-profile", detail="content")` is a database read. No reflect turn, no LLM call, no recomputation — this is the economic argument for the whole feature, and the system-test story pins it directly: after generation, the test resets the LLM rulebook so any further reflect call would fail the test, then reads the profile twice and asserts identical content (`hindsight-system-tests/tests/test_34_user_profile.py`, `test_getting_the_profile_recomputes_nothing`).

The practical consequence for an agent integration: injecting the user profile into a prompt is a cheap, cacheable fetch, not a reasoning pass. Freshness is handled separately by the staleness and trigger machinery below, not by making reads expensive.

## 4. Staleness Is a Watermark, Not a TTL

Staleness is a question about data, not about clocks. The single-model check (`MemoryEngine.compute_mental_model_is_stale` in `memory_engine.py`) answers: was a memory in this model's scope written or updated after `last_memory_seen_at`?

- A cheap shortcut first compares the model's watermark against the bank's newest memory write; if nothing has been written anywhere in the bank since the model last read, the model is current and no scoped query runs.
- Otherwise a scoped existence check asks whether one of the writes since the watermark falls inside the model's scope (tags, tag groups, fact types). Writes outside the scope do not count.
- Both inserts and updates count as writes; a memory edit makes the model stale just as a new memory does.
- A hard deletion raises no timestamp, so staleness separately checks whether facts cited by the stored grounding still exist.

There is no timeout and no TTL. A profile over an unchanged bank stays current forever, and a profile over an actively written bank goes stale after a retain. `last_refreshed_at` exists but does not participate in ordinary write staleness — refreshing a model must not, by itself, make it look current, which is why the watermark is stamped from the memories the refresh saw rather than from the clock.

Going stale does not change the answer. The old content keeps serving until a refresh replaces it; blanking it on staleness would leave a gap every time anything was retained. `is_stale` means "worth refreshing", and the flag is visible on every read so the caller can decide.

## 5. Automatic Refresh Is Opt-In

Staleness is computed automatically and unconditionally; regeneration of stale content is not. The model's trigger decides when to enqueue a refresh, while `trigger.mode` decides how that refresh processes the profile:

1. **No refresh trigger (the default)**: a stale profile keeps serving old content indefinitely. A caller that wants the new facts must call `refresh_mental_model` itself. Reading `is_stale: true` is the signal to do so.
2. **`refresh_after_consolidation: true`**: after observations consolidation finishes, the worker selects models with this flag that are actually stale — a tag prefilter followed by a per-model scoped check (authoritative entry: the consolidation flush in `hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py`) — and refreshes each in its stored full or delta mode. The trigger point is consolidation, not retain: new memories must pass through observations consolidation first.
3. **`refresh_cron`**: a UTC cron schedule. Each tick still checks staleness first and skips the refresh when nothing in scope changed; a cron and `refresh_after_consolidation` are mutually exclusive because the two triggers would race and double-refresh.

Two refinements keep automatic refresh cheap:

- **`min_refresh_interval_seconds`** (default 0, meaning no floor) is a per-model minimum spacing between automatic refreshes. A trigger arriving inside the window is not dropped but parked, and further triggers fold into the one queued refresh — a burst of retains costs one refresh instead of one per retain.
- **The stale gate itself** is the anti-waste mechanism for scheduled refreshes: ticks over an unchanged bank do nothing.

Explicit refreshes — the API, MCP, and control-plane paths — ignore the staleness gate and the minimum interval and run immediately, but they still use the model's stored mode. There is no atomic `refresh_mental_model(..., mode="delta")` or `mode="full"` override.

## 6. Changing the Prompt Is Update, Then Refresh

`update_mental_model` with a new `source_query` writes the query to the model's row and does nothing else — no reflect and no regeneration. The stored content still reflects the old query until a refresh runs. The correct sequence, which the quick-start example performs before every refresh, is:

```python
client.update_mental_model(bank_id, "user-profile", source_query=NEW_SOURCE_QUERY)
client.refresh_mental_model(bank_id, "user-profile")   # runs the new query through reflect
```

Because explicit refresh ignores the staleness gate, the second call runs even when the model is not stale. In delta mode, the changed source query deliberately disables the delta baseline and makes that refresh full; subsequent refreshes can return to delta after the successful run records the new query. The two API calls remain separate because changing stored configuration should not silently spend LLM tokens.

## 7. Full and Delta Trade Different Risks

Neither mode dominates on token cost or profile quality. Full mode has stronger global reconsideration; delta mode has stronger continuity.

### 7.1 Token Cost Is Workload-Dependent

Delta usually reduces recall context when the bank has a long history and only a small batch changed, and an empty delta window can preserve the document without running the merge call. But when reflect returns supporting facts, a delta refresh performs the reflect pipeline and then an additional structured-operation LLM call carrying the current document and new evidence. A short profile over a small bank can therefore cost the same as or more than a full refresh. The implementation and tests establish the call graph and token windows, not a universal token-saving ratio.

### 7.2 Full Mode Can Improve Global Coherence

Full mode can reconsider relationships across older and newer memories, reorganise the whole profile, remove duplication, and correct an accumulated structure. It is the stronger re-baselining mechanism after a major topic change or visible profile drift. Its limitation is that the full history is available to retrieval rather than guaranteed to fit in the final context; a regeneration can omit an older detail that the stored profile had preserved.

### 7.3 Delta Mode Can Improve Retention and Stability

Delta preserves prior profile text that no operation touches, so an unrelated update cannot paraphrase or accidentally drop established details. That stability can make delta more accurate for routine updates even though it sees less historical evidence. Its limitation is that an incomplete or mistaken baseline can persist, and many local edits can leave the document poorly organised or over budget despite correct individual updates.

### 7.4 Practical Policy for a Frequently Updated User Profile

A practical policy, not an engine default, is: generate the first profile in full mode, use delta for routine small updates, and perform a controlled full regeneration when the source query changes, the profile shows contradiction or duplication, many memories were revised, or evaluation shows that local edits have accumulated a bad baseline. `clear_mental_model` also forces the next refresh to re-synthesise because it removes the delta baseline, but callers should treat clearing as an explicit state-changing operation rather than a routine refresh option.

Choosing between these policies requires a representative evaluation over the same evolving memory sequence. The relevant measures are not only total tokens, but also retained facts, correction of superseded facts, unsupported claims, contradiction handling, profile organisation, and stability across refreshes.

## 8. The Blackbox Stories and Proof Boundary

The user-profile system test in `hindsight-system-tests/tests/test_34_user_profile.py` drives a real `hindsight-api` process through the published Python client with a scripted LLM — no engine access and no SQL. The user is openclaw, the bank is `user-openclaw`, and the three stories pin the default full-mode profile cycle:

1. **Generation**: retain the user's memories (employer, role, and programming-language preference), create the `user-profile` model with the profile source query, and assert the content is the synthesised profile drawn from the bank.
2. **Cheap reads**: read the profile twice with the LLM rulebook reset — any reflect turn would fail the test — and assert identical content both times.
3. **Refresh**: retain a new fact about the user, explicitly refresh, and assert the profile now includes it and is no longer stale.

Delta mechanics are pinned separately in `hindsight-api-slim/tests/test_mental_model_delta.py`: the tests verify the watermark-bounded memory window, current-document baseline, new-facts-only operation prompt, preservation of untouched sections, source-query fallback to full, safe handling of failed operations, and repeated-update stability. These deterministic tests prove the implementation contract; they do not prove that delta uses fewer provider-billed tokens or produces a more accurate user profile than full mode on a real corpus.

The neighbouring system stories pin shared full-mode machinery: staleness semantics in `test_31_mental_model_staleness.py` (a later write makes the model stale, staleness alone does not change the answer, a refresh advances the watermark and clears the flag, and history keeps the previous answer) and the generic model lifecycle in `test_30_mental_models.py` (creation is immediate, a refresh writes an answer drawn from the bank, and deleting a model leaves the facts alone).

## 9. Reflect-Only Multi-Target Generation

A caller that can use only the Reflect API can generate a profile and related questions, but it must treat them as separate on-demand computations. There is no multi-target `source_query` configuration on Reflect: each target is one call with its own `query`, and each call independently runs the reflect retrieval and synthesis pipeline over the bank.

| Concern          | Mental model                  | Reflect-only integration                                        |
| ---------------- | ----------------------------- | --------------------------------------------------------------- |
| Target prompt    | Persisted `source_query`      | Per-call `query`                                                |
| Result lifetime  | Stored in Hindsight           | Returned to the caller only                                     |
| Updating         | Explicit or automatic refresh | Call Reflect again                                              |
| Reading          | Cheap database read           | Another Reflect computation unless the caller caches the result |
| Multiple targets | Multiple model ids            | Multiple Reflect calls                                          |

### 9.1 Independent Profile and Question Views

The simplest design derives both outputs directly from the same bank memories. `exclude_mental_models=True` makes that boundary explicit: existing mental models in the bank cannot silently become evidence for either result. The calls are independent and may be run concurrently when the deployment's Reflect admission and LLM concurrency limits allow it; sequential calls are equally correct.

```python
profile = client.reflect(
    bank_id="user-alice",
    query=(
        "Build a factual user profile from retrieved memories only. "
        "Include confirmed background, preferences, goals, and constraints. "
        "Do not infer unsupported details."
    ),
    budget="mid",
    max_tokens=2048,
    exclude_mental_models=True,
)

questions = client.reflect(
    bank_id="user-alice",
    query=(
        "Generate five useful follow-up questions from retrieved memories. "
        "Focus on unresolved goals, missing information, contradictions, and decisions "
        "that would help support the user. Do not answer the questions."
    ),
    budget="mid",
    max_tokens=1024,
    exclude_mental_models=True,
    response_schema={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["questions"],
    },
)

profile_markdown = profile.text
if not profile_markdown.strip():
    raise RuntimeError("Reflect returned an empty user profile")
if questions.structured_output_error:
    raise RuntimeError(questions.structured_output_error)
if questions.structured_output is None:
    raise RuntimeError("Reflect returned no structured question list")
question_list = questions.structured_output["questions"]
```

`response_schema` is optional. Without it, `questions.text` is ordinary Markdown; with it, Reflect also performs structured-output extraction and returns the typed value in `structured_output`. Callers must check `structured_output` and `structured_output_error` rather than assuming extraction succeeded merely because the Reflect response contains text.

Tags, tag groups, and fact types can give the two calls different evidence scopes as well as different prompts. Different `query` values answer different questions over the same scope; filters are what make them read different subsets of the bank.

### 9.2 Questions That Depend on the Generated Profile

If the questions must be based specifically on the generated profile rather than independently on bank memories, the calls have a real dependency and must be sequential. Run the profile call first, validate that it returned usable visible content, and include that content directly in the second call's `query`; the separate `context` parameter is deprecated and is only retained for backward compatibility.

```python
profile = client.reflect(
    bank_id="user-alice",
    query="Build a factual user profile from retrieved memories only. Do not infer unsupported details.",
    budget="mid",
    max_tokens=2048,
    exclude_mental_models=True,
)
if not profile.text.strip():
    raise RuntimeError("Reflect returned an empty user profile")

questions = client.reflect(
    bank_id="user-alice",
    query=f"""Using the generated profile below, produce five useful follow-up questions.

User profile:
{profile.text}

Prioritize missing information, unresolved goals, contradictions, and pending decisions. Do not answer the questions.""",
    budget="mid",
    max_tokens=1024,
    exclude_mental_models=True,
    response_schema={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["questions"],
    },
)
```

This second form deliberately pays for two sequential reflect pipelines and carries the generated profile into the second prompt. It gives the questions a clear dependency on the exact profile result, but it does not create persistence: when memories change, the caller must rerun the profile and then the questions. If the application needs cheap repeated reads, it must cache or store the returned artifacts outside the Reflect API and define when that cache is invalidated.

### 9.3 Current-Message Questions Are Also On-Demand

Questions related to the user's current message should stay in the second Reflect call's `query`, together with the current message. A standing mental model is suited to a recurring question over accumulated memories; changing a mental model's source query for every user message would cause regeneration and, in delta mode, a full-mode fallback after every topic change. Reflect-only generation avoids that mismatch because its query is intentionally request-scoped.
