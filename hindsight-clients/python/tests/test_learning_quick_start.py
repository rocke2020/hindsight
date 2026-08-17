from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, TracebackType

import pytest

from hindsight_client import RecallResponse, RecallResult, ReflectResponse
from hindsight_client_api.models.retain_response import RetainResponse

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
QUICK_START_MODULE_PATH = REPOSITORY_ROOT / "learning" / "quick_start" / "quick_start.py"


def load_quick_start_module() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location("learning_quick_start", QUICK_START_MODULE_PATH)
    assert module_spec is not None
    assert module_spec.loader is not None

    quick_start_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(quick_start_module)
    return quick_start_module


class FakeHindsight:
    was_closed = False

    def __init__(self, base_url: str) -> None:
        assert base_url == "http://hindsight.test"

    def __enter__(self) -> FakeHindsight:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        type(self).was_closed = True

    def retain(self, bank_id: str, content: str) -> RetainResponse:
        assert bank_id == "quick-start"
        assert content == "Alice works at Google as a software engineer."
        return RetainResponse.model_validate_json(
            '{"success":true,"bank_id":"quick-start","items_count":1,"async":false}'
        )

    def recall(self, bank_id: str, query: str) -> RecallResponse:
        assert bank_id == "quick-start"
        assert query == "What does Alice do?"
        return RecallResponse(
            results=[
                RecallResult(
                    id="memory-1",
                    type="world",
                    text="Alice works at Google as a software engineer.",
                )
            ]
        )

    def reflect(self, bank_id: str, query: str) -> ReflectResponse:
        assert bank_id == "quick-start"
        assert query == "Summarize what you know about Alice."
        return ReflectResponse(text="Alice is a software engineer at Google.")


def test_main_runs_retain_recall_reflect_and_prints_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    quick_start = load_quick_start_module()
    FakeHindsight.was_closed = False
    monkeypatch.setenv("HINDSIGHT_API_URL", "http://hindsight.test")
    monkeypatch.setattr(quick_start, "Hindsight", FakeHindsight)

    quick_start.main()

    assert FakeHindsight.was_closed
    assert capsys.readouterr().out == (
        "Retain succeeded: True\n"
        "\nRecall results:\n"
        "- [world] Alice works at Google as a software engineer.\n"
        "\nReflection:\n"
        "Alice is a software engineer at Google.\n"
    )
