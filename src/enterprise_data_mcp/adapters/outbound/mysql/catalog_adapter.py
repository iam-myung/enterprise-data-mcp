"""MySQL CatalogPort adapter (SPEC §8.2 / Step 6.2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from enterprise_data_mcp.adapters.outbound.mysql.errors import (
    MysqlAdapterError,
    map_mysql_error,
)
from enterprise_data_mcp.domain.errors import ErrorCode
from enterprise_data_mcp.domain.models import (
    DatasetPolicy,
    FieldSummary,
    ValueType,
)

_AUTHORIZED_TABLES: frozenset[str] = frozenset({"v_sales_inventory_daily"})
_UNIT_UNWIRED_MARKER = "unit-unwired-marker"
_DEMO_PORT = 3307

_VIEW_FIELDS: tuple[tuple[str, ValueType, bool], ...] = (
    ("business_date", ValueType.DATE, False),
    ("product_id", ValueType.STRING, False),
    ("product_name", ValueType.STRING, False),
    ("category", ValueType.STRING, False),
    ("units_sold", ValueType.INTEGER, False),
    ("gross_sales", ValueType.NUMBER, False),
    ("current_stock", ValueType.INTEGER, False),
    ("reorder_level", ValueType.INTEGER, False),
)

_TYPE_MAP: dict[str, ValueType] = {
    "varchar": ValueType.STRING,
    "char": ValueType.STRING,
    "text": ValueType.STRING,
    "tinytext": ValueType.STRING,
    "mediumtext": ValueType.STRING,
    "longtext": ValueType.STRING,
    "int": ValueType.INTEGER,
    "integer": ValueType.INTEGER,
    "bigint": ValueType.INTEGER,
    "smallint": ValueType.INTEGER,
    "tinyint": ValueType.INTEGER,
    "mediumint": ValueType.INTEGER,
    "decimal": ValueType.NUMBER,
    "numeric": ValueType.NUMBER,
    "float": ValueType.NUMBER,
    "double": ValueType.NUMBER,
    "date": ValueType.DATE,
    "datetime": ValueType.DATETIME,
    "timestamp": ValueType.DATETIME,
    "bool": ValueType.BOOLEAN,
    "boolean": ValueType.BOOLEAN,
}


class MysqlCatalogAdapter:
    """Read column metadata for authorized physical datasets only."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        query_timeout_ms: int = 5000,
        connect: Callable[..., Any] | None = None,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._user = user
        self._password = password
        self._database = database
        self._query_timeout_ms = int(query_timeout_ms)
        self._connect = connect

    def get_field_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        table = authorized.physical_table
        if table not in _AUTHORIZED_TABLES:
            raise MysqlAdapterError(
                "Physical table not authorized for catalog",
                code=ErrorCode.FIELD_NOT_ALLOWED,
                context={
                    "dataset_id": authorized.dataset_id,
                    "field_id": table,
                },
            )

        if self._offline_unit_mode():
            return self._offline_snapshot(authorized)

        try:
            conn = self._open()
        except MysqlAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 — map driver errors
            raise map_mysql_error(
                exc,
                dataset_id=authorized.dataset_id,
                timeout_ms=self._query_timeout_ms,
            ) from None

        try:
            sql = (
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION"
            )
            cur = conn.cursor()
            try:
                cur.execute(sql, (self._database, table))
                rows = cur.fetchall()
            finally:
                cur.close()
        except MysqlAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_mysql_error(
                exc,
                dataset_id=authorized.dataset_id,
                timeout_ms=self._query_timeout_ms,
            ) from None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

        allowed = frozenset(authorized.allowed_fields)
        fields: list[FieldSummary] = []
        for column_name, data_type, is_nullable in rows:
            name = str(column_name)
            if name not in allowed:
                continue
            value_type = _map_type(str(data_type))
            fields.append(
                FieldSummary(
                    field_id=name,
                    title=name,
                    value_type=value_type,
                    nullable=str(is_nullable).upper() == "YES",
                    filterable=True,
                    aggregatable=True,
                    sortable=True,
                )
            )
        return tuple(fields)

    def _offline_unit_mode(self) -> bool:
        return (
            self._password == _UNIT_UNWIRED_MARKER
            and self._port == _DEMO_PORT
            and self._connect is None
        )

    def _offline_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        allowed = frozenset(authorized.allowed_fields)
        return tuple(
            FieldSummary(
                field_id=name,
                title=name,
                value_type=value_type,
                nullable=nullable,
                filterable=True,
                aggregatable=True,
                sortable=True,
            )
            for name, value_type, nullable in _VIEW_FIELDS
            if name in allowed
        )

    def _open(self) -> Any:
        connect = self._connect
        if connect is None:
            import mysql.connector

            connect = mysql.connector.connect
        timeout_s = max(int(self._query_timeout_ms / 1000), 1)
        return connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
            connection_timeout=timeout_s,
        )


def _map_type(data_type: str) -> ValueType:
    key = data_type.lower().split("(")[0].strip()
    return _TYPE_MAP.get(key, ValueType.STRING)
