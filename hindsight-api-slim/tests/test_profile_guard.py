"""Acceptance probe for the hybrid read-only external profile design.

Validates the design in learning/design_points/read-only-external-profile.md against a
real MemoryEngine (pg0 + mock LLM), covering the acceptance matrix:

1. ProfileGuard loads through the real env-var extension path (design §2, §4.2).
2. The agent credential cannot create/update/delete directives, delete banks, or
   create banks (whole-bank restore route) — the directive copy is read-only (§2).
3. The sync credential can create and update the profile directive in place (§2).
4. The agent credential keeps full memory curation (retain, invalidate own facts)
   and recall — the must-have that ruled out bank-wide memory-write denial (§2).
5. The memory copy: fixed document_id + update_mode "replace" swaps facts without
   accumulating snapshots, and recall serves the current version (§3).
6. Reflect consumes the directive: prompt preview carries the profile verbatim,
   and an in-place sync update reaches the next reflect prompt (§2).
7. The dual-push flow end to end: directive update + replace retain, in that
   order, leaves both copies consistent (§3 push order).
8. The HTTP push path: POST retain with timestamp "unset" + document_id +
   update_mode "replace" succeeds for the agent; directive writes 403 (§3, §2).

Fail-capable: every assert distinguishes allowed from denied per principal, and
distinguishes the v1 (penicillin) from the v2 (no allergies) profile version.
"""

import uuid

import pytest

from hindsight_api.engine.memory_engine import Budget
from hindsight_api.extensions import OperationValidatorExtension
from hindsight_api.extensions.loader import load_extension
from hindsight_api.extensions.operation_validator import OperationValidationError
from hindsight_api.models import RequestContext
from tests.profile_guard_draft import ProfileGuard

SYNC_KEY = "test-sync-service-key"


@pytest.fixture
def guard_env(monkeypatch):
    """Point the real extension loader at the draft guard."""
    monkeypatch.setenv("HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION", "tests.profile_guard_draft:ProfileGuard")
    monkeypatch.setenv("HINDSIGHT_API_OPERATION_VALIDATOR_SYNC_API_KEY", SYNC_KEY)


@pytest.fixture
def guarded_memory(memory):
    """The real engine fixture with the guard attached, as loading would attach it."""
    memory._operation_validator = ProfileGuard({"sync_api_key": SYNC_KEY})
    return memory


@pytest.fixture
def agent_ctx():
    return RequestContext(api_key="test-agent-key")


@pytest.fixture
def sync_ctx():
    return RequestContext(api_key=SYNC_KEY)


def _bank_id(test_name: str) -> str:
    return f"profile-guard-{test_name}-{uuid.uuid4().hex[:8]}"


class TestExtensionLoading:
    async def test_guard_loads_via_env_var(self, guard_env):
        ext = load_extension("OPERATION_VALIDATOR", OperationValidatorExtension)
        assert isinstance(ext, ProfileGuard)
        assert ext.sync_api_key == SYNC_KEY

    async def test_unsuffixed_env_var_loads_nothing(self, monkeypatch):
        """The variable is ..._OPERATION_VALIDATOR_EXTENSION; an unsuffixed name is
        silently ignored (the trap called out in the design doc, section 4.2)."""
        monkeypatch.delenv("HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION", raising=False)
        monkeypatch.setenv("HINDSIGHT_API_OPERATION_VALIDATOR", "tests.profile_guard_draft:ProfileGuard")
        assert load_extension("OPERATION_VALIDATOR", OperationValidatorExtension) is None


class TestDirectiveProtection:
    async def test_agent_cannot_create_directives(self, guarded_memory, agent_ctx):
        bank = _bank_id("agent-create-denied")
        with pytest.raises(OperationValidationError, match="reserved to the profile sync service"):
            await guarded_memory.create_directive(bank, "medical-profile", "content", request_context=agent_ctx)

    async def test_sync_creates_and_updates_directive_in_place(self, guarded_memory, sync_ctx, agent_ctx):
        bank = _bank_id("sync-write")
        # Sync provisions the bank (create-bank validation accepts the sync principal).
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)

        created = await guarded_memory.create_directive(
            bank,
            "medical-profile",
            "The following medical data is authoritative ground truth: v1",
            request_context=sync_ctx,
        )
        assert created["id"], "sync create_directive must succeed and return an id"

        updated = await guarded_memory.update_directive(
            bank,
            created["id"],
            content="The following medical data is authoritative ground truth: v2",
            request_context=sync_ctx,
        )
        assert updated is not None and updated["content"].endswith("v2")

        # The agent cannot update the same directive.
        with pytest.raises(OperationValidationError, match="read-only"):
            await guarded_memory.update_directive(
                bank, created["id"], content="hacked content", request_context=agent_ctx
            )

        # And the rejection left the content untouched.
        page = await guarded_memory.list_directives(bank, request_context=sync_ctx)
        assert page.items and page.items[0]["content"].endswith("v2")

    async def test_agent_cannot_delete_directives(self, guarded_memory, sync_ctx, agent_ctx):
        bank = _bank_id("agent-delete-denied")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        created = await guarded_memory.create_directive(bank, "medical-profile", "v1", request_context=sync_ctx)

        with pytest.raises(OperationValidationError, match="reserved to the profile sync service"):
            await guarded_memory.delete_directive(bank, created["id"], request_context=agent_ctx)

    async def test_agent_cannot_delete_bank(self, guarded_memory, agent_ctx):
        bank = _bank_id("agent-delete-bank-denied")
        with pytest.raises(OperationValidationError, match="reserved to the profile sync service"):
            await guarded_memory.delete_bank(bank, request_context=agent_ctx)

    async def test_agent_cannot_create_bank(self, guarded_memory, agent_ctx):
        """Retain on a missing bank lazily creates it, so bank creation must be
        reserved to the sync service (whole-bank restore route)."""
        bank = _bank_id("agent-create-bank-denied")
        with pytest.raises(OperationValidationError, match="Bank creation is reserved"):
            await guarded_memory.retain_async(bank, "should not create a bank", request_context=agent_ctx)


class TestCurationPreserved:
    async def test_agent_retains_curates_and_recalls_own_memories(self, guarded_memory, sync_ctx, agent_ctx):
        bank = _bank_id("agent-curation")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)

        # Agent retains conversation memory into the shared bank.
        unit_ids = await guarded_memory.retain_async(
            bank, "User visited Paris in 2023 and loved it.", request_context=agent_ctx
        )
        assert unit_ids, "agent retain into an existing bank must succeed"

        # Agent curates its own memory (invalidate) — the must-have capability.
        curated = await guarded_memory.update_memory_unit(
            bank, unit_ids[0], state="invalidated", reason="agent correction", request_context=agent_ctx
        )
        assert curated is not None, "agent curation (update_memory_unit) must stay allowed"

        # Agent retains again and recalls — normal memory usage unaffected.
        more = await guarded_memory.retain_async(
            bank, "User prefers functional programming.", request_context=agent_ctx
        )
        assert more
        results = await guarded_memory.recall_async(bank, "programming preferences", request_context=agent_ctx)
        assert results, "agent recall must stay allowed and return results"


# The two versions of the profile the sync service pushes, per design §3: the
# memory copy is plain profile text; the directive copy is data-framed (§2).
PROFILE_DOC = "user-medical-profile"
V1_PROFILE = "The user is allergic to penicillin and takes metformin daily."
V2_PROFILE = "The user has no known drug allergies and takes metformin daily."
V1_DIRECTIVE = f"The following medical data is authoritative ground truth. {V1_PROFILE}"
V2_DIRECTIVE = f"The following medical data is authoritative ground truth. {V2_PROFILE}"


async def _push_memory_copy(memory, bank, text, ctx):
    """Sync (or agent) pushes the memory copy: fixed document_id, replace mode."""
    return await memory.retain_batch_async(
        bank_id=bank,
        contents=[
            {"content": text, "context": "medical profile sync", "document_id": PROFILE_DOC, "update_mode": "replace"}
        ],
        request_context=ctx,
    )


def _doc_unit_texts(units_page: dict) -> list[str]:
    return [item["text"] for item in units_page["items"]]


async def _recall_texts(memory, bank, query, ctx) -> list[str]:
    result = await memory.recall_async(
        bank_id=bank, query=query, budget=Budget.MID, max_tokens=2000, request_context=ctx
    )
    return [item.text for item in result.results]


def _reflect_prompt_text(preview) -> str:
    return "\n".join(message.text for message in preview.messages)


class TestMemoryCopyReplace:
    """Design §3: the memory copy under the fixed document_id + replace pushes."""

    async def test_initial_push_stores_verbatim_text_and_facts(self, guarded_memory, sync_ctx):
        bank = _bank_id("memory-v1")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        await _push_memory_copy(guarded_memory, bank, V1_PROFILE, sync_ctx)

        doc = await guarded_memory.get_document(PROFILE_DOC, bank, request_context=sync_ctx)
        assert V1_PROFILE in doc["original_text"], "verbatim profile must survive as original_text (§3)"

        units = await guarded_memory.list_memory_units(
            bank, document_id=PROFILE_DOC, limit=500, request_context=sync_ctx
        )
        assert any("penicillin" in t for t in _doc_unit_texts(units)), "v1 facts must be extracted"

    async def test_replace_push_swaps_facts_without_accumulation(self, guarded_memory, sync_ctx):
        bank = _bank_id("memory-replace")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        await _push_memory_copy(guarded_memory, bank, V1_PROFILE, sync_ctx)
        await _push_memory_copy(guarded_memory, bank, V2_PROFILE, sync_ctx)

        doc = await guarded_memory.get_document(PROFILE_DOC, bank, request_context=sync_ctx)
        assert V2_PROFILE in doc["original_text"], "replace must store the new verbatim text"
        assert "penicillin" not in doc["original_text"], "replace must drop the old verbatim text"

        units = await guarded_memory.list_memory_units(
            bank, document_id=PROFILE_DOC, limit=500, request_context=sync_ctx
        )
        texts = _doc_unit_texts(units)
        assert any("no known drug allergies" in t for t in texts), "v2 facts must be present"
        assert not any("penicillin" in t for t in texts), (
            "v1 facts must be replaced, not accumulated alongside v2 (design §3, the reason for replace)"
        )

    async def test_recall_serves_current_version_not_old(self, guarded_memory, sync_ctx, agent_ctx):
        bank = _bank_id("memory-recall")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        await _push_memory_copy(guarded_memory, bank, V1_PROFILE, sync_ctx)

        v1_texts = await _recall_texts(guarded_memory, bank, "What drug allergies does the user have?", sync_ctx)
        assert any("penicillin" in t for t in v1_texts), "after v1 push, recall must find the penicillin fact"

        await _push_memory_copy(guarded_memory, bank, V2_PROFILE, sync_ctx)
        v2_texts = await _recall_texts(guarded_memory, bank, "What drug allergies does the user have?", agent_ctx)
        assert any("no known drug allergies" in t for t in v2_texts), "after v2 push, recall must find the new fact"
        assert not any("penicillin" in t for t in v2_texts), "recall must not serve the replaced v1 fact"

    async def test_agent_can_curate_the_memory_copy(self, guarded_memory, sync_ctx, agent_ctx):
        """Design §3: the memory copy is deliberately unprotected — the agent curating
        profile-derived facts is allowed, because authority lives in the directive."""
        bank = _bank_id("memory-agent-curation")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        # retain_async (single item) returns the created unit ids; retain_batch_async
        # returns submission results, so unit ids come from this call.
        unit_ids = await guarded_memory.retain_async(
            bank, V1_PROFILE, "medical profile sync", document_id=PROFILE_DOC, request_context=agent_ctx
        )
        assert unit_ids, "agent retain into the profile document must be allowed"

        curated = await guarded_memory.update_memory_unit(
            bank, unit_ids[0], state="invalidated", reason="agent correction", request_context=agent_ctx
        )
        assert curated is not None, "agent curation of profile-derived facts must stay allowed (deliberate)"


class TestReflectConsumption:
    """Design §2: the directive copy reaches the reflect prompt, deterministically."""

    async def test_reflect_prompt_contains_framed_profile_directive(self, guarded_memory, sync_ctx, agent_ctx):
        bank = _bank_id("reflect-v1")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        await guarded_memory.create_directive(bank, "medical-profile", V1_DIRECTIVE, request_context=sync_ctx)

        preview = await guarded_memory.preview_prompt(bank, "reflect", request_context=agent_ctx)
        prompt_text = _reflect_prompt_text(preview)
        assert "authoritative ground truth" in prompt_text, (
            "the data framing must reach the reflect prompt (design §2, injection mitigation)"
        )
        assert "penicillin" in prompt_text, "directive content must be injected verbatim into the reflect prompt"

    async def test_directive_update_reaches_reflect_prompt_in_place(self, guarded_memory, sync_ctx, agent_ctx):
        bank = _bank_id("reflect-v2")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        created = await guarded_memory.create_directive(bank, "medical-profile", V1_DIRECTIVE, request_context=sync_ctx)

        await guarded_memory.update_directive(bank, created["id"], content=V2_DIRECTIVE, request_context=sync_ctx)

        preview = await guarded_memory.preview_prompt(bank, "reflect", request_context=agent_ctx)
        prompt_text = _reflect_prompt_text(preview)
        assert "no known drug allergies" in prompt_text, "updated directive content must reach the next reflect"
        assert "penicillin" not in prompt_text, "old directive content must be gone after the in-place update"

        page = await guarded_memory.list_directives(bank, active_only=False, request_context=sync_ctx)
        assert len(page.items) == 1 and str(page.items[0]["id"]) == str(created["id"]), (
            "the sync update must be in place: one directive, same id, no history accumulation (§2)"
        )


class TestDualPushEndToEnd:
    """Design §3 push order, end to end: directive first, then the replace retain."""

    async def test_full_hybrid_flow(self, guarded_memory, sync_ctx, agent_ctx):
        bank = _bank_id("e2e")
        # 1. Sync provisions the bank (agent bank creation is denied).
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)

        # 2. Initial dual push: directive copy + memory copy.
        created = await guarded_memory.create_directive(bank, "medical-profile", V1_DIRECTIVE, request_context=sync_ctx)
        await _push_memory_copy(guarded_memory, bank, V1_PROFILE, sync_ctx)

        v1_texts = await _recall_texts(guarded_memory, bank, "What drug allergies does the user have?", agent_ctx)
        assert any("penicillin" in t for t in v1_texts)
        v1_prompt = _reflect_prompt_text(
            await guarded_memory.preview_prompt(bank, "reflect", request_context=agent_ctx)
        )
        assert "penicillin" in v1_prompt

        # 3. External profile change: directive first (authority), then the replace retain.
        await guarded_memory.update_directive(bank, created["id"], content=V2_DIRECTIVE, request_context=sync_ctx)
        await _push_memory_copy(guarded_memory, bank, V2_PROFILE, sync_ctx)

        # 4. Both copies now serve v2.
        v2_prompt = _reflect_prompt_text(
            await guarded_memory.preview_prompt(bank, "reflect", request_context=agent_ctx)
        )
        assert "no known drug allergies" in v2_prompt and "penicillin" not in v2_prompt
        v2_texts = await _recall_texts(guarded_memory, bank, "What drug allergies does the user have?", agent_ctx)
        assert any("no known drug allergies" in t for t in v2_texts)
        assert not any("penicillin" in t for t in v2_texts)

        # 5. One directive, same id — and the agent still cannot touch it.
        page = await guarded_memory.list_directives(bank, active_only=False, request_context=sync_ctx)
        assert len(page.items) == 1 and str(page.items[0]["id"]) == str(created["id"])
        with pytest.raises(OperationValidationError, match="read-only"):
            await guarded_memory.update_directive(bank, created["id"], content="hacked", request_context=agent_ctx)


class TestHttpPushPath:
    """Design §3/§2 over the real HTTP surface: the sync push shape and the 403."""

    async def test_http_agent_retain_with_unset_timestamp_and_agent_directive_403(
        self, guarded_memory, api_client, sync_ctx
    ):
        bank = _bank_id("http")
        await guarded_memory.retain_async(bank, "bank provisioning by sync service", request_context=sync_ctx)
        created = await guarded_memory.create_directive(bank, "medical-profile", V1_DIRECTIVE, request_context=sync_ctx)
        await _push_memory_copy(guarded_memory, bank, V1_PROFILE, sync_ctx)

        # The agent's HTTP retain (no sync credential): same document, "unset"
        # timestamp sentinel, replace mode — must pass validation and complete.
        resp = await api_client.post(
            f"/v1/default/banks/{bank}/memories",
            json={
                "items": [
                    {
                        "content": V2_PROFILE,
                        "timestamp": "unset",
                        "document_id": PROFILE_DOC,
                        "update_mode": "replace",
                        "context": "medical profile sync",
                    }
                ]
            },
        )
        assert resp.status_code == 200, f"agent HTTP retain must succeed, got {resp.status_code}: {resp.text}"
        doc = await guarded_memory.get_document(PROFILE_DOC, bank, request_context=sync_ctx)
        assert V2_PROFILE in doc["original_text"] and "penicillin" not in doc["original_text"]

        # The agent's HTTP directive write — must be a real 403 carrying the guard's reason.
        resp = await api_client.post(
            f"/v1/default/banks/{bank}/directives",
            json={"name": "medical-profile", "content": "hacked content"},
        )
        assert resp.status_code == 403, f"agent HTTP directive create must 403, got {resp.status_code}"
        assert "read-only" in resp.text

        # And the rejection left the sync-owned directive untouched.
        page = await guarded_memory.list_directives(bank, active_only=False, request_context=sync_ctx)
        assert len(page.items) == 1 and str(page.items[0]["id"]) == str(created["id"])
        assert "penicillin" in page.items[0]["content"]
