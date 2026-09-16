"""Run a retain -> recall -> user-profile flow against Hindsight.

Prerequisites (from the repository root):

1. Bootstrap the development environment once and configure the LLM credentials
   requested in ``.env``::

       ./scripts/dev/setup.sh

2. Start the API and Control Plane in terminal 1::

       ./scripts/dev/start.sh

   The API should report ready at http://localhost:8888. The default local
   database is embedded pg0, so a separate PostgreSQL or Docker service is not
   required.

3. Run this example in terminal 2::

       uv run python learning/quick_start/quick_start.py

   To connect to a different API address, set ``HINDSIGHT_API_URL``::

       HINDSIGHT_API_URL=http://localhost:8080 \
         uv run python learning/quick_start/quick_start.py

This tutorial uses one bank per user: Alice's memory lives in ``user-alice``.
It writes one memory, recalls related facts, then creates or refreshes the
bank's ``user-profile`` mental model and reads its content directly. Running
the example again reuses the same bank and profile, retains the example memory
again, and refreshes the profile.
"""

import asyncio
import os

from hindsight_client import Hindsight

DEFAULT_HINDSIGHT_API_URL = "http://localhost:8888"
USER_BANK_ID = "user-alice"
USER_PROFILE_MENTAL_MODEL_ID = "user-profile"
USER_PROFILE_SOURCE_QUERY = (
    "Build a factual profile of the user from retrieved memories only. Include confirmed background, "
    "preferences, and goals. Treat repeated memories as duplicate evidence, not independent corroboration. "
    "Do not attribute the bank's name, mission, background, or disposition settings to the user. "
    "Mark missing information as unknown and do not infer unsupported details."
)
USER_PROFILE_MAX_TOKENS = 2048
MENTAL_MODEL_OPERATION_POLL_INTERVAL_SECONDS = 1.0
MENTAL_MODEL_OPERATION_TIMEOUT_SECONDS = 300.0
TERMINAL_OPERATION_FAILURE_STATUSES = {"failed", "cancelled", "not_found"}


async def wait_for_mental_model_operation(client: Hindsight, operation_id: str) -> None:
    """Wait until a mental-model create or refresh operation finishes."""
    event_loop = asyncio.get_running_loop()
    deadline = event_loop.time() + MENTAL_MODEL_OPERATION_TIMEOUT_SECONDS

    while True:
        operation = await client.operations.get_operation_status(USER_BANK_ID, operation_id)
        if operation.status == "completed":
            return
        if operation.status in TERMINAL_OPERATION_FAILURE_STATUSES:
            raise RuntimeError(
                f"Mental-model operation {operation_id} {operation.status}: {operation.error_message or 'no details'}"
            )
        if event_loop.time() >= deadline:
            raise TimeoutError(
                f"Mental-model operation {operation_id} did not complete within "
                f"{MENTAL_MODEL_OPERATION_TIMEOUT_SECONDS:g} seconds"
            )

        await asyncio.sleep(MENTAL_MODEL_OPERATION_POLL_INTERVAL_SECONDS)


def main(only_get_mental_model=0) -> None:
    with Hindsight(base_url=os.getenv("HINDSIGHT_API_URL", DEFAULT_HINDSIGHT_API_URL)) as client:
        if only_get_mental_model:
            user_profile = client.get_mental_model(
                bank_id=USER_BANK_ID,
                mental_model_id=USER_PROFILE_MENTAL_MODEL_ID,
                detail="content",
            )
            print("\nUser profile:")
            print(user_profile.content or "(No profile content yet.)")
            return
        retain_response = client.retain(
            bank_id=USER_BANK_ID,
            content="Alice works at Google as a software engineer.",
        )
        print(f"Retain succeeded: {retain_response.success}")

        recall_response = client.recall(
            bank_id=USER_BANK_ID,
            query="What does Alice do?",
        )
        print("\nRecall results:")
        for result in recall_response.results:
            print(f"- [{result.type}] {result.text}")

        existing_models = client.list_mental_models(
            bank_id=USER_BANK_ID,
            detail="metadata",
        )
        has_user_profile = any(
            mental_model.id == USER_PROFILE_MENTAL_MODEL_ID for mental_model in existing_models.items
        )

        if has_user_profile:
            client.update_mental_model(
                bank_id=USER_BANK_ID,
                mental_model_id=USER_PROFILE_MENTAL_MODEL_ID,
                source_query=USER_PROFILE_SOURCE_QUERY,
            )
            profile_operation = client.refresh_mental_model(
                bank_id=USER_BANK_ID,
                mental_model_id=USER_PROFILE_MENTAL_MODEL_ID,
            )
        else:
            profile_operation = client.create_mental_model(
                bank_id=USER_BANK_ID,
                id=USER_PROFILE_MENTAL_MODEL_ID,
                name="User Profile",
                source_query=USER_PROFILE_SOURCE_QUERY,
                max_tokens=USER_PROFILE_MAX_TOKENS,
                trigger={"refresh_after_consolidation": True},
            )

        client_event_loop = asyncio.get_event_loop()
        client_event_loop.run_until_complete(wait_for_mental_model_operation(client, profile_operation.operation_id))
        user_profile = client.get_mental_model(
            bank_id=USER_BANK_ID,
            mental_model_id=USER_PROFILE_MENTAL_MODEL_ID,
            detail="content",
        )
        print("\nUser profile:")
        print(user_profile.content or "(No profile content yet.)")


if __name__ == "__main__":
    main(only_get_mental_model=0)
