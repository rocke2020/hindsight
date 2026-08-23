from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, TracebackType

import pytest
from hindsight_client import RecallResponse, RecallResult
from hindsight_client_api.models.async_operation_submit_response import AsyncOperationSubmitResponse
from hindsight_client_api.models.create_mental_model_response import CreateMentalModelResponse
from hindsight_client_api.models.mental_model_list_response import MentalModelListResponse
from hindsight_client_api.models.mental_model_response import MentalModelResponse
from hindsight_client_api.models.operation_status_response import OperationStatusResponse
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


def user_profile_response() -> MentalModelResponse:
    return MentalModelResponse(
        id="user-profile",
        bank_id="user-alice",
        name="User Profile",
        source_query=(
            "Build a factual profile of the user from retrieved memories only. Include confirmed background, "
            "preferences, and goals. Treat repeated memories as duplicate evidence, not independent corroboration. "
            "Do not attribute the bank's name, mission, background, or disposition settings to the user. "
            "Mark missing information as unknown and do not infer unsupported details."
        ),
        content="Alice is a software engineer at Google.",
        tags=[],
        max_tokens=2048,
        trigger=None,
        last_refreshed_at="2026-08-23T12:00:00Z",
        last_memory_seen_at="2026-08-23T12:00:00Z",
        created_at="2026-08-23T12:00:00Z",
        reflect_response=None,
        is_stale=False,
    )


class FakeOperationsApi:
    def __init__(self, client_loop: asyncio.AbstractEventLoop) -> None:
        self.client_loop = client_loop

    async def get_operation_status(self, bank_id: str, operation_id: str) -> OperationStatusResponse:
        if asyncio.get_running_loop() is not self.client_loop:
            raise RuntimeError("operation polling crossed the client event-loop boundary")
        assert bank_id == "user-alice"
        assert operation_id in {"create-user-profile", "refresh-user-profile"}
        FakeHindsight.profile_operation_completed = True
        return OperationStatusResponse(
            operation_id=operation_id,
            status="completed",
            operation_type="refresh_mental_model",
            created_at="2026-08-23T12:00:00Z",
            updated_at="2026-08-23T12:00:01Z",
            completed_at="2026-08-23T12:00:01Z",
            error_message=None,
            retry_count=0,
            next_retry_at=None,
            progress=None,
            result_metadata={"mental_model_id": "user-profile"},
            details=None,
            child_operations=None,
            task_payload={"mental_model_id": "user-profile"},
        )


class FakeHindsight:
    was_closed = False
    profile_exists = False
    profile_operation_completed = False
    create_profile_calls = 0
    update_profile_calls = 0
    refresh_profile_calls = 0

    def __init__(self, base_url: str) -> None:
        assert base_url == "http://hindsight.test"
        try:
            client_loop = asyncio.get_event_loop()
        except RuntimeError:
            client_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(client_loop)
        self.operations = FakeOperationsApi(client_loop)

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
        assert bank_id == "user-alice"
        assert content == "Alice works at Google as a software engineer."
        return RetainResponse.model_validate_json(
            '{"success":true,"bank_id":"user-alice","items_count":1,"async":false}'
        )

    def recall(self, bank_id: str, query: str) -> RecallResponse:
        assert bank_id == "user-alice"
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

    def list_mental_models(self, bank_id: str, detail: str) -> MentalModelListResponse:
        assert bank_id == "user-alice"
        assert detail == "metadata"
        items = [user_profile_response()] if type(self).profile_exists else []
        return MentalModelListResponse(items=items, total=len(items), limit=100, offset=0)

    def create_mental_model(
        self,
        bank_id: str,
        name: str,
        source_query: str,
        max_tokens: int,
        trigger: dict[str, bool],
        id: str,
    ) -> CreateMentalModelResponse:
        assert bank_id == "user-alice"
        assert name == "User Profile"
        assert source_query == (
            "Build a factual profile of the user from retrieved memories only. Include confirmed background, "
            "preferences, and goals. Treat repeated memories as duplicate evidence, not independent corroboration. "
            "Do not attribute the bank's name, mission, background, or disposition settings to the user. "
            "Mark missing information as unknown and do not infer unsupported details."
        )
        assert max_tokens == 2048
        assert trigger == {"refresh_after_consolidation": True}
        assert id == "user-profile"
        type(self).create_profile_calls += 1
        return CreateMentalModelResponse(
            mental_model_id="user-profile",
            operation_id="create-user-profile",
        )

    def refresh_mental_model(self, bank_id: str, mental_model_id: str) -> AsyncOperationSubmitResponse:
        assert bank_id == "user-alice"
        assert mental_model_id == "user-profile"
        type(self).refresh_profile_calls += 1
        return AsyncOperationSubmitResponse(operation_id="refresh-user-profile", status="pending")

    def update_mental_model(
        self,
        bank_id: str,
        mental_model_id: str,
        source_query: str,
    ) -> MentalModelResponse:
        assert bank_id == "user-alice"
        assert mental_model_id == "user-profile"
        assert source_query == (
            "Build a factual profile of the user from retrieved memories only. Include confirmed background, "
            "preferences, and goals. Treat repeated memories as duplicate evidence, not independent corroboration. "
            "Do not attribute the bank's name, mission, background, or disposition settings to the user. "
            "Mark missing information as unknown and do not infer unsupported details."
        )
        type(self).update_profile_calls += 1
        return user_profile_response()

    def get_mental_model(self, bank_id: str, mental_model_id: str, detail: str) -> MentalModelResponse:
        assert bank_id == "user-alice"
        assert mental_model_id == "user-profile"
        assert detail == "content"
        assert type(self).profile_operation_completed
        return user_profile_response()


def run_quick_start(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> str:
    quick_start = load_quick_start_module()
    FakeHindsight.was_closed = False
    FakeHindsight.profile_operation_completed = False
    FakeHindsight.create_profile_calls = 0
    FakeHindsight.update_profile_calls = 0
    FakeHindsight.refresh_profile_calls = 0
    monkeypatch.setenv("HINDSIGHT_API_URL", "http://hindsight.test")
    monkeypatch.setattr(quick_start, "Hindsight", FakeHindsight)

    quick_start.main()

    assert FakeHindsight.was_closed
    return capsys.readouterr().out


def test_main_creates_missing_user_profile_and_prints_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeHindsight.profile_exists = False

    output = run_quick_start(monkeypatch, capsys)

    assert FakeHindsight.create_profile_calls == 1
    assert FakeHindsight.update_profile_calls == 0
    assert FakeHindsight.refresh_profile_calls == 0
    assert output == (
        "Retain succeeded: True\n"
        "\nRecall results:\n"
        "- [world] Alice works at Google as a software engineer.\n"
        "\nUser profile:\n"
        "Alice is a software engineer at Google.\n"
    )


def test_main_refreshes_existing_user_profile_before_printing_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeHindsight.profile_exists = True

    output = run_quick_start(monkeypatch, capsys)

    assert FakeHindsight.create_profile_calls == 0
    assert FakeHindsight.update_profile_calls == 1
    assert FakeHindsight.refresh_profile_calls == 1
    assert output.endswith("\nUser profile:\nAlice is a software engineer at Google.\n")


def test_main_polls_profile_on_the_sync_client_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeHindsight.profile_exists = True

    output = run_quick_start(monkeypatch, capsys)

    assert output.endswith("\nUser profile:\nAlice is a software engineer at Google.\n")
