"""Validation helpers for declarative Stage 4 runbooks."""

from __future__ import annotations

from cockpit.domain.models.response import (
    RunbookArtifactDefinition,
    RunbookCompensationDefinition,
    RunbookDefinition,
    RunbookStepDefinition,
)
from cockpit.shared.enums import RunbookExecutorKind, RunbookRiskClass


class RunbookValidationError(ValueError):
    """Raised when a declarative runbook definition is invalid."""


def validate_runbook_payload(
    payload: dict[str, object],
    *,
    source_path: str,
    checksum: str,
) -> RunbookDefinition:
    """Validate and normalize one runbook payload.

    Parameters
    ----------
    payload:
        Raw YAML payload.
    source_path:
        Source file path for diagnostics.
    checksum:
        Stable content checksum for the loaded file.
    """

    runbook_id = _required_str(payload, "id")
    version = _required_str(payload, "version")
    title = _required_str(payload, "title")
    description = _optional_str(payload.get("description"))
    risk_class = RunbookRiskClass(str(payload.get("risk_class", RunbookRiskClass.GUARDED.value)))
    tags = _string_list(payload.get("tags", []))
    scope = _mapping(payload.get("scope", {}), key="scope")

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RunbookValidationError("Runbook must declare a non-empty 'steps' list.")

    steps: list[RunbookStepDefinition] = []
    seen_keys: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise RunbookValidationError(f"Step {index} must be an object.")
        step = _validate_step(raw_step, step_index=index)
        if step.key in seen_keys:
            raise RunbookValidationError(f"Runbook step key '{step.key}' is duplicated.")
        seen_keys.add(step.key)
        steps.append(step)

    return RunbookDefinition(
        id=runbook_id,
        version=version,
        title=title,
        description=description,
        risk_class=risk_class,
        source_path=source_path,
        checksum=checksum,
        scope=scope,
        tags=tuple(tags),
        steps=tuple(steps),
    )


def _validate_step(payload: dict[str, object], *, step_index: int) -> RunbookStepDefinition:
    key = _required_str(payload, "key")
    title = _required_str(payload, "title")
    executor_kind = RunbookExecutorKind(_required_str(payload, "executor_kind"))
    operation_kind = _required_str(payload, "operation_kind")
    description = _optional_str(payload.get("description"))
    requires_confirmation = bool(payload.get("requires_confirmation", False))
    requires_elevated_mode = bool(payload.get("requires_elevated_mode", False))
    approval_required = bool(payload.get("approval_required", False))
    required_approver_count = int(payload.get("required_approver_count", 0) or 0)
    required_roles = tuple(_string_list(payload.get("required_roles", [])))
    allow_self_approval = bool(payload.get("allow_self_approval", False))
    approval_expires_after_seconds = payload.get("approval_expires_after_seconds")
    max_retries = int(payload.get("max_retries", 0) or 0)
    continue_on_failure = bool(payload.get("continue_on_failure", False))
    step_config = _mapping(payload.get("step_config", {}), key=f"steps[{step_index}].step_config")
    artifacts = _validate_artifacts(payload.get("artifacts", []), step_index=step_index)
    compensation = _validate_compensation(
        payload.get("compensation"),
        step_index=step_index,
    )

    if required_approver_count < 0:
        raise RunbookValidationError(
            f"Step '{key}' has invalid required_approver_count {required_approver_count}."
        )
    if required_approver_count > 0:
        approval_required = True
    if approval_expires_after_seconds is not None and int(approval_expires_after_seconds) <= 0:
        raise RunbookValidationError(
            f"Step '{key}' must use a positive approval_expires_after_seconds."
        )
    if max_retries < 0:
        raise RunbookValidationError(f"Step '{key}' must not use a negative max_retries.")

    _validate_executor_config(
        executor_kind=executor_kind,
        step_key=key,
        step_config=step_config,
    )

    return RunbookStepDefinition(
        key=key,
        title=title,
        executor_kind=executor_kind,
        operation_kind=operation_kind,
        description=description,
        requires_confirmation=requires_confirmation,
        requires_elevated_mode=requires_elevated_mode,
        approval_required=approval_required,
        required_approver_count=required_approver_count,
        required_roles=required_roles,
        allow_self_approval=allow_self_approval,
        approval_expires_after_seconds=(
            int(approval_expires_after_seconds)
            if approval_expires_after_seconds is not None
            else None
        ),
        max_retries=max_retries,
        continue_on_failure=continue_on_failure,
        step_config=step_config,
        artifacts=artifacts,
        compensation=compensation,
    )


def _validate_artifacts(payload: object, *, step_index: int) -> tuple[RunbookArtifactDefinition, ...]:
    if payload in (None, []):
        return ()
    if not isinstance(payload, list):
        raise RunbookValidationError(f"Step {step_index} artifacts must be a list.")
    items: list[RunbookArtifactDefinition] = []
    for artifact_index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise RunbookValidationError(
                f"Step {step_index} artifact {artifact_index} must be an object."
            )
        items.append(
            RunbookArtifactDefinition(
                kind=_required_str(item, "kind"),
                label=_required_str(item, "label"),
                required=bool(item.get("required", False)),
            )
        )
    return tuple(items)


def _validate_compensation(
    payload: object,
    *,
    step_index: int,
) -> RunbookCompensationDefinition | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise RunbookValidationError(f"Step {step_index} compensation must be an object.")
    step_config = _mapping(
        payload.get("step_config", {}),
        key=f"steps[{step_index}].compensation.step_config",
    )
    executor_kind = RunbookExecutorKind(_required_str(payload, "executor_kind"))
    operation_kind = _required_str(payload, "operation_kind")
    _validate_executor_config(
        executor_kind=executor_kind,
        step_key=f"steps[{step_index}].compensation",
        step_config=step_config,
    )
    required_approver_count = int(payload.get("required_approver_count", 0) or 0)
    return RunbookCompensationDefinition(
        title=_required_str(payload, "title"),
        executor_kind=executor_kind,
        operation_kind=operation_kind,
        step_config=step_config,
        requires_confirmation=bool(payload.get("requires_confirmation", False)),
        requires_elevated_mode=bool(payload.get("requires_elevated_mode", False)),
        approval_required=bool(payload.get("approval_required", False) or required_approver_count > 0),
        required_approver_count=required_approver_count,
        required_roles=tuple(_string_list(payload.get("required_roles", []))),
    )


def _validate_executor_config(
    *,
    executor_kind: RunbookExecutorKind,
    step_key: str,
    step_config: dict[str, object],
) -> None:
    if executor_kind is RunbookExecutorKind.MANUAL:
        if "instructions" not in step_config:
            raise RunbookValidationError(
                f"Manual step '{step_key}' must declare step_config.instructions."
            )
        return
    if executor_kind is RunbookExecutorKind.SHELL:
        if "command" not in step_config:
            raise RunbookValidationError(
                f"Shell step '{step_key}' must declare step_config.command."
            )
        return
    if executor_kind is RunbookExecutorKind.HTTP:
        if "method" not in step_config or "url" not in step_config:
            raise RunbookValidationError(
                f"HTTP step '{step_key}' must declare step_config.method and step_config.url."
            )
        return
    if executor_kind is RunbookExecutorKind.DOCKER:
        if "operation" not in step_config or "container_id" not in step_config:
            raise RunbookValidationError(
                f"Docker step '{step_key}' must declare step_config.operation and step_config.container_id."
            )
        return
    if executor_kind is RunbookExecutorKind.DB:
        if "statement" not in step_config:
            raise RunbookValidationError(
                f"DB step '{step_key}' must declare step_config.statement."
            )
        if "profile_id" not in step_config and "database_path" not in step_config:
            raise RunbookValidationError(
                f"DB step '{step_key}' must declare step_config.profile_id or step_config.database_path."
            )
        return


def _required_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RunbookValidationError(f"Field '{key}' must be a non-empty string.")
    return value.strip()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RunbookValidationError("Optional string fields must be strings.")
    normalized = value.strip()
    return normalized or None


def _string_list(value: object) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise RunbookValidationError("Expected a list of strings.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RunbookValidationError("Expected a list of non-empty strings.")
        result.append(item.strip())
    return result


def _mapping(value: object, *, key: str) -> dict[str, object]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise RunbookValidationError(f"Field '{key}' must be an object.")
    return {str(map_key): map_value for map_key, map_value in value.items()}

