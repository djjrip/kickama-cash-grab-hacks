#!/usr/bin/env python3
"""
Configuration file generator for the Tent of Trials platform.
Generates configuration files for different environments from templates.

This tool supports multiple configuration formats:
  - YAML (default)
  - JSON
  - TOML
  - Environment variables (.env)
  - Kubernetes ConfigMap YAML

The configuration templates use Jinja2 templating with environment-specific
variable files. The variable files are stored in the `config/vars/` directory
and are selected based on the target environment.

Usage:
    python3 config_generator.py --env production --format yaml
    python3 config_generator.py --env staging --format json --output config.json
    python3 config_generator.py --env development --format dotenv
    python3 config_generator.py --env production --format k8s-configmap
"""

import argparse
import copy
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import toml
    HAS_TOML = True
except ImportError:
    HAS_TOML = False


# ---------------------------------------------------------------------------
# CONFIGURATION SCHEMA
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "app": {
        "name": "tent-of-trials",
        "version": "3.2.0",
        "environment": "development",
        "debug": True,
        "log_level": "debug",
        "log_format": "json",
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
        "read_timeout": 30,
        "write_timeout": 60,
        "idle_timeout": 120,
        "max_header_bytes": 1048576,
        "shutdown_timeout": 30,
    },
    "database": {
        "host": "localhost",
        "port": 5432,
        "name": "tent_dev",
        "user": "tent_app",
        "password": "",  # Must be set via env var or vault
        "pool_min": 2,
        "pool_max": 10,
        "timeout_ms": 5000,
        "ssl_mode": "prefer",
    },
    "redis": {
        "host": "localhost",
        "port": 6379,
        "password": "",
        "db": 0,
        "pool_size": 10,
        "timeout_ms": 2000,
    },
    "kafka": {
        "brokers": ["localhost:9092"],
        "group_id": "tent-dev",
        "client_id": "tent-backend",
        "timeout_ms": 10000,
        "retry_count": 3,
        "retry_backoff_ms": 1000,
        "enable_auto_commit": True,
        "auto_commit_interval_ms": 5000,
    },
    "market": {
        "rate_limit_per_second": 10,
        "rate_limit_burst": 20,
        "orderbook_depth": 50,
        "max_order_size": 1000,
        "min_order_size": 0.001,
        "max_position_size": 10000,
        "allowed_instruments": ["*"],
        "fees": {
            "maker": 0.001,
            "taker": 0.002,
            "withdrawal": 0.0,
        },
    },
    "auth": {
        "jwt_secret": "",  # Must be set via env var or vault
        "jwt_expiry_minutes": 60,
        "refresh_token_expiry_days": 30,
        "session_timeout_minutes": 60,
        "mfa_required": False,
        "max_login_attempts": 5,
        "lockout_duration_minutes": 15,
        "password_min_length": 8,
        "password_require_special": True,
        "password_require_numbers": True,
        "password_require_uppercase": True,
    },
    "monitoring": {
        "metrics_enabled": True,
        "metrics_port": 9090,
        "tracing_enabled": True,
        "tracing_sample_rate": 0.1,
        "tracing_endpoint": "http://localhost:4318",
        "health_check_enabled": True,
        "profiling_enabled": False,
    },
    "features": {
        "web_socket": True,
        "streaming": True,
        "ai_assistant": False,
        "social_trading": False,
        "margin_trading": False,
        "futures_trading": False,
        "options_trading": False,
        "dark_mode": True,
        "ab_testing": True,
    },
}

ENV_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "development": {
        "app": {"environment": "development", "debug": True, "log_level": "debug"},
        "database": {"name": "tent_dev"},
        "market": {"rate_limit_per_second": 1000},
        "auth": {"jwt_expiry_minutes": 1440},
    },
    "staging": {
        "app": {"environment": "staging", "debug": True, "log_level": "info"},
        "database": {"name": "tent_staging", "pool_max": 20},
        "market": {"rate_limit_per_second": 100},
        "auth": {"jwt_expiry_minutes": 60},
        "monitoring": {"tracing_sample_rate": 0.5},
    },
    "production": {
        "app": {"environment": "production", "debug": False, "log_level": "info"},
        "database": {"name": "tent_production", "pool_max": 50, "pool_min": 10},
        "market": {"rate_limit_per_second": 10, "rate_limit_burst": 20},
        "auth": {"jwt_expiry_minutes": 60, "mfa_required": True},
        "monitoring": {"tracing_sample_rate": 0.01, "profiling_enabled": False},
        "features": {"ai_assistant": False, "margin_trading": True},
    },
}

SENSITIVE_KEYS = [
    "database.password", "redis.password", "auth.jwt_secret",
    "auth.jwt_secret", "auth.jwt_secret",
]
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data" / "config_generator.schema.json"


def format_path(path: str) -> str:
    return path or "<root>"


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def matches_schema_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_json_schema(data: Any, schema: Dict[str, Any], path: str = "") -> List[str]:
    errors: List[str] = []

    expected_type = schema.get("type")
    if expected_type:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(matches_schema_type(data, item) for item in expected_types):
            errors.append(
                f"{format_path(path)}: expected {expected_type}, got {json_type(data)}"
            )
            return errors

    if "enum" in schema and data not in schema["enum"]:
        allowed = ", ".join(repr(item) for item in schema["enum"])
        errors.append(f"{format_path(path)}: expected one of {allowed}, got {data!r}")

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{format_path(path)}: expected >= {schema['minimum']}, got {data}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{format_path(path)}: expected <= {schema['maximum']}, got {data}")

    if isinstance(data, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in data:
                child_path = f"{path}.{key}" if path else key
                errors.append(f"{child_path}: required property is missing")

        additional = schema.get("additionalProperties", True)
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else key
            if key in properties:
                errors.extend(validate_json_schema(value, properties[key], child_path))
            elif additional is False:
                errors.append(f"{child_path}: additional property is not allowed")
            elif isinstance(additional, dict):
                errors.extend(validate_json_schema(value, additional, child_path))

    if isinstance(data, list) and "items" in schema:
        item_schema = schema["items"]
        for index, item in enumerate(data):
            errors.extend(validate_json_schema(item, item_schema, f"{path}[{index}]"))

    return errors


def load_json_file(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_data_file(path: Path) -> Any:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_json_file(path)
    if suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            raise RuntimeError("PyYAML is required to read YAML input files")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    raise RuntimeError(f"Unsupported input file format for {path}; use JSON or YAML")


def load_schema(path: str) -> Dict[str, Any]:
    schema_path = Path(path)
    schema = load_json_file(schema_path)
    if not isinstance(schema, dict):
        raise RuntimeError(f"Schema must be a JSON object: {schema_path}")
    return schema


def print_validation_errors(label: str, errors: List[str]) -> None:
    print(f"{label} validation failed with {len(errors)} error(s):", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)


def qualify_validation_errors(label: str, errors: List[str]) -> List[str]:
    return [f"{label}.{error}" for error in errors]


def validate_internal_configs(
    schema: Dict[str, Any],
    default_config: Optional[Dict[str, Any]] = None,
    env_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Validate built-in defaults and every environment overlay before generation."""
    defaults = default_config if default_config is not None else DEFAULT_CONFIG
    overrides = env_overrides if env_overrides is not None else ENV_OVERRIDES

    errors = qualify_validation_errors(
        "DEFAULT_CONFIG",
        validate_json_schema(defaults, schema),
    )
    for env, env_override in overrides.items():
        errors.extend(
            qualify_validation_errors(
                f"ENV_OVERRIDES.{env}",
                validate_json_schema(env_override, schema),
            )
        )
        generated = merge_config(defaults, env_override)
        errors.extend(
            qualify_validation_errors(
                f"generated.{env}",
                validate_json_schema(generated, schema),
            )
        )
    return errors


def merge_config(base: Dict, override: Dict) -> Dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value
    return result


def generate_config(env: str, overrides: Optional[Dict] = None) -> Dict:
    config = dict(DEFAULT_CONFIG)
    if env in ENV_OVERRIDES:
        config = merge_config(config, ENV_OVERRIDES[env])
    if overrides:
        config = merge_config(config, overrides)
    return config


def mask_sensitive(config: Dict, prefix: str = "") -> Dict:
    masked = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if full_key in SENSITIVE_KEYS:
            masked[key] = "***REDACTED***"
        elif isinstance(value, dict):
            masked[key] = mask_sensitive(value, full_key)
        else:
            masked[key] = value
    return masked


def to_yaml(config: Dict) -> str:
    if not HAS_YAML:
        return "ERROR: PyYAML is not installed"
    return yaml.dump(config, default_flow_style=False, sort_keys=False)


def to_json(config: Dict, pretty: bool = True) -> str:
    if pretty:
        return json.dumps(config, indent=2, default=str)
    return json.dumps(config, default=str)


def to_toml(config: Dict) -> str:
    if not HAS_TOML:
        return "ERROR: toml is not installed"

    def flatten(config: Dict, prefix: str = "") -> Dict:
        result = {}
        for key, value in config.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.update(flatten(value, full_key))
            else:
                result[full_key] = value
        return result

    flat = flatten(config)
    lines = []
    for key, value in flat.items():
        parts = key.split(".")
        if len(parts) > 1:
            section = parts[0]
            sub_key = ".".join(parts[1:])
            if not any(line.startswith(f"[{section}]") for line in lines):
                lines.append(f"\n[{section}]")
            if isinstance(value, str):
                lines.append(f'{sub_key} = "{value}"')
            elif isinstance(value, bool):
                lines.append(f"{sub_key} = {str(value).lower()}")
            elif isinstance(value, list):
                items = ", ".join(f'"{item}"' if isinstance(item, str) else str(item) for item in value)
                lines.append(f"{sub_key} = [{items}]")
            else:
                lines.append(f"{sub_key} = {value}")
    return "\n".join(lines)


def to_dotenv(config: Dict, prefix: str = "") -> str:
    lines = [f"# Generated by config_generator.py", f"# Environment configuration", f"# Generated: {datetime.now().isoformat()}", ""]

    def flatten(config: Dict, current_prefix: str = ""):
        for key, value in config.items():
            full_key = f"{current_prefix}_{key}".upper() if current_prefix else key.upper()
            if isinstance(value, dict):
                flatten(value, full_key)
            elif isinstance(value, list):
                lines.append(f"{full_key}={','.join(str(v) for v in value)}")
            elif isinstance(value, bool):
                lines.append(f"{full_key}={str(value).lower()}")
            elif value is None:
                lines.append(f"{full_key}=")
            else:
                lines.append(f"{full_key}={value}")

    flatten(config)
    return "\n".join(lines)


def to_k8s_configmap(config: Dict, name: str = "app-config") -> str:
    data_lines = []
    for key, value in flatten_for_k8s(config):
        if isinstance(value, str) and not key.startswith("_"):
            data_lines.append(f"  {key}: {json.dumps(value)}")

    return f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {name}
  labels:
    app: tent-of-trials
data:
{chr(10).join(data_lines)}
"""


def flatten_for_k8s(config: Dict, prefix: str = "") -> List[tuple]:
    result = []
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.extend(flatten_for_k8s(value, full_key))
        else:
            result.append((full_key, value))
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="Configuration generator")
    parser.add_argument("--env", "-e", default="development",
                       choices=list(ENV_OVERRIDES.keys()),
                       help="Target environment")
    parser.add_argument("--format", "-f", default="yaml",
                       choices=["yaml", "json", "toml", "dotenv", "k8s-configmap"],
                       help="Output format")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--overrides",
                       help="JSON or YAML config override file to merge before rendering")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH),
                       help="JSON Schema file used to validate overrides and generated config")
    parser.add_argument("--show-sensitive", action="store_true",
                       help="Show sensitive values (default: masked)")
    parser.add_argument("--stdout", action="store_true",
                       help="Print to stdout instead of file")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        schema = load_schema(args.schema)
    except Exception as exc:
        print(f"Failed to load schema: {exc}", file=sys.stderr)
        return 1

    internal_errors = validate_internal_configs(schema)
    if internal_errors:
        print_validation_errors("Internal configuration", internal_errors)
        return 1

    overrides = None
    if args.overrides:
        try:
            overrides = load_data_file(Path(args.overrides))
        except Exception as exc:
            print(f"Failed to load overrides: {exc}", file=sys.stderr)
            return 1
        if not isinstance(overrides, dict):
            print("Override input must be a JSON or YAML object", file=sys.stderr)
            return 1
        override_errors = validate_json_schema(overrides, schema)
        if override_errors:
            print_validation_errors(f"Input {args.overrides}", override_errors)
            return 1

    config = generate_config(args.env, overrides)
    generated_errors = validate_json_schema(config, schema)
    if generated_errors:
        print_validation_errors("Generated config", generated_errors)
        return 1

    if not args.show_sensitive:
        display_config = mask_sensitive(config)
    else:
        display_config = config

    format_map = {
        "yaml": to_yaml,
        "json": to_json,
        "toml": to_toml,
        "dotenv": to_dotenv,
        "k8s-configmap": to_k8s_configmap,
    }

    output_fn = format_map.get(args.format)
    if not output_fn:
        print(f"Unsupported format: {args.format}")
        return 1

    output = output_fn(display_config)
    if args.format == "json":
        try:
            rendered = json.loads(output)
        except json.JSONDecodeError as exc:
            print(f"Generated JSON could not be parsed: {exc}", file=sys.stderr)
            return 1
        rendered_errors = validate_json_schema(rendered, schema)
        if rendered_errors:
            print_validation_errors("Rendered JSON", rendered_errors)
            return 1
    elif args.format == "yaml" and HAS_YAML:
        rendered = yaml.safe_load(output)
        rendered_errors = validate_json_schema(rendered, schema)
        if rendered_errors:
            print_validation_errors("Rendered YAML", rendered_errors)
            return 1

    if args.stdout or not args.output:
        print(output)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Configuration written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
