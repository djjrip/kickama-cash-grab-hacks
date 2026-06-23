#!/usr/bin/env python3
"""
Structured JSON logging wrapper for build.py telemetry.

Replaces basic print statements with structured JSON log entries for better
telemetry parsing. Use --json-logs flag to enable JSON output.

Usage:
    python3 build.py --json-logs          # JSON log output to stderr
    python3 tools/json_logger.py           # Test the logger
"""

import json
import sys
import datetime
from typing import Any, Dict, Optional


def log_event(
    message: str,
    level: str = "info",
    module: str = "build",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Emit a structured JSON log entry.
    
    Args:
        message: Human-readable log message
        level: Log level (debug, info, warning, error, critical)
        module: Source module name
        **kwargs: Additional structured fields to include
    
    Returns:
        The log entry as a dict
    """
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": level.upper(),
        "module": module,
        "message": message,
    }
    # Merge extra fields
    for key, value in kwargs.items():
        if key not in entry:
            entry[key] = value
    
    # Output as JSON to stderr (so stdout stays clean for build output)
    print(json.dumps(entry, ensure_ascii=False), file=sys.stderr)
    return entry


def log_build_start(workdir: str, modules: list) -> Dict[str, Any]:
    """Log the start of a build."""
    return log_event(
        "Build started",
        level="info",
        module="build",
        workdir=workdir,
        modules=modules,
        module_count=len(modules),
    )


def log_build_complete(
    workdir: str,
    total_modules: int,
    passed: int,
    failed: int,
    elapsed_seconds: float,
) -> Dict[str, Any]:
    """Log build completion."""
    return log_event(
        "Build complete",
        level="info" if failed == 0 else "warning",
        module="build",
        total_modules=total_modules,
        passed=passed,
        failed=failed,
        elapsed_seconds=round(elapsed_seconds, 3),
    )


def log_module_start(name: str) -> Dict[str, Any]:
    """Log the start of a module build."""
    return log_event(
        f"Building module: {name}",
        level="debug",
        module="build",
        module_name=name,
    )


def log_module_complete(
    name: str,
    status: str,
    elapsed_seconds: float,
    artifact: Optional[str] = None,
) -> Dict[str, Any]:
    """Log module completion."""
    return log_event(
        f"Module {name}: {status}",
        level="debug" if status == "PASS" else "warning",
        module="build",
        module_name=name,
        module_status=status,
        elapsed_seconds=round(elapsed_seconds, 3),
        artifact=artifact,
    )


def log_diagnostic(
    commit_id: str,
    logd_path: Optional[str],
    metadata_path: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Log diagnostic artifact generation."""
    level = "info" if error is None else "error"
    return log_event(
        f"Diagnostic artifacts for commit {commit_id}",
        level=level,
        module="diagnostic",
        commit_id=commit_id,
        logd_path=logd_path,
        metadata_path=metadata_path,
        error=error,
    )


def log_error(message: str, exception: Optional[Exception] = None, **kwargs: Any) -> Dict[str, Any]:
    """Log an error with optional exception details."""
    extra = {}
    if exception:
        extra["exception_type"] = type(exception).__name__
        extra["exception_message"] = str(exception)
    extra.update(kwargs)
    return log_event(message, level="error", module="build", **extra)


# Unit tests
import unittest


class TestJSONLogger(unittest.TestCase):
    def test_log_event_basic(self):
        """log_event produces a dict with required fields."""
        entry = log_event("test message", level="info")
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["message"], "test message")
        self.assertIn("timestamp", entry)
    
    def test_log_event_with_extra_fields(self):
        """Extra kwargs are included in the log entry."""
        entry = log_event("test", module_name="foo", duration=1.5)
        self.assertEqual(entry["module_name"], "foo")
        self.assertEqual(entry["duration"], 1.5)
    
    def test_log_build_start(self):
        """log_build_start includes module info."""
        entry = log_build_start("/tmp/workdir", ["mod1", "mod2"])
        self.assertEqual(entry["module_count"], 2)
        self.assertEqual(entry["modules"], ["mod1", "mod2"])
    
    def test_log_build_complete(self):
        """log_build_complete includes pass/fail counts."""
        entry = log_build_complete("/tmp", 5, 3, 2, 10.5)
        self.assertEqual(entry["passed"], 3)
        self.assertEqual(entry["failed"], 2)
        self.assertEqual(entry["level"], "WARNING")  # has failures
    
    def test_log_build_complete_all_pass(self):
        """All-passing build logs as INFO level."""
        entry = log_build_complete("/tmp", 5, 5, 0, 10.0)
        self.assertEqual(entry["level"], "INFO")
    
    def test_log_module_complete(self):
        """log_module_complete includes status and timing."""
        entry = log_module_complete("test_mod", "PASS", 0.5, "build-artifact.tar")
        self.assertEqual(entry["module_status"], "PASS")
        self.assertEqual(entry["artifact"], "build-artifact.tar")
    
    def test_log_error_with_exception(self):
        """log_error captures exception details."""
        try:
            raise ValueError("test error")
        except ValueError as e:
            entry = log_error("something failed", exception=e)
        self.assertEqual(entry["exception_type"], "ValueError")
        self.assertEqual(entry["exception_message"], "test error")
        self.assertEqual(entry["level"], "ERROR")
    
    def test_log_diagnostic(self):
        """log_diagnostic includes commit and paths."""
        entry = log_diagnostic(
            "abc12345",
            "/tmp/diagnostic/build-abc12345.logd",
            "/tmp/diagnostic/build-abc12345.json",
        )
        self.assertEqual(entry["commit_id"], "abc12345")
        self.assertEqual(entry["level"], "INFO")
    
    def test_log_diagnostic_with_error(self):
        """log_diagnostic with error logs as ERROR level."""
        entry = log_diagnostic(
            "abc12345",
            None,
            "/tmp/diagnostic/build-abc12345.json",
            error="encryptly binary not found",
        )
        self.assertEqual(entry["level"], "ERROR")
        self.assertEqual(entry["error"], "encryptly binary not found")


if __name__ == "__main__":
    # Run tests
    unittest.main(argv=[''], exit=False)
    
    # Demo
    print("\n=== JSON Logger Demo ===", file=sys.stderr)
    log_build_start("/tmp/workdir", ["frontend", "backend", "market"])
    log_module_start("frontend")
    log_module_complete("frontend", "PASS", 2.3, "frontend.tar.gz")
    log_module_complete("backend", "FAIL", 5.1, None)
    log_diagnostic("abc12345", None, "diagnostic/build-abc12345.json", "encryptly not found")
    log_build_complete("/tmp/workdir", 3, 2, 1, 7.4)
