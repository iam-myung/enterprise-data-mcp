"""RED: YAML Policy Adapter (SPEC §11.1 / §8.1 / Step 4).

Scope: load valid policy; reject sensitive keys, duplicate IDs, load failures.
No production adapter until 4-GREEN.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import ErrorCode, TransportKind
from enterprise_data_mcp.domain.models import CallerContext, Capability, DatasetPolicy

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "policy"

_PROFILE = "demo_readonly"
_CALLER = CallerContext(
    caller_id="demo-stdio-client",
    policy_profile=_PROFILE,
    transport=TransportKind.STDIO,
)

# Sensitive substrings that must never appear in raised error payloads.
_LEAK_MARKERS: tuple[str, ...] = (
    "SHOULD_NOT_LEAK_IN_ERROR",
    "NESTED_SECRET_VALUE_XYZ",
)


def _adapter_cls() -> Any:
    """Import production symbol under test (must fail until 4-GREEN)."""
    from enterprise_data_mcp.adapters.policy.yaml_policy_adapter import (
        YamlPolicyAdapter,
    )

    return YamlPolicyAdapter


def _from_path(path: Path) -> Any:
    cls = _adapter_cls()
    return cls.from_yaml_path(path)


def _assert_validation_error(exc: BaseException) -> None:
    code = getattr(exc, "code", None)
    assert code in (
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.VALIDATION_ERROR.value,
    ), f"expected VALIDATION_ERROR, got {code!r} from {type(exc).__name__}"
    context = getattr(exc, "context", None)
    assert isinstance(context, dict), "VALIDATION_ERROR requires context mapping"
    assert set(context.keys()) <= {"field", "reason"}
    blob = f"{exc!s}{getattr(exc, 'message', '')}{context!s}"
    for marker in _LEAK_MARKERS:
        assert marker not in blob, f"secret leaked into error payload: {marker}"


# ---------------------------------------------------------------------------
# Import / construction surface
# ---------------------------------------------------------------------------


def test_yaml_policy_adapter_module_importable() -> None:
    cls = _adapter_cls()
    assert cls is not None
    assert callable(getattr(cls, "from_yaml_path", None))
    assert callable(getattr(cls, "list_dataset_policies", None)) or hasattr(
        cls, "list_dataset_policies"
    )


# ---------------------------------------------------------------------------
# Happy path — real fixture load
# ---------------------------------------------------------------------------


def test_loads_valid_policy_returns_dataset_policies() -> None:
    adapter = _from_path(FIXTURES / "valid_demo_readonly.yaml")
    policies = adapter.list_dataset_policies(_CALLER)

    assert isinstance(policies, frozenset)
    assert len(policies) == 1
    policy = next(iter(policies))
    assert isinstance(policy, DatasetPolicy)
    assert policy.dataset_id == "sales_inventory_daily"
    assert policy.physical_table == "v_sales_inventory_daily"
    assert "product_id" in policy.allowed_fields
    assert "business_date" in policy.allowed_fields
    assert Capability.READ_DETAIL in policy.capabilities
    assert policy.allowed_fields  # non-empty invariant


def test_unknown_policy_profile_returns_empty_frozenset() -> None:
    adapter = _from_path(FIXTURES / "valid_demo_readonly.yaml")
    other = CallerContext(
        caller_id="other-client",
        policy_profile="unknown_profile",
        transport=TransportKind.STDIO,
    )
    policies = adapter.list_dataset_policies(other)
    assert policies == frozenset()


# ---------------------------------------------------------------------------
# Sensitive keys (SPEC §11.1)
# ---------------------------------------------------------------------------


def test_rejects_top_level_password_sensitive_key() -> None:
    cls = _adapter_cls()  # RED: ModuleNotFoundError until GREEN
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(FIXTURES / "reject_sensitive_password.yaml")
    _assert_validation_error(ei.value)


def test_rejects_nested_api_key_sensitive_key() -> None:
    cls = _adapter_cls()
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(FIXTURES / "reject_sensitive_nested_token.yaml")
    _assert_validation_error(ei.value)


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "password",
        "secret",
        "token",
        "api_key",
        "connection_string",
        "dsn",
        "credentials",
        "private_key",
    ],
)
def test_rejects_sensitive_key_names_case_insensitive(
    sensitive_key: str, tmp_path: Path
) -> None:
    cls = _adapter_cls()
    # Upper/mixed case key must also be rejected (PLAN: case-insensitive).
    key = sensitive_key[:1].upper() + sensitive_key[1:]
    body = (
        f"policy_profile: {_PROFILE}\n"
        f"{key}: not-a-real-secret\n"
        "datasets:\n"
        "  sales_inventory_daily:\n"
        "    physical_table: v_sales_inventory_daily\n"
        "    title: Sales\n"
        "    description: demo\n"
        "    capabilities: [READ_DETAIL]\n"
        "    default_limit: 50\n"
        "    max_limit: 100\n"
        "    allowed_fields:\n"
        "      product_id:\n"
        "        physical_column: product_id\n"
    )
    path = tmp_path / f"reject_{sensitive_key}.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(path)
    _assert_validation_error(ei.value)


# ---------------------------------------------------------------------------
# Duplicate IDs
# ---------------------------------------------------------------------------


def test_rejects_duplicate_dataset_ids() -> None:
    cls = _adapter_cls()
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(FIXTURES / "reject_duplicate_dataset_ids.yaml")
    _assert_validation_error(ei.value)


def test_rejects_duplicate_field_ids() -> None:
    cls = _adapter_cls()
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(FIXTURES / "reject_duplicate_field_ids.yaml")
    _assert_validation_error(ei.value)


# ---------------------------------------------------------------------------
# Load failure paths
# ---------------------------------------------------------------------------


def test_rejects_missing_policy_file(tmp_path: Path) -> None:
    cls = _adapter_cls()
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(missing)
    _assert_validation_error(ei.value)


def test_rejects_invalid_yaml_syntax() -> None:
    cls = _adapter_cls()
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(FIXTURES / "reject_invalid_syntax.yaml")
    _assert_validation_error(ei.value)


def test_rejects_empty_allowed_fields() -> None:
    cls = _adapter_cls()
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(FIXTURES / "reject_empty_allowed_fields.yaml")
    _assert_validation_error(ei.value)


def test_rejects_max_limit_above_system_cap() -> None:
    cls = _adapter_cls()
    with pytest.raises(Exception) as ei:
        cls.from_yaml_path(FIXTURES / "reject_max_limit_overflow.yaml")
    _assert_validation_error(ei.value)


def test_adapter_must_not_import_mysql_or_hosts() -> None:
    """Architecture: policy adapter stays free of MySQL/Host stacks."""
    import ast

    src_root = Path(__file__).resolve().parents[4] / "src"
    module_path = (
        src_root
        / "enterprise_data_mcp"
        / "adapters"
        / "policy"
        / "yaml_policy_adapter.py"
    )
    assert module_path.is_file(), "expected yaml_policy_adapter.py (GREEN deliverable)"
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_prefixes = (
        "mysql",
        "enterprise_data_mcp.hosts",
        "enterprise_data_mcp.adapters.outbound",
        "enterprise_data_mcp.adapters.inbound",
        "fastmcp",
    )
    violations = [
        name
        for name in imported
        if any(name == p or name.startswith(p + ".") for p in forbidden_prefixes)
    ]
    assert not violations, f"policy adapter forbidden imports: {violations}"
