#!/usr/bin/env python3
"""Validate config_generator.py schema validation behavior."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import config_generator


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "config_generator.py"
FIXTURES = [
    ROOT / "data" / "config_generator_invalid_bad_port.json",
    ROOT / "data" / "config_generator_invalid_bad_log_level.json",
    ROOT / "data" / "config_generator_invalid_unknown_section.json",
]


def run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def assert_contains_all(text: str, expected: list[str]) -> None:
    missing = [item for item in expected if item not in text]
    if missing:
        raise AssertionError(f"Missing expected text {missing!r} from:\n{text}")


def validate_invalid_fixtures() -> None:
    for fixture in FIXTURES:
        result = run_generator("--overrides", str(fixture), "--format", "json", "--stdout")
        if result.returncode == 0:
            raise AssertionError(f"{fixture.name} unexpectedly passed validation")

    bad_port = run_generator("--overrides", str(FIXTURES[0]), "--format", "json", "--stdout")
    assert_contains_all(bad_port.stderr, ["server.port", "server.read_timeout"])

    bad_log_level = run_generator("--overrides", str(FIXTURES[1]), "--format", "json", "--stdout")
    assert_contains_all(bad_log_level.stderr, ["app.debug", "app.log_level"])

    unknown_section = run_generator("--overrides", str(FIXTURES[2]), "--format", "json", "--stdout")
    assert_contains_all(unknown_section.stderr, ["payments"])


def validate_generated_json() -> None:
    result = run_generator("--env", "staging", "--format", "json", "--stdout")
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    payload = json.loads(result.stdout)
    if payload["app"]["environment"] != "staging":
        raise AssertionError("generated JSON did not use the requested environment")


def validate_custom_schema() -> None:
    custom_schema = {
        "type": "object",
        "properties": {
            "app": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["custom-app"]}
                },
            }
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        schema_path = Path(tmp) / "schema.json"
        schema_path.write_text(json.dumps(custom_schema), encoding="utf-8")
        result = run_generator("--schema", str(schema_path), "--format", "json", "--stdout")
        if result.returncode == 0:
            raise AssertionError("custom schema unexpectedly accepted generated config")
        assert_contains_all(result.stderr, ["app.name", "custom-app"])


def validate_internal_config_checks() -> None:
    schema = config_generator.load_schema(str(ROOT / "data" / "config_generator.schema.json"))

    errors = config_generator.validate_internal_configs(
        schema,
        default_config={
            **config_generator.DEFAULT_CONFIG,
            "server": {**config_generator.DEFAULT_CONFIG["server"], "port": "bad-port"},
        },
        env_overrides={
            **config_generator.ENV_OVERRIDES,
            "production": {
                **config_generator.ENV_OVERRIDES["production"],
                "app": {
                    **config_generator.ENV_OVERRIDES["production"]["app"],
                    "environment": "prod",
                },
            },
        },
    )

    assert_contains_all(
        "\n".join(errors),
        ["DEFAULT_CONFIG.server.port", "ENV_OVERRIDES.production.app.environment"],
    )


def main() -> None:
    validate_invalid_fixtures()
    validate_generated_json()
    validate_custom_schema()
    validate_internal_config_checks()
    print("config_generator schema validation checks passed")


if __name__ == "__main__":
    main()
