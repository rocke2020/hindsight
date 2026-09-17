"""Draft ProfileGuard: read-only authority over the external profile's directive copy.

Implements the enforcement half of learning/design_points/read-only-external-profile.md
(hybrid directive + memory design): the profile's directive copy may only be written
by the external sync service; the agent credential can read it (via reflect) but never
create, update, or delete it. The profile's memory copy is deliberately unprotected.

Load with:
    HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION=tests.profile_guard_draft:ProfileGuard
    HINDSIGHT_API_OPERATION_VALIDATOR_SYNC_API_KEY=<sync service key>
"""

from hindsight_api.extensions.operation_validator import (
    BankWriteContext,
    BankWriteOperation,
    CreateBankContext,
    OperationValidatorExtension,
    RecallContext,
    ReflectContext,
    RetainContext,
    ValidationResult,
)

# The only three writers of the directives table, plus destructive bank operations
# whose denial closes the whole-bank restore route (importer writes directives
# directly, but only into a fresh bank). Compare against the enum members, not
# their string values — BankWriteOperation is a StrEnum with lowercase values.
_DENIED_FOR_AGENT = frozenset(
    {
        BankWriteOperation.CREATE_DIRECTIVE,
        BankWriteOperation.UPDATE_DIRECTIVE,
        BankWriteOperation.DELETE_DIRECTIVE,
        BankWriteOperation.DELETE_BANK,
    }
)


class ProfileGuard(OperationValidatorExtension):
    """Reserve the profile directive (and bank lifecycle) to the sync service."""

    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self.sync_api_key = config.get("sync_api_key")
        if not self.sync_api_key:
            raise ValueError(
                "ProfileGuard requires HINDSIGHT_API_OPERATION_VALIDATOR_SYNC_API_KEY "
                "(the external profile sync service's credential)"
            )

    def _is_sync(self, request_context: object) -> bool:
        # Draft: raw bearer-key comparison. Production deployments should compare a
        # persisted identity (api_key_id): background execution reconstructs
        # RequestContext with internal=True and no raw key (memory_engine.py:3001-3019),
        # and internal=True must never itself be treated as sync authority.
        api_key = getattr(request_context, "api_key", None)
        return bool(api_key) and api_key == self.sync_api_key

    async def validate_bank_write(self, ctx: BankWriteContext) -> ValidationResult:
        if self._is_sync(ctx.request_context):
            return ValidationResult.accept()
        if ctx.operation in _DENIED_FOR_AGENT:
            return ValidationResult.reject(
                f"Operation '{ctx.operation.value}' is reserved to the profile sync service; "
                "the external profile is read-only inside Hindsight."
            )
        return ValidationResult.accept()

    async def validate_create_bank(self, ctx: CreateBankContext) -> ValidationResult:
        if self._is_sync(ctx.request_context):
            return ValidationResult.accept()
        return ValidationResult.reject("Bank creation is reserved to the profile sync service.")

    # The memory copy of the profile is deliberately unprotected: ordinary
    # retain/recall/reflect pass through unchanged for every principal.
    async def validate_retain(self, ctx: RetainContext) -> ValidationResult:
        return ValidationResult.accept()

    async def validate_recall(self, ctx: RecallContext) -> ValidationResult:
        return ValidationResult.accept()

    async def validate_reflect(self, ctx: ReflectContext) -> ValidationResult:
        return ValidationResult.accept()
