#!/usr/bin/env python3
"""Focused validation for analytics dashboard query planning."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analytics_query_parser import build_dashboard_query, compute_shard_key


class AnalyticsQueryParserTests(unittest.TestCase):
    def test_builds_parameterized_shard_scoped_query(self) -> None:
        query = build_dashboard_query(
            {
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-1",
                "metric": "events",
                "group_by": "day",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-02T00:00:00Z",
                "filters": {"region": "us-east"},
            }
        )

        self.assertIn("shard_key = %(shard_key)s", query.sql)
        self.assertIn("COUNT(*)", query.sql)
        self.assertIn("properties->>%(filter_0_key)s = %(filter_0)s", query.sql)
        self.assertEqual(query.params["filter_0_key"], "region")
        self.assertEqual(query.params["filter_0"], "us-east")
        self.assertEqual(query.shard_key, compute_shard_key("tenant-a", "workspace-1"))

    def test_rejects_inverted_time_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "start must be earlier"):
            build_dashboard_query(
                {
                    "tenant_id": "tenant-a",
                    "workspace_id": "workspace-1",
                    "start": "2026-01-02T00:00:00Z",
                    "end": "2026-01-01T00:00:00Z",
                }
            )

    def test_rejects_unknown_metric(self) -> None:
        with self.assertRaisesRegex(ValueError, "metric must be"):
            build_dashboard_query(
                {
                    "tenant_id": "tenant-a",
                    "workspace_id": "workspace-1",
                    "metric": "drop table",
                    "start": "2026-01-01T00:00:00Z",
                    "end": "2026-01-02T00:00:00Z",
                }
            )

    def test_rejects_unsafe_filter_identifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "safe identifier"):
            build_dashboard_query(
                {
                    "tenant_id": "tenant-a",
                    "workspace_id": "workspace-1",
                    "start": "2026-01-01T00:00:00Z",
                    "end": "2026-01-02T00:00:00Z",
                    "filters": {"region;drop": "us-east"},
                }
            )


if __name__ == "__main__":
    unittest.main()
