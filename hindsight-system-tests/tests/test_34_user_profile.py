"""A user profile is the mental-model feature pointed at the user.

Hindsight has no dedicated profile endpoint: a user profile is a mental model
with the conventional id ``user-profile``, whose source query asks the reflect
agent to synthesise who the user is from the bank's memories. Creating it runs
that query through the same reflect loop any other mental model uses, reading it
is a database fetch that recomputes nothing, and a refresh after new memories
rewrites it from the moved facts. This story pins that cycle for one user —
openclaw, whose memories live in the ``user-openclaw`` bank, the one-bank-per-user
layout the quick start example uses.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator

import pytest
from hindsight_client import Hindsight

from hindsight_system_tests import reflect_loop
from hindsight_system_tests.payloads import consolidation, extracted, fact

pytestmark = pytest.mark.asyncio

USER_PROFILE_ID = "user-profile"
USER_PROFILE_SOURCE_QUERY = (
    "Build a factual profile of the user from retrieved memories only. Include confirmed background, "
    "preferences, and goals. Treat repeated memories as duplicate evidence, not independent corroboration. "
    "Do not attribute the bank's name, mission, background, or disposition settings to the user. "
    "Mark missing information as unknown and do not infer unsupported details."
)
FIRST_PROFILE = "openclaw is a backend engineer at Acme who prefers Rust."
SECOND_PROFILE = "openclaw is a backend engineer at Acme who prefers Rust and is learning Japanese."


@pytest.fixture
async def openclaw_bank(client: Hindsight) -> AsyncIterator[str]:
    """One bank per user: openclaw's memories live in ``user-openclaw``.

    Prefixed with ``systest-`` so the session-start sweep still catches a run
    killed mid-test, and deleted here for the same isolation ``bank_id`` gives.
    """
    bank = f"systest-user-openclaw-{uuid.uuid4().hex[:8]}"
    yield bank
    with contextlib.suppress(Exception):
        await client.banks.delete_bank(bank)


@pytest.fixture
async def profile(client: Hindsight, llm, openclaw_bank: str, settled) -> str:
    """openclaw's ``user-profile`` model, already generated from their memories."""
    llm.on_step("extract_facts", contains="Rust").returns(
        extracted(
            fact("openclaw works at Acme as a backend engineer", who="openclaw", entities=["openclaw", "Acme"]),
            fact("openclaw prefers Rust", who="openclaw", entities=["openclaw", "Rust"]),
        )
    )
    llm.on_step("consolidate").returns(consolidation())
    reflect_loop(llm, answer=FIRST_PROFILE)

    await client.aretain(
        bank_id=openclaw_bank,
        content="openclaw works at Acme as a backend engineer. openclaw prefers Rust.",
    )
    await settled(openclaw_bank)

    created = await client.mental_models.create_mental_model(
        openclaw_bank,
        {
            "id": USER_PROFILE_ID,
            "name": "User Profile",
            "source_query": USER_PROFILE_SOURCE_QUERY,
        },
    )
    assert created.mental_model_id == USER_PROFILE_ID
    await settled(openclaw_bank)
    return created.mental_model_id


async def test_generating_a_profile_synthesises_the_users_memories(client, openclaw_bank, profile):
    """Create runs the source query through reflect, so the profile lands as
    content drawn from what the bank actually holds — not as a placeholder."""
    model = await client.mental_models.get_mental_model(openclaw_bank, profile, detail="full")

    assert model.id == USER_PROFILE_ID, "the conventional id is what callers address the profile by"
    assert model.content.strip() == FIRST_PROFILE


async def test_getting_the_profile_recomputes_nothing(client, llm, openclaw_bank, profile):
    """Reading is the cheap half of the feature: the answer is already written,
    so a get is a database read. Any further reflect turn would go unscripted
    and fail the test, because the rulebook is not reset mid-test — which is
    precisely the assertion."""
    first = await client.mental_models.get_mental_model(openclaw_bank, profile, detail="content")
    second = await client.mental_models.get_mental_model(openclaw_bank, profile, detail="content")

    assert first.content == second.content == f"{FIRST_PROFILE}\n"


async def test_a_refresh_pulls_new_memories_into_the_profile(client, llm, openclaw_bank, profile, settled):
    """The profile is not a snapshot: retain more memories about the user,
    refresh, and the same source query synthesises the wider picture."""
    llm.reset()
    llm.on_step("extract_facts", contains="Japanese").returns(
        extracted(fact("openclaw is learning Japanese", who="openclaw", entities=["openclaw", "Japanese"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    reflect_loop(llm, answer=SECOND_PROFILE)

    await client.aretain(bank_id=openclaw_bank, content="openclaw is learning Japanese.")
    await settled(openclaw_bank)
    await client.mental_models.refresh_mental_model(openclaw_bank, profile)
    await settled(openclaw_bank)

    model = await client.mental_models.get_mental_model(openclaw_bank, profile, detail="full")
    assert model.content.strip() == SECOND_PROFILE
    assert model.is_stale is False
