#!/usr/bin/env python3
"""Build safe analytics dashboard queries for sharded event storage."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

ALLOWED_METRICS = {
    "events": "COUNT(*)",
    "users": "COUNT(DISTINCT properties->>'user_id')",
    "sessions": "COUNT(DISTINCT properties->>'session_id')",
}

ALLOWED_GROUPS = {
    "event_name": "event_name",
    "day": "date_trunc('day', occurred_at)",
    "workspace_id": "workspace_id",
}


@dataclass(frozen=True)
class DashboardQuery:
    sql: str
    params: dict[str, Any]
    shard_key: int


def compute_shard_key(tenant_id: str, workspace_id: str, shard_count: int = 32) -> int:
    """Return a deterministic routing key matching the schema's shard modulus."""
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    seed = f"{tenant_id}:{workspace_id}".encode("utf-8")
    # Python's hash is intentionally randomized per process; use a stable FNV-1a
    # variant so dry-run query plans and generated scripts route consistently.
    value = 2166136261
    for byte in seed:
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return value % shard_count


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _validate_identifier(value: str, field: str) -> str:
    if not IDENTIFIER_RE.match(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def build_dashboard_query(spec: dict[str, Any]) -> DashboardQuery:
    """Validate a dashboard query spec and return parameterized SQL."""
    tenant_id = str(spec.get("tenant_id") or "").strip()
    workspace_id = str(spec.get("workspace_id") or "").strip()
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not workspace_id:
        raise ValueError("workspace_id is required")

    metric = str(spec.get("metric", "events"))
    if metric not in ALLOWED_METRICS:
        raise ValueError(f"metric must be one of: {', '.join(sorted(ALLOWED_METRICS))}")

    group_by = str(spec.get("group_by", "day"))
    if group_by not in ALLOWED_GROUPS:
        raise ValueError(f"group_by must be one of: {', '.join(sorted(ALLOWED_GROUPS))}")

    start = _parse_timestamp(str(spec.get("start")), "start")
    end = _parse_timestamp(str(spec.get("end")), "end")
    if start >= end:
        raise ValueError("start must be earlier than end")

    filters = spec.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")

    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    where = [
        "tenant_id = %(tenant_id)s",
        "workspace_id = %(workspace_id)s",
        "occurred_at >= %(start)s",
        "occurred_at < %(end)s",
    ]

    for index, (key, raw_value) in enumerate(sorted(filters.items())):
        safe_key = _validate_identifier(str(key), f"filters[{key!r}]")
        param_name = f"filter_{index}"
        params[param_name] = str(raw_value)
        where.append(f"properties->>%({param_name}_key)s = %({param_name})s")
        params[f"{param_name}_key"] = safe_key

    shard_key = compute_shard_key(tenant_id, workspace_id)
    params["shard_key"] = shard_key
    where.insert(0, "shard_key = %(shard_key)s")

    group_expr = ALLOWED_GROUPS[group_by]
    sql = (
        f"SELECT {group_expr} AS bucket, {ALLOWED_METRICS[metric]} AS value\n"
        "FROM analytics_dashboard_events\n"
        f"WHERE {' AND '.join(where)}\n"
        f"GROUP BY {group_expr}\n"
        "ORDER BY bucket ASC"
    )
    return DashboardQuery(sql=sql, params=params, shard_key=shard_key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", help="Path to a JSON dashboard query spec")
    args = parser.parse_args()

    with open(args.spec, "r", encoding="utf-8") as handle:
        query = build_dashboard_query(json.load(handle))
    print(json.dumps({"sql": query.sql, "params": query.params}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
