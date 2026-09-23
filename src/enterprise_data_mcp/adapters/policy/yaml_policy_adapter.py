"""Static YAML Policy Adapter (SPEC §11.1 / §8.1 / Step 4).

Implements PolicyPort. No MySQL, Host, MCP, or logging.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from enterprise_data_mcp.domain.errors import ErrorCode
from enterprise_data_mcp.domain.models import CallerContext, Capability, DatasetPolicy

_SYSTEM_MAX_LIMIT = 100
_DEFAULT_LIMIT = 50

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "connection_string",
        "dsn",
        "credentials",
        "private_key",
    }
)


class PolicyValidationError(Exception):
    """Fail-fast policy load error mapped to VALIDATION_ERROR."""

    def __init__(self, message: str, *, field: str, reason: str) -> None:
        super().__init__(message)
        self.code = ErrorCode.VALIDATION_ERROR.value
        self.message = message
        self.context: dict[str, str] = {"field": field, "reason": reason}


class _FieldMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    physical_column: str


class _FieldListEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    physical_column: str


class _DatasetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    physical_table: str
    title: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    default_limit: int = _DEFAULT_LIMIT
    max_limit: int = _SYSTEM_MAX_LIMIT
    allowed_fields: Any


class YamlPolicyAdapter:
    """Load a single static YAML policy profile into DatasetPolicy values."""

    def __init__(
        self, *, policy_profile: str, policies: frozenset[DatasetPolicy]
    ) -> None:
        self._policy_profile = policy_profile
        self._policies = policies

    @classmethod
    def from_yaml_path(cls, path: Path | str) -> YamlPolicyAdapter:
        file_path = Path(path)
        if not file_path.is_file():
            raise PolicyValidationError(
                "policy file not found",
                field="path",
                reason="file_not_found",
            )
        try:
            raw_text = file_path.read_text(encoding="utf-8")
            loaded: Any = yaml.safe_load(raw_text)
        except OSError:
            raise PolicyValidationError(
                "policy file not readable",
                field="path",
                reason="file_not_readable",
            ) from None
        except yaml.YAMLError:
            raise PolicyValidationError(
                "policy YAML syntax is invalid",
                field="yaml",
                reason="invalid_syntax",
            ) from None

        if not isinstance(loaded, Mapping):
            raise PolicyValidationError(
                "policy root must be a mapping",
                field="root",
                reason="invalid_type",
            )

        _reject_sensitive_keys(loaded)

        profile = loaded.get("policy_profile")
        if not isinstance(profile, str) or not profile.strip():
            raise PolicyValidationError(
                "policy_profile is required",
                field="policy_profile",
                reason="required",
            )

        datasets_node = loaded.get("datasets")
        try:
            policies = _parse_datasets(datasets_node)
        except PolicyValidationError:
            raise
        except ValidationError as exc:
            raise PolicyValidationError(
                "policy structure is invalid",
                field="datasets",
                reason="schema_invalid",
            ) from exc
        except (TypeError, ValueError, KeyError) as exc:
            raise PolicyValidationError(
                "policy structure is invalid",
                field="datasets",
                reason="schema_invalid",
            ) from exc

        return cls(policy_profile=profile, policies=frozenset(policies))

    def list_dataset_policies(
        self, caller: CallerContext
    ) -> frozenset[DatasetPolicy]:
        if caller.policy_profile != self._policy_profile:
            return frozenset()
        return self._policies


def _reject_sensitive_keys(node: Any) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                raise PolicyValidationError(
                    "policy contains forbidden sensitive key",
                    field=key,
                    reason="sensitive_key_forbidden",
                )
            _reject_sensitive_keys(value)
    elif isinstance(node, list):
        for item in node:
            _reject_sensitive_keys(item)


def _parse_datasets(datasets_node: Any) -> list[DatasetPolicy]:
    if datasets_node is None:
        raise PolicyValidationError(
            "datasets is required",
            field="datasets",
            reason="required",
        )

    policies: list[DatasetPolicy] = []

    if isinstance(datasets_node, Mapping):
        for dataset_id, body in datasets_node.items():
            if not isinstance(dataset_id, str) or not dataset_id:
                raise PolicyValidationError(
                    "dataset_id must be a non-empty string",
                    field="dataset_id",
                    reason="invalid_type",
                )
            policies.append(_parse_one_dataset(dataset_id, body))
        return policies

    if isinstance(datasets_node, list):
        seen: set[str] = set()
        for item in datasets_node:
            if not isinstance(item, Mapping):
                raise PolicyValidationError(
                    "dataset list entries must be mappings",
                    field="datasets",
                    reason="invalid_type",
                )
            dataset_id = item.get("dataset_id")
            if not isinstance(dataset_id, str) or not dataset_id:
                raise PolicyValidationError(
                    "dataset_id is required",
                    field="dataset_id",
                    reason="required",
                )
            if dataset_id in seen:
                raise PolicyValidationError(
                    "duplicate dataset_id is forbidden",
                    field="dataset_id",
                    reason="duplicate_dataset_id",
                )
            seen.add(dataset_id)
            body = {k: v for k, v in item.items() if k != "dataset_id"}
            policies.append(_parse_one_dataset(dataset_id, body))
        return policies

    raise PolicyValidationError(
        "datasets must be a mapping or list",
        field="datasets",
        reason="invalid_type",
    )


def _parse_one_dataset(dataset_id: str, body: Any) -> DatasetPolicy:
    if not isinstance(body, Mapping):
        raise PolicyValidationError(
            "dataset body must be a mapping",
            field=dataset_id,
            reason="invalid_type",
        )

    parsed = _DatasetBody.model_validate(dict(body))
    if parsed.max_limit > _SYSTEM_MAX_LIMIT:
        raise PolicyValidationError(
            "max_limit exceeds system cap",
            field="max_limit",
            reason="max_limit_exceeded",
        )
    if parsed.max_limit < 1 or parsed.default_limit < 1:
        raise PolicyValidationError(
            "limit must be >= 1",
            field="limit",
            reason="invalid_value",
        )
    if parsed.default_limit > parsed.max_limit:
        raise PolicyValidationError(
            "default_limit cannot exceed max_limit",
            field="default_limit",
            reason="invalid_value",
        )

    field_ids = _parse_allowed_fields(parsed.allowed_fields, dataset_id=dataset_id)
    capabilities = _parse_capabilities(parsed.capabilities)

    return DatasetPolicy(
        dataset_id=dataset_id,
        physical_table=parsed.physical_table,
        allowed_fields=tuple(field_ids),
        capabilities=capabilities,
    )


def _parse_allowed_fields(allowed_fields: Any, *, dataset_id: str) -> list[str]:
    if allowed_fields is None:
        raise PolicyValidationError(
            "allowed_fields must be non-empty",
            field="allowed_fields",
            reason="empty_allowed_fields",
        )

    if isinstance(allowed_fields, Mapping):
        if len(allowed_fields) == 0:
            raise PolicyValidationError(
                "allowed_fields must be non-empty",
                field="allowed_fields",
                reason="empty_allowed_fields",
            )
        field_ids: list[str] = []
        for field_id, entry in allowed_fields.items():
            if not isinstance(field_id, str) or not field_id:
                raise PolicyValidationError(
                    "field_id must be a non-empty string",
                    field="allowed_fields",
                    reason="invalid_type",
                )
            _FieldMapEntry.model_validate(entry)
            field_ids.append(field_id)
        return field_ids

    if isinstance(allowed_fields, list):
        if len(allowed_fields) == 0:
            raise PolicyValidationError(
                "allowed_fields must be non-empty",
                field="allowed_fields",
                reason="empty_allowed_fields",
            )
        field_ids = []
        seen: set[str] = set()
        for entry in allowed_fields:
            parsed = _FieldListEntry.model_validate(entry)
            if parsed.field_id in seen:
                raise PolicyValidationError(
                    "duplicate field_id is forbidden",
                    field="field_id",
                    reason="duplicate_field_id",
                )
            seen.add(parsed.field_id)
            field_ids.append(parsed.field_id)
        return field_ids

    raise PolicyValidationError(
        "allowed_fields must be a mapping or list",
        field="allowed_fields",
        reason="invalid_type",
    )


def _parse_capabilities(raw: list[str]) -> tuple[Capability, ...]:
    caps: list[Capability] = []
    for item in raw:
        try:
            caps.append(Capability(item))
        except ValueError as exc:
            raise PolicyValidationError(
                "capability is not allowed",
                field="capabilities",
                reason="invalid_value",
            ) from exc
    return tuple(caps)
