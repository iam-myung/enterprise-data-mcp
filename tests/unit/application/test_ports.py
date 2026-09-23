"""RED: Application Ports shape + prohibitions (SPEC §8 / Step 3.1).

Scope: Protocol surfaces only. No use cases, no Adapters, no I/O.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Protocol, get_args, get_origin, get_type_hints

import pytest

# Exact Port closure — SPEC §8 / 3.1-PLAN.
REQUIRED_PORT_NAMES: frozenset[str] = frozenset(
    {
        "PolicyPort",
        "CatalogPort",
        "QueryPort",
        "AuditPort",
        "TelemetryPort",
        "ClockPort",
        "IdPort",
    }
)

# Application must stay free of concrete I/O stacks (SPEC §6 / §18.1).
FORBIDDEN_APPLICATION_IMPORT_PREFIXES: tuple[str, ...] = (
    "enterprise_data_mcp.adapters",
    "enterprise_data_mcp.hosts",
    "enterprise_data_mcp.bootstrap",
    "fastmcp",
    "mcp",
    "mysql",
    "mysql.connector",
    "opentelemetry",
    "sqlite3",
    "sqlalchemy",
    "langgraph",
)

# PolicyPort must not expose DB / query / logging surfaces (SPEC §8.1).
POLICY_FORBIDDEN_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "connect",
        "execute",
        "execute_query",
        "execute_sql",
        "fetch",
        "fetchall",
        "query",
        "run_query",
        "log",
        "info",
        "debug",
        "warning",
        "error",
        "write_log",
    }
)

# QueryPort must not accept raw SQL / write / multi-statement knobs (SPEC §8.3).
QUERY_FORBIDDEN_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "raw_sql",
        "sql",
        "statement",
        "statements",
        "multi_statement",
        "write",
        "autocommit",
    }
)


def _load_ports() -> Any:
    """Import production module under test (must fail until 3.1-GREEN)."""
    import enterprise_data_mcp.application.ports as ports_module

    return ports_module


def _ports_source_path() -> Path:
    import enterprise_data_mcp.application.ports as ports_module

    path = Path(ports_module.__file__).resolve()
    assert path.name == "ports.py"
    return path


def _parse_imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _module_violates(imported: str, forbidden_prefixes: tuple[str, ...]) -> bool:
    return any(
        imported == prefix or imported.startswith(prefix + ".")
        for prefix in forbidden_prefixes
    )


def _protocol_method_names(protocol_cls: type) -> frozenset[str]:
    return frozenset(
        name
        for name, member in vars(protocol_cls).items()
        if callable(member) and not name.startswith("_")
    )


def _annotation_type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is not None:
        return getattr(origin, "__name__", str(origin))
    return getattr(annotation, "__name__", str(annotation))


# ---------------------------------------------------------------------------
# Closure + Protocol shape
# ---------------------------------------------------------------------------


def test_ports_module_exports_exact_seven_port_protocols() -> None:
    ports = _load_ports()
    exported = {
        name
        for name in REQUIRED_PORT_NAMES
        if hasattr(ports, name)
    }
    assert exported == REQUIRED_PORT_NAMES

    for name in sorted(REQUIRED_PORT_NAMES):
        port_cls = getattr(ports, name)
        assert isinstance(port_cls, type), f"{name} must be a type"
        assert issubclass(port_cls, Protocol), f"{name} must be typing.Protocol"


def test_policy_port_lists_immutable_dataset_policies_from_caller() -> None:
    ports = _load_ports()
    from enterprise_data_mcp.domain.models import CallerContext, DatasetPolicy

    PolicyPort = ports.PolicyPort
    methods = _protocol_method_names(PolicyPort)
    assert "list_dataset_policies" in methods
    assert methods.isdisjoint(POLICY_FORBIDDEN_METHOD_NAMES)

    hints = get_type_hints(PolicyPort.list_dataset_policies)
    assert hints["caller"] is CallerContext
    return_ann = hints["return"]
    assert get_origin(return_ann) is frozenset
    assert get_args(return_ann) == (DatasetPolicy,)


def test_catalog_port_returns_field_snapshot_for_authorized_physical_ref() -> None:
    ports = _load_ports()
    from enterprise_data_mcp.domain.models import DatasetPolicy, FieldSummary

    CatalogPort = ports.CatalogPort
    methods = _protocol_method_names(CatalogPort)
    assert "get_field_snapshot" in methods
    assert "list_all_tables" not in methods
    assert "get_credentials" not in methods

    hints = get_type_hints(CatalogPort.get_field_snapshot)
    assert hints["authorized"] is DatasetPolicy
    return_ann = hints["return"]
    assert get_origin(return_ann) is tuple
    assert get_args(return_ann) == (FieldSummary, ...)


def test_query_port_executes_validated_plan_without_raw_sql() -> None:
    ports = _load_ports()
    from enterprise_data_mcp.domain.models import QueryPlan, QueryResult

    QueryPort = ports.QueryPort
    methods = _protocol_method_names(QueryPort)
    assert "execute" in methods
    assert "execute_raw" not in methods
    assert "execute_write" not in methods
    assert "commit" not in methods

    sig = inspect.signature(QueryPort.execute)
    param_names = frozenset(sig.parameters) - {"self"}
    assert param_names.isdisjoint(QUERY_FORBIDDEN_PARAM_NAMES)

    hints = get_type_hints(QueryPort.execute)
    assert hints["plan"] is QueryPlan
    return_ann = hints["return"]
    assert get_origin(return_ann) is tuple
    assert get_args(return_ann) == (QueryResult, int)


def test_audit_port_start_and_finish_take_audit_record() -> None:
    ports = _load_ports()
    from enterprise_data_mcp.domain.models import AuditRecord

    AuditPort = ports.AuditPort
    methods = _protocol_method_names(AuditPort)
    assert methods == frozenset({"start", "finish"})

    start_hints = get_type_hints(AuditPort.start)
    finish_hints = get_type_hints(AuditPort.finish)
    assert start_hints["record"] is AuditRecord
    assert finish_hints["record"] is AuditRecord
    assert start_hints["return"] is type(None)
    assert finish_hints["return"] is type(None)


def test_audit_port_protocol_source_does_not_swallow_failures() -> None:
    """Adapter contract: write failures must surface — Protocol must not hide them."""
    path = _ports_source_path()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    audit_cls: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AuditPort":
            audit_cls = node
            break
    assert audit_cls is not None, "AuditPort class missing in ports.py"

    for stmt in audit_cls.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name in {"start", "finish"}:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Try):
                    for handler in child.handlers:
                        if handler.body and all(
                            isinstance(b, ast.Pass) for b in handler.body
                        ):
                            pytest.fail(
                                f"AuditPort.{stmt.name} must not swallow failures "
                                "with bare except/pass"
                            )


def test_telemetry_port_exposes_span_event_and_metric_hooks() -> None:
    ports = _load_ports()
    TelemetryPort = ports.TelemetryPort
    methods = _protocol_method_names(TelemetryPort)
    assert "start_span" in methods
    assert "record_event" in methods
    assert "record_metric" in methods

    span_hints = get_type_hints(TelemetryPort.start_span)
    event_hints = get_type_hints(TelemetryPort.record_event)
    metric_hints = get_type_hints(TelemetryPort.record_metric)

    assert span_hints["trace_id"] is str
    assert span_hints["operation"] is str
    assert event_hints["trace_id"] is str
    assert event_hints["event"] is str
    assert _annotation_type_name(event_hints["fields"]) in {"Mapping", "dict"}
    assert metric_hints["name"] is str
    assert metric_hints["value"] is float
    assert _annotation_type_name(metric_hints["labels"]) in {"Mapping", "dict"}


def test_clock_and_id_ports_support_deterministic_injection() -> None:
    ports = _load_ports()
    ClockPort = ports.ClockPort
    IdPort = ports.IdPort

    assert "now_utc" in _protocol_method_names(ClockPort)
    assert "new_trace_id" in _protocol_method_names(IdPort)

    assert get_type_hints(ClockPort.now_utc)["return"] is str
    assert get_type_hints(IdPort.new_trace_id)["return"] is str


# ---------------------------------------------------------------------------
# Prohibitions (module / package boundaries)
# ---------------------------------------------------------------------------


def test_ports_module_has_no_forbidden_runtime_imports() -> None:
    path = _ports_source_path()
    imported = _parse_imported_modules(path)
    violations = sorted(
        name
        for name in imported
        if _module_violates(name, FORBIDDEN_APPLICATION_IMPORT_PREFIXES)
    )
    assert not violations, "ports.py forbidden imports:\n" + "\n".join(violations)


def test_ports_module_does_not_define_use_case_services() -> None:
    ports = _load_ports()
    forbidden_attrs = (
        "ListAuthorizedDatasets",
        "GetAuthorizedSchema",
        "ExecuteReadQuery",
        "CatalogService",
        "QueryService",
        "list_authorized_datasets",
        "get_authorized_schema",
        "execute_read_query",
    )
    present = [name for name in forbidden_attrs if hasattr(ports, name)]
    assert present == [], f"ports.py must not host use cases: {present}"


def test_application_package_allows_query_service_module_for_step_52() -> None:
    """Step 5.2 introduces query_service.py — module file must exist."""
    import enterprise_data_mcp.application as application_pkg

    app_dir = Path(application_pkg.__file__).resolve().parent
    path = app_dir / "query_service.py"
    assert path.is_file(), "expected application/query_service.py (Step 5.2)"


def test_telemetry_port_is_invisible_to_domain_package() -> None:
    """SPEC §8.5: TelemetryPort must not appear inside domain."""
    import enterprise_data_mcp.domain as domain_pkg

    domain_dir = Path(domain_pkg.__file__).resolve().parent
    hits: list[str] = []
    for path in sorted(domain_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "TelemetryPort" in text or "application.ports" in text:
            hits.append(str(path.relative_to(domain_dir)))
    assert hits == [], "domain must not reference TelemetryPort/ports:\n" + "\n".join(
        hits
    )


def test_policy_port_has_no_db_oriented_parameters() -> None:
    ports = _load_ports()
    sig = inspect.signature(ports.PolicyPort.list_dataset_policies)
    param_names = frozenset(sig.parameters) - {"self"}
    db_params = frozenset(
        {
            "connection",
            "conn",
            "cursor",
            "engine",
            "session",
            "dsn",
            "sql",
            "raw_sql",
        }
    )
    assert param_names.isdisjoint(db_params)
    assert param_names == frozenset({"caller"})
