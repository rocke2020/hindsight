"""Run a retain -> recall -> reflect flow against the local Hindsight service.

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

The example writes one memory to the ``quick-start`` bank, recalls related
facts, and asks Hindsight to synthesize them with reflect. Running it again
uses the same bank and retains the example memory again.
"""

import os

from hindsight_client import Hindsight

DEFAULT_HINDSIGHT_API_URL = "http://localhost:8888"
BANK_ID = "quick-start"


def main() -> None:
    with Hindsight(base_url=os.getenv("HINDSIGHT_API_URL", DEFAULT_HINDSIGHT_API_URL)) as client:
        retain_response = client.retain(
            bank_id=BANK_ID,
            content="Alice works at Google as a software engineer.",
        )
        print(f"Retain succeeded: {retain_response.success}")

        recall_response = client.recall(
            bank_id=BANK_ID,
            query="What does Alice do?",
        )
        print("\nRecall results:")
        for result in recall_response.results:
            print(f"- [{result.type}] {result.text}")

        reflect_response = client.reflect(
            bank_id=BANK_ID,
            query="Summarize what you know about Alice.",
        )
        print("\nReflection:")
        print(reflect_response.text)


if __name__ == "__main__":
    main()
