"""Bootstrap containers: demo Fake ports (Hosts) and live MySQL wiring (release smoke)."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from enterprise_data_mcp.adapters.audit.migrator import AuditMigrator
from enterprise_data_mcp.adapters.audit.sqlite_audit_adapter import SqliteAuditAdapter
from enterprise_data_mcp.adapters.observability.composite_telemetry_adapter import (
    CompositeTelemetryAdapter,
)
from enterprise_data_mcp.adapters.outbound.mysql.catalog_adapter import (
    MysqlCatalogAdapter,
)
from enterprise_data_mcp.adapters.outbound.mysql.query_adapter import MysqlQueryAdapter
from enterprise_data_mcp.adapters.policy.yaml_policy_adapter import YamlPolicyAdapter
from enterprise_data_mcp.application.catalog_service import (
    GetAuthorizedSchema,
    ListAuthorizedDatasets,
)
from enterprise_data_mcp.application.query_service import ExecuteReadQuery
from enterprise_data_mcp.domain.errors import ResultStatus, TransportKind
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    Capability,
    DatasetPolicy,
    FieldSummary,
    QueryPlan,
    QueryResult,
    QueryResultSource,
    ValueType,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_POLICY_PATH = _PROJECT_ROOT / "config" / "access_policy.example.yaml"

_DATASET = "sales_inventory_daily"
_PHYSICAL = "phys_sales_secret"
_CALL_ID = "call-stdio-demo-0001"
_TRACE_ID = "trace-stdio-demo-aaaa"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"


@dataclass
class _FakeClockPort:
    now: str = _TIMESTAMP_UTC

    def now_utc(self) -> str:
        return self.now


@dataclass
class _FakeIdPort:
    trace_id: str = _TRACE_ID

    def new_trace_id(self) -> str:
        return self.trace_id


@dataclass
class _FakeTelemetryPort:
    def start_span(self, trace_id: str, operation: str) -> None:
        return None

    def record_event(
        self, trace_id: str, event: str, fields: Mapping[str, object]
    ) -> None:
        return None

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        return None


@dataclass
class _FakeAuditPort:
    def start(self, record: AuditRecord) -> None:
        return None

    def finish(self, record: AuditRecord) -> None:
        return None


@dataclass
class _FakePolicyPort:
    policies: frozenset[DatasetPolicy]

    def list_dataset_policies(self, caller: CallerContext) -> frozenset[DatasetPolicy]:
        return self.policies


@dataclass
class _FakeCatalogPort:
    snapshots: Mapping[str, tuple[FieldSummary, ...]]

    def get_field_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        return self.snapshots[authorized.dataset_id]


@dataclass
class _FakeQueryPort:
    result: QueryResult

    def execute(self, plan: QueryPlan) -> tuple[QueryResult, int]:
        return self.result, 1


@dataclass(frozen=True, slots=True)
class AppContainer:
    list_datasets: ListAuthorizedDatasets
    get_schema: GetAuthorizedSchema
    execute_query: ExecuteReadQuery
    caller: CallerContext
    call_id: str


class _HostIdentity(Protocol):
    caller_id: str
    policy_profile: str
    transport: TransportKind


def resolve_app_container(
    settings: _HostIdentity,
    environ: Mapping[str, str] | None = None,
) -> AppContainer:
    """Select demo vs live MySQL composition via MCP_CONTAINER (BUG-01)."""
    env = environ if environ is not None else {}
    mode = str(env.get("MCP_CONTAINER", "demo")).strip().lower()
    if mode in {"mysql", "live"}:
        return build_mysql_container(settings)
    if mode in {"demo", "fake"}:
        return build_demo_container(settings)
    raise ValueError(
        f"MCP_CONTAINER must be 'demo' or 'mysql', got {mode!r}"
    )


def build_demo_container(settings: _HostIdentity) -> AppContainer:
    """Wire Fake Catalog/Query ports for Host contract tests (no MySQL)."""
    policy = DatasetPolicy(
        dataset_id=_DATASET,
        physical_table=_PHYSICAL,
        allowed_fields=("product_name", "quantity"),
        capabilities=(Capability.READ_DETAIL, Capability.FILTER),
    )
    fields = (
        FieldSummary(
            field_id="product_name",
            title="product_name",
            value_type=ValueType.STRING,
            nullable=False,
            filterable=True,
            aggregatable=False,
            sortable=True,
        ),
        FieldSummary(
            field_id="quantity",
            title="quantity",
            value_type=ValueType.INTEGER,
            nullable=False,
            filterable=True,
            aggregatable=True,
            sortable=True,
        ),
    )
    empty = QueryResult(
        result_status=ResultStatus.EMPTY,
        columns=("product_name", "quantity"),
        rows=(),
        row_count=0,
        truncated=False,
        source=QueryResultSource(
            dataset_id=_DATASET, queried_at_utc=_TIMESTAMP_UTC
        ),
    )
    ports: dict[str, Any] = dict(
        policy=_FakePolicyPort(policies=frozenset({policy})),
        catalog=_FakeCatalogPort(snapshots={_DATASET: fields}),
        audit=_FakeAuditPort(),
        telemetry=_FakeTelemetryPort(),
        clock=_FakeClockPort(),
        ids=_FakeIdPort(),
    )
    caller = CallerContext(
        caller_id=settings.caller_id,
        policy_profile=settings.policy_profile,
        transport=settings.transport,
    )
    return AppContainer(
        list_datasets=ListAuthorizedDatasets(**ports),
        get_schema=GetAuthorizedSchema(**ports),
        execute_query=ExecuteReadQuery(
            **ports,
            query=_FakeQueryPort(result=empty),
        ),
        caller=caller,
        call_id=_CALL_ID,
    )


@dataclass
class _UtcClockPort:
    def now_utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _UuidIdPort:
    def new_trace_id(self) -> str:
        return uuid.uuid4().hex


def _mysql_settings_from_env(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3307")),
        "user": os.environ.get("MYSQL_USER", "edmcp_ro"),
        "password": os.environ.get("MYSQL_PASSWORD", "demoro"),
        "database": os.environ.get("MYSQL_DATABASE", "edmcp_demo"),
        "query_timeout_ms": int(os.environ.get("MYSQL_QUERY_TIMEOUT_MS", "5000")),
        "queried_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if overrides:
        base.update(dict(overrides))
    return base


def build_mysql_container(
    settings: _HostIdentity,
    *,
    mysql: Mapping[str, Any] | None = None,
    policy_path: Path | str | None = None,
    audit_db_path: Path | str | None = None,
) -> AppContainer:
    """Wire real Policy YAML + MySQL Catalog/Query + SQLite audit (SPEC §16.4 smoke)."""
    path = Path(policy_path) if policy_path is not None else _DEFAULT_POLICY_PATH
    policy = YamlPolicyAdapter.from_yaml_path(path)

    mysql_cfg = _mysql_settings_from_env(mysql)
    catalog = MysqlCatalogAdapter(
        host=str(mysql_cfg["host"]),
        port=int(mysql_cfg["port"]),
        user=str(mysql_cfg["user"]),
        password=str(mysql_cfg["password"]),
        database=str(mysql_cfg["database"]),
        query_timeout_ms=int(mysql_cfg["query_timeout_ms"]),
    )
    query = MysqlQueryAdapter(
        host=str(mysql_cfg["host"]),
        port=int(mysql_cfg["port"]),
        user=str(mysql_cfg["user"]),
        password=str(mysql_cfg["password"]),
        database=str(mysql_cfg["database"]),
        query_timeout_ms=int(mysql_cfg["query_timeout_ms"]),
        queried_at_utc=str(mysql_cfg["queried_at_utc"]),
    )

    if audit_db_path is None:
        env_audit = os.environ.get("AUDIT_DB_PATH", "").strip()
        if env_audit:
            audit_path = Path(env_audit)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, tmp_name = tempfile.mkstemp(prefix="edmcp-audit-", suffix=".sqlite3")
            os.close(fd)
            audit_path = Path(tmp_name)
    else:
        audit_path = Path(audit_db_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
    AuditMigrator(db_path=audit_path).apply_upgrade()
    audit = SqliteAuditAdapter(
        db_path=audit_path,
        policy_profile=settings.policy_profile,
        transport=settings.transport.value
        if hasattr(settings.transport, "value")
        else str(settings.transport),
    )

    ports: dict[str, Any] = dict(
        policy=policy,
        catalog=catalog,
        audit=audit,
        telemetry=CompositeTelemetryAdapter(),
        clock=_UtcClockPort(),
        ids=_UuidIdPort(),
    )
    caller = CallerContext(
        caller_id=settings.caller_id,
        policy_profile=settings.policy_profile,
        transport=settings.transport,
    )
    return AppContainer(
        list_datasets=ListAuthorizedDatasets(**ports),
        get_schema=GetAuthorizedSchema(**ports),
        execute_query=ExecuteReadQuery(**ports, query=query),
        caller=caller,
        call_id=f"call-mysql-live-{uuid.uuid4().hex[:12]}",
    )
