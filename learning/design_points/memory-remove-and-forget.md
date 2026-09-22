# Hindsight Memory Remove and Forget

## Overview

Hindsight has two different meanings for “remove” and “forget”: **forget** is reversible curation of one raw fact, while **remove** is destructive deletion of a document, a bank, or all memories in a bank. They must not be treated as the same operation.

## Capability matrix

| Intent | Public surface | Scope | Reversible? | Result |
| --- | --- | --- | --- | --- |
| Forget a fact | `PATCH /v1/default/banks/{bank_id}/memories/{memory_id}` with `state="invalidated"`; MCP `invalidate_memory` | One `world` or `experience` fact | Yes, with `state="valid"` or `restore=true` | Fact leaves active recall/consolidation/graph surfaces but remains in the archive for audit |
| Correct a fact | Same PATCH route with text/context/date/type/entity fields; MCP `update_memory` | One raw fact | Effectively no automatic undo | Re-embeds the fact, removes stale derived observations/links, and re-consolidates/rebuilds graph state |
| Remove a document | `DELETE /v1/default/banks/{bank_id}/documents/{document_id}`; MCP `delete_document`; CLI `hindsight document delete` | One source document and its extracted memories | No | Deletes the document, its memory units, and associated links; cleans dependent derived state |
| Clear memories | `DELETE /v1/default/banks/{bank_id}/memories?type=...`; MCP `clear_memories` | All memories in a bank, or one fact type | No | Deletes memories while preserving the bank profile; `type` can target `world`, `experience`, or `observation` |
| Delete a bank | `DELETE /v1/default/banks/{bank_id}`; MCP `delete_bank`; CLI bank deletion | Entire bank | No | Deletes the bank profile and bank-scoped memories, documents, entities, links, archives, and related data |

## Forget: reversible invalidation

The supported “forget this fact” operation is memory curation, not physical deletion. The PATCH request accepts `state="invalidated"` and an optional `reason`; restoring uses `state="valid"`. Only raw `world` and `experience` facts can be curated because observations are derived memories and are regenerated from their sources. See `hindsight-api-slim/hindsight_api/api/http.py:5611-5665`, `hindsight-api-slim/hindsight_api/engine/memory_engine.py:11005-11090`, and `hindsight-api-slim/hindsight_api/mcp_tools.py:3669-3732`.

The PostgreSQL implementation moves the live row from `memory_units` to `invalidated_memory_units`. Before the move it snapshots entity IDs and retain-time causal-link descriptors; deleting the live row then cascades its active entity postings and temporal/semantic links. The archive stores the invalidation reason and timestamp, but is cold storage and does not keep the live embedding. See `hindsight-api-slim/hindsight_api/engine/memories/pg/writes.py:397-430` and `hindsight-api-slim/hindsight_api/engine/memories/base.py:1771-1804`.

After invalidation, Hindsight removes observations that depend on the retired source, resets surviving co-source facts for re-consolidation, queues graph maintenance, refreshes projections grounded in the removed fact, and performs vector-index maintenance. This keeps the active recall path clean without requiring every query to add a “not invalidated” predicate. See `hindsight-api-slim/hindsight_api/engine/memory_engine.py:11425-11447`, `hindsight-api-slim/hindsight_api/engine/memory_engine.py:10143-10227`, and `hindsight-docs/docs/developer/api/memories.mdx:159-203`.

Restore is the reverse lifecycle: the archived row returns to `memory_units`, the search vector and embedding are rebuilt, consolidation is reset, surviving entity postings and saved causal links are restored, and graph maintenance is queued. Some connected entities or peers may have been permanently removed while the fact was archived, so restore rematerializes only what still exists. See `hindsight-api-slim/hindsight_api/engine/memories/pg/writes.py:445-565` and `hindsight-api-slim/hindsight_api/engine/memory_engine.py:11448-11488`.

Invalidation does **not** modify the source document. Reprocessing that document extracts fresh facts and therefore can reset prior curation; use invalidation for residue, and fix systematic extraction problems at the mission/configuration level. See `hindsight-docs/docs/developer/api/memories.mdx:200-208`.

## Remove: destructive deletion

### Document deletion

`DELETE /v1/default/banks/{bank_id}/documents/{document_id}` is permanent. It deletes the document and all memory units extracted from it, with database cascades removing their links and entity associations. Hindsight also runs the stale-observation sweep after deletion so observations inserted concurrently by consolidation cannot survive with deleted sources; it then invalidates affected caches and schedules consolidation, graph maintenance, vector maintenance, and refreshes for derived documents that cited the removed grounding. See `hindsight-api-slim/hindsight_api/api/http.py:7628-7668` and `hindsight-api-slim/hindsight_api/engine/memory_engine.py:9578-9760`.

### Bank-memory clearing

`DELETE /v1/default/banks/{bank_id}/memories` calls `delete_bank(..., delete_bank_profile=False)`, so the bank remains available while its memories are deleted. A `type` query parameter narrows the destructive operation to `world`, `experience`, or `observation`. Type-scoped clearing also removes matching rows from `invalidated_memory_units`; clearing observations explicitly removes observation history. See `hindsight-api-slim/hindsight_api/api/http.py:9479-9505` and `hindsight-api-slim/hindsight_api/engine/memory_engine.py:10419-10691`.

### Whole-bank deletion

`DELETE /v1/default/banks/{bank_id}` permanently removes the bank profile and bank-scoped data. The engine deletes documents, live memories, observation history, invalidated-memory archive rows, entities, extension-owned bank tables, and finally the bank row; it also drops per-bank vector indexes and, for an external memory store, drops the bank storage. See `hindsight-api-slim/hindsight_api/api/http.py:8018-8040` and `hindsight-api-slim/hindsight_api/engine/memory_engine.py:10535-10668`.

## Important boundary: individual physical memory deletion

The engine still contains internal `delete_memory_unit` and bulk `delete_memory_units` lifecycle helpers for maintenance and cleanup, including the same link cascade, stale-observation sweep, graph maintenance, cache invalidation, and vector maintenance. See `hindsight-api-slim/hindsight_api/engine/memory_engine.py:10068-10227`.

However, the current public surfaces do not expose an individual destructive memory-delete operation: the HTTP API exposes PATCH curation rather than `DELETE /memories/{id}`, MCP registers `update_memory` and `invalidate_memory` but not `delete_memory`, and the CLI deliberately returns “Individual memory deletion is no longer supported; use `memory clear`”. See `hindsight-api-slim/hindsight_api/mcp.py:130-162`, `hindsight-api-slim/hindsight_api/mcp_tools.py:647-652`, and `hindsight-cli/src/api.rs:441-452`.

## Practical decision rule

- Use **invalidate / forget** when the fact is wrong, stale, duplicated, or should be hidden from active reasoning but retained for audit and possible restoration.
- Use **document delete** when the source document itself must be removed together with every fact extracted from it.
- Use **clear memories** when the bank should survive but its memory contents must be wiped, optionally by fact type.
- Use **bank delete** when the tenant/bank and all of its data must be destroyed.
- Do not call the internal single-memory delete helper as a public contract; for a user-facing single-fact “forget” flow, use reversible invalidation.

## Source map

- HTTP curation and destructive routes: `hindsight-api-slim/hindsight_api/api/http.py:5611-5665`, `hindsight-api-slim/hindsight_api/api/http.py:7628-7668`, `hindsight-api-slim/hindsight_api/api/http.py:8018-8040`, and `hindsight-api-slim/hindsight_api/api/http.py:9479-9505`.
- Engine lifecycle orchestration: `hindsight-api-slim/hindsight_api/engine/memory_engine.py:9578-9760`, `hindsight-api-slim/hindsight_api/engine/memory_engine.py:10068-10227`, and `hindsight-api-slim/hindsight_api/engine/memory_engine.py:10419-10691`.
- Archive move/restore implementation: `hindsight-api-slim/hindsight_api/engine/memories/pg/writes.py:397-565`.
- MCP tool contract: `hindsight-api-slim/hindsight_api/mcp_tools.py:3541-3732` and `hindsight-api-slim/hindsight_api/mcp_tools.py:3873-3929`.
- User-facing documentation: `hindsight-docs/docs/developer/api/memories.mdx:159-208` and `hindsight-docs/docs/developer/api/documents.mdx:157-182`.
