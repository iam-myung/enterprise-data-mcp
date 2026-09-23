"""Critical OTEL span name closure (SPEC §16.2 / Step 8.2)."""

from __future__ import annotations

CRITICAL_SPAN_NAMES: frozenset[str] = frozenset(
    {
        "mcp.request",
        "policy.check",
        "catalog.read",
        "query.compile",
        "mysql.execute",
        "audit.write",
    }
)
