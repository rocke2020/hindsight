"""Run the basic index (retain) -> recall (read) loop against Hindsight.

This is the minimal write/read pair over one memory bank: retain (index)
memories first, then recall (read) them back with a query. It uses the
official generated Python client (``hindsight-client``), the same one the
docs quickstart uses.

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

       uv run python learning/quick_start/index_and_recall.py

   To connect to a different API address, set ``HINDSIGHT_API_URL``::

       HINDSIGHT_API_URL=http://localhost:8080 \
         uv run python learning/quick_start/index_and_recall.py

This tutorial uses one bank: ``alice``. It indexes a handful of facts in one
batch retain, then issues two recall queries (basic, and filtered by fact
type) and prints the results. The bank persists between runs, so retained
facts from a previous run are still recalled on the next one.
"""

import os

from hindsight_client import Hindsight

DEFAULT_HINDSIGHT_API_URL = "http://localhost:8888"
USER_BANK_ID = "alice"
# One conversation, split into messages: each message is retained as its own
# item with a shared document_id so the facts stay grouped in one document.
CONVERSATION_DOCUMENT_ID = "chat-2026-09-15-alice-bob"
RETAIN_ITEMS = [
    {
        "content": "Alice works at Google as a software engineer.",
        "context": "career",
        "document_id": CONVERSATION_DOCUMENT_ID,
    },
    {
        "content": "Bob is a data scientist at Meta.",
        "context": "career",
        "document_id": CONVERSATION_DOCUMENT_ID,
    },
    {
        "content": "Alice loves hiking on weekends.",
        "context": "hobby",
        "document_id": CONVERSATION_DOCUMENT_ID,
    },
    {
        "content": "Alice and Bob are friends from college.",
        "context": "relationship",
        "document_id": CONVERSATION_DOCUMENT_ID,
    },
]


def print_recall_results(title: str, results) -> None:
    print(f"\n{title}")
    if not results:
        print("- (no results)")
        return
    for result in results:
        print(f"- [{result.type}] {result.text}")


def main() -> None:
    with Hindsight(base_url=os.getenv("HINDSIGHT_API_URL", DEFAULT_HINDSIGHT_API_URL)) as client:
        # Index (write): one batch retain. Hindsight extracts facts, resolves
        # entities, and links them in the knowledge graph behind the scenes.
        retain_response = client.retain_batch(
            bank_id=USER_BANK_ID,
            items=RETAIN_ITEMS,
        )
        print(f"Retain succeeded: {retain_response.success}")

        # Read (recall) #1: basic query — four search strategies (semantic,
        # keyword, graph, temporal) run in parallel, then results are reranked.
        recall_response = client.recall(
            bank_id=USER_BANK_ID,
            query="What does Alice do?",
        )
        print_recall_results("Recall results for 'What does Alice do?':", recall_response.results)

        # Read (recall) #2: filtered by fact type — only world facts
        # (objective information), no experiences or observations.
        world_facts = client.recall(
            bank_id=USER_BANK_ID,
            query="Where does Alice work?",
            types=["world"],
        )
        print_recall_results("World-only recall results:", world_facts.results)


if __name__ == "__main__":
    main()
