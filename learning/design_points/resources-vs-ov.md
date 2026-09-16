# User Resources: What Hindsight Has Versus What OpenViking Has

## Overview

Hindsight has no resource concept. OpenViking (ov) treats a resource as a first-class context type: user-added external knowledge such as API docs, code repositories, and manuals, stored under `viking://resources/` with layered extraction and optional scheduled re-ingestion. Hindsight's nearest equivalents — the file retain endpoint, timestamp-unset memory items, and document tags — can hold the same bytes and answer the same queries, but they are ordinary memories in an ordinary bank, not a separate tier with its own semantics. The practical consequence: a "user inserts reference material once, agents query it forever" flow is reproducible in Hindsight today, while the ov-specific guarantees (self-updating sources, deterministic URI tree, progressive layer loading) are not.

Scope: Hindsight `dev` branch (`hindsight-api-slim/hindsight_api/`) against the local ov checkout at `~/codes/ov1`. No live runs claimed; the cited source files are the evidence.

## Terminology

- **Resource** (ov): one of ov's three context types — Resource, Memory, Skill — where Resource is user-initiated, long-lived, relatively static knowledge the agent references but does not write (`ov1/docs/en/concepts/02-context-types.md`).
- **Bank** (Hindsight): an isolated memory store; the unit of multi-tenancy and of the strict no-cross-bank-leakage guarantee.
- **File retain**: Hindsight's multipart file ingestion endpoint, `POST /v1/default/banks/{bank_id}/files/retain`, which parses uploads and runs the standard retain pipeline asynchronously.
- **Retain pipeline**: parse → chunk → LLM fact extraction → entity/link graph → embedding; every ingest, file or text, becomes documents plus extracted facts.
- **Timestamp-unset**: the `MemoryItem.timestamp` sentinel string `"unset"`, explicitly documented for "timeless content such as fictional documents or static reference material" (`hindsight-api-slim/hindsight_api/api/http.py:1128`).
- **L0/L1/L2 layers** (ov): abstract / overview / detail tiers ov builds per resource, loaded on demand so an agent reads a summary before paying for full content.

## 1. The Two Models Side by Side

The difference is a data-model split versus a data-model collapse. In ov, what the user adds and what the agent learns are different *kinds* of context with different storage locations, lifecycle, and write authority — `add_resource` writes under `viking://resources/`, agent memory under `viking://user/{user_id}/memories/`, and the type system enforces who writes where. In Hindsight, both are memories in a bank; the only structural distinction available to the caller is which bank, which document, and which tags.

| Aspect | OpenViking Resource | Hindsight nearest equivalent |
|---|---|---|
| Write API | `client.add_resource(path_or_url, reason=...)`, one call per source (`ov1/openviking/server/routers/resources.py:210`) | `files/retain` for files (`http.py:9311`); `memories/retain` for text (`http.py:1247`) |
| Input sources | Remote HTTP(S) URL, git repo, sitemap, RSS, cloud connector (tos/git/Feishu), or temp upload (`AddResourceRequest`, `resources.py:26`) | Uploaded file bytes or in-request text; no URL, git, or connector ingestion — the caller fetches, Hindsight stores |
| Self-updating | `watch_interval` schedules re-processing; watches are per-resource and source-conflict-checked (`resources.py:65`) | None; re-send the content |
| Storage identity | `viking://resources/<name>/...` URI tree, `ls`/`tree`/`find` browsable | `document_id` + `context` + `tags` inside a bank; no URI or tree |
| Extraction model | Layered L0/L1/L2 summaries, loaded progressively | LLM fact extraction into facts/entities/links — corpus becomes memories |
| Static-content signalling | The type itself is "relatively static, user-modified" | `timestamp: "unset"` per item; otherwise none |
| Isolation from agent memories | Separate namespace by type system | Separate bank (caller's choice) or nothing |
| Annotating why it was added | `reason` field, "used for documentation and monitoring" | `metadata` dict on the item |

## 2. What Works Today in Hindsight

The file path is real and first-class in its own right. `files/retain` accepts multipart uploads with a per-file parser chain (`iris`, `markitdown`, `llama_parse` — `hindsight_api/engine/parsers/`), per-file `document_id`/`context`/`tags`/`strategy`, and always processes asynchronously (`http.py:1318` rejects synchronous `update_mode` on this endpoint explicitly). The parsed text then flows through the ordinary retain pipeline, so a PDF manual ends up as a document with extracted facts, an entity graph, and embeddings — fully recallable.

The recipe for an ov-style "reference bank" is therefore:

1. Create a dedicated bank for reference material, so user-added knowledge and agent conversation memories never mix — the bank boundary is the only hard isolation Hindsight offers.
2. Insert files via `files/retain` with a `context` naming the project and `tags` standing in for ov's directory grouping.
3. Insert plain text via `memories/retain` with `timestamp: "unset"` so static material is not falsely treated as events on a timeline.
4. Query with ordinary recall; per-strategy recall boosts (semantic/BM25/graph/temporal) are the retrieval-side tuning surface.

What this buys: durable, recallable, entity-linked knowledge added by the user. What it does not buy is everything in the next section.

## 3. What Only ov Has

Four capabilities have no Hindsight counterpart, and naming them precisely is more useful than "Hindsight doesn't support resources":

1. **Source-driven ingestion.** ov's `add_resource` takes the *URL or repo* and does the fetching itself, including auth (`args.auth_config` for git, Feishu tokens). Hindsight's ingest boundary is the request body; whatever the client uploads is all it sees. A Hindsight caller wanting "add this website" must fetch, convert, and re-retain on every change themselves.
2. **Watches.** `watch_interval > 0` registers a scheduled re-process of the same source, with conflict rules when the source changes. This is the difference between "reference material that maintains itself" and "a snapshot the user must remember to refresh". Hindsight's `worker/poller.py` polls the database task queue — it is task infrastructure, not source monitoring, despite the surface resemblance.
3. **The URI tree.** `viking://resources/<project>/...` with `ls`/`tree`/`grep` gives agents deterministic, browseable access to context. Hindsight's recall is similarity-and-graph retrieval with no enumerable namespace; an agent cannot list what reference material exists, only search it.
4. **Progressive layers.** L0 abstract → L1 overview → L2 detail means an agent reads a one-paragraph summary and only descends when needed. Hindsight chunking plus reranking serves a similar goal inside recall — small chunks scored, best ones returned — but the explicit "cheap summary first, pay only on demand" contract is not exposed.

The reverse framing also matters: ov's resource is *parsed and summarised*; Hindsight's ingest is *interpreted into facts*. For an API manual, ov gives you browsable layers of the original; Hindsight gives you "the rate limit is 100 req/min" as a fact linked to the `rate limit` entity. Which is better depends on whether the consumer is an agent reading documentation or an agent answering questions.

## 4. Design Point

If Hindsight were to grow a real resource tier, the existing seams suggest where it would attach: `retain_strategies` already lets a bank define named ingestion profiles, a resource strategy could pin "no timestamp, verbatim-heavy, no consolidation" semantics without a new type system; and bank templates (`apply_default_bank_template_resources`, `http.py:4009`) already seed reference-like content at bank creation. The costlier halves are the parts that are not configuration but architecture — watches need a scheduler with source ownership, and a URI tree needs a namespace model the recall engine currently lacks. Until then, "Hindsight supports user resources" is true only in the collapsed sense: they are memories the user happened to add, kept honest by bank isolation and the `"unset"` timestamp.
