# Read-Only External Profile: Investigation History

## Overview

This record traces how the read-only external profile design converged on the current split (agent-side authoritative copy + Hindsight memory copy, see `read-only-external-profile.md`) — which server-side protection options were evaluated against the real source, which one was actually built and verified live, and why it was ultimately removed in favor of the simpler agent-side design. Source citations are relative to `hindsight-api-slim/hindsight_api/` on the `dev` branch; the design reviews were run as Codex (g-c) consults on 2026-09-17, session `01a0ae11-6de9-7671-ae5c-afc105618768`.

The requirement throughout: an external system owns a user's medical profile and pushes it into Hindsight so the agent's answers reflect a richer understanding of the user; Hindsight's authority over the profile is read-only — its content must never be modified from inside Hindsight, and when the external profile changes, the update is re-pushed into the same resource.

## 1. The Original Single-Carrier Design and Its Break

The first proposal stored the profile as one ordinary document in the same bank as agent conversation memories (one person, one bank), protected by a document-scoped OperationValidator extension: deny writes whose target is the profile document for every principal except the sync service. Codex round 1 broke it on two findings, both verified against source:

1. **The validator cannot see the target.** `BankWriteContext` carries only `bank_id`, `operation`, and `request_context` (`extensions/operation_validator.py:447-452`); `delete_document` and `update_memory_unit` discard their target ids when constructing it (`engine/memory_engine.py:9600-9603, 11105-11108`). A validator can deny an operation bank-wide or allow it bank-wide — it cannot distinguish the profile document from conversation memories in the same bank. Protecting the document therefore means denying agent curation entirely, which is a must-have core capability, not a negotiable one.
2. **Retain is its own write hole.** Retain validates through a separate `validate_retain` hook whose `RetainContext` carries per-item `document_id`s (`extensions/operation_validator.py:155-166`) — but the top-level `document_id` field is not reliably populated on the async path; the ids live in `contents` (`engine/memory_engine.py:5410-5419, 20960-20965`). An agent could replace or append to the fixed profile id through an ordinary retain unless that hook reserves it.

Round 1 also corrected two details in the original write-up: the extension env var is `HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION` (suffixed; `extensions/loader.py:49-61`), and `replace` mode deletes and rewrites rather than tombstoning, with observation re-derivation asynchronous and conditional (`engine/memory_engine.py:5729-5739`) — `force_reextract` is needed when identical text must re-extract.

## 2. The Engine-Change Alternative, Sized

With document-scoped protection impossible via the existing hook, the next candidate was an engine change: add optional `document_id`/`memory_id` fields to `BankWriteContext`, populate them at the document/memory-scoped call sites, resolve `memory_id → document_id` (including archived rows, which do carry `document_id`, `engine/memories/pg/writes.py:359-373`), and let the external guard deny only writes whose resolved target is the profile. Codex round 2 sized it and found the five proposed call sites insufficient — real additional gaps:

1. `DELETE_BANK` (and MCP `clear_memories`, which routes there) wipes profile facts with no document target to match — destructive whole-bank operations still need bank-level denial.
2. Document import (`import_documents_async`, `api/http.py:8337-8358` → `engine/memory_engine.py:7186-7213` → `engine/transfer/importer.py:955-968`) replaces documents with no retain/write validation at all.
3. Engine-level single/bulk deletion (`engine/memory_engine.py:10100-10159, 10301-10354`) has no validator gate.
4. `retry_operation` (`engine/memory_engine.py:20060-20092`) replays a stored job under its original persisted principal — an agent permitted to retry could replay an old sync write.

Sound design, but a real PR: dataclass fields, ~5 call sites, target resolution with live+archived rows, and guards for import/deletion/retry — before any of the policy lives in the extension.

## 3. The Directive-Copy Design: Built, Verified, and Its Cost

Round 3 re-examined the no-engine-change options under tightened constraints (one bank per person, no engine changes, curation preserved) and surfaced the decisive structural fact: **the directives table has no engine-internal writers.** Its only writers are the three validated CRUD methods (`engine/memory_engine.py:19496-19673`); the bank-template import preauthorizes and routes through them (`api/http.py:3930-3948`, `engine/memory_engine.py:13661-13671`); the single exception — whole-bank restore writing directives directly (`engine/transfer/importer.py:702-718, 804-809`) — requires a nonexistent target bank. Directive content is injected into reflect prompts with "NEVER violate" priority (`engine/reflect/prompts.py:40-76`). So a directive *can* be made read-only with a validator that only needs operation names — the one dimension `BankWriteContext` does carry. `reflect_mission`/bank-config was evaluated and rejected as a carrier (role-section text, LLM-rewritten by `MERGE_BANK_MISSION`, not evidential content).

The hybrid design that followed: the profile stored twice in the same bank — a directive copy (authoritative, sync-service-writable only) for reflect, plus an ordinary memory copy (fixed `document_id` + `replace`) for recall. This was implemented as `tests/profile_guard_draft.py` (the guard: deny `CREATE/UPDATE/DELETE_DIRECTIVE` + `DELETE_BANK` + bank creation to non-sync principals, pass-through retain/recall/reflect) and a 16-test acceptance probe (`tests/test_profile_guard.py`), all passing against a real MemoryEngine (pg0 + MockLLM). It was then deployed to the local running service (env vars in the checkout `.env`, guard module copied alongside, service restarted via `~/.hindsight/bin/start-hindsight.sh`) and verified live with eight real HTTP probes: agent directive writes 403 with the guard's reason, sync writes 200 with in-place updates, agent retain/recall/curation on existing banks 200.

The removal decision followed from its one unavoidable cost: closing the restore route requires denying bank creation to every non-sync caller — including the control plane — while in normal use the users themselves create banks. That behavioral restriction is inherent to the design (a preprovisioned-bank world), not an implementation wart. Combined with the observation that agent-side reflect injection covers the authoritative-consumption need entirely (reflect's user message is the caller's query, `engine/reflect/prompts.py:139`, documented as out-ranking the system prompt, #3776), the server-side authoritative copy became unnecessary. The guard, its env vars, the copied module, and the two test files were removed; the local service was restarted clean and bank/directive creation verified restored (200 without any sync key).

## 4. Lessons Kept from the Implementation

The guard no longer ships, but what building and running it taught remains valuable for any future OperationValidator work:

1. **A guard that runs is not a guard that blocks.** The first version compared operation names against a string deny-set, but `BankWriteOperation` is a StrEnum with lowercase values (`CREATE_DIRECTIVE = "create_directive"`) — nothing matched and directive protection silently failed until the acceptance test asserted the *denied* path with its rejection reason. Compare against enum members; test denials, not just loads.
2. **`OperationValidatorExtension` is abstract over the core hooks** — a write-only guard still implements pass-throughs for `validate_retain`/`validate_recall`/`validate_reflect` or instantiation fails at load time.
3. **`retain_batch_async` and `retain_async` return different things** (submission results vs unit ids); when a test needs a unit id to curate, use `retain_async` (it takes `document_id`) or read ids back via `list_memory_units(document_id=...)`.
4. **Assert the state after rejection, not just the raise.** Denial-raises and content-untouched are two different properties; a guard that partially wrote before rejecting passes the first and fails the second.
5. **`preview_prompt(bank_id, "reflect")` renders the exact next reflect system prompt deterministically** — the right surface for prompt-content claims, no LLM needed; model *compliance* is a separate, LLM-judge-shaped question.
6. **The unsuffixed env var (`HINDSIGHT_API_OPERATION_VALIDATOR` without `_EXTENSION`) silently loads nothing** — the one failure mode that raises no error anywhere; deployment acceptance must include an unauthorized write actually failing.
7. **Background execution reconstructs `RequestContext` with persisted ids (`api_key_id`, `tenant_id`) and no raw key** (`engine/memory_engine.py:3001-3019`) — a principal check comparing raw bearer keys breaks authorized async writes, and `internal=True` must never be treated as authority.

## 5. Why the Current Design Won

Stated as the decision, not the chronology:

1. **The requirement's real subject is the answers, not the store.** "Hindsight has read-only authority over the profile" was a means to "the agent's answers carry the authoritative profile." Agent-side injection achieves the end directly, and makes the read-only property trivially true — nothing authoritative exists inside Hindsight to protect.
2. **Every server-side protection design paid a permanent cost for a contingent threat.** Document-scoped protection needs engine changes plus a bypass-closing campaign; directive protection needs sync-only bank creation. The recall-side memory copy needs no protection at all once authority leaves the server.
3. **One bank per person and agent curation were non-negotiable**, and both server-side designs strained against them — the engine-change route against complexity, the directive route against bank-creation freedom.

The remaining trade-offs the current design accepts knowingly: reflect pays the profile text as prompt tokens on every call; each consumer owns its copy's freshness; recall-path answers stay non-authoritative; and the injection framing ("treat as facts, not instructions") is a caller discipline, not a server guarantee.
