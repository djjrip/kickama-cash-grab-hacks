#!/usr/bin/env python3
"""Validate deterministic output from tools/data_generator.py."""

import filecmp
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "data_generator.py"
SEEDS = (7, 42, 2026)


def run_generator(output_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(GENERATOR),
        "--output-dir",
        str(output_dir),
        "--users",
        "5",
        "--orders",
        "8",
        "--trades",
        "8",
        "--ticks",
        "10",
        "--candles",
        "4",
        "--format",
        "json",
        *extra_args,
    ]
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=True)


def compare_dirs(left: Path, right: Path) -> None:
    comparison = filecmp.dircmp(left, right)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        raise AssertionError(
            f"Directory entries differ: left_only={comparison.left_only}, "
            f"right_only={comparison.right_only}, funny={comparison.funny_files}"
        )

    _, mismatches, errors = filecmp.cmpfiles(
        left,
        right,
        comparison.common_files,
        shallow=False,
    )
    if mismatches or errors:
        raise AssertionError(f"Generated files differ: mismatches={mismatches}, errors={errors}")


def assert_metadata(output_dir: Path, seed: int) -> None:
    metadata_path = output_dir / "metadata.json"
    if not metadata_path.exists():
        raise AssertionError("metadata.json was not generated")

    metadata = json.loads(metadata_path.read_text())
    if metadata.get("seed") != seed:
        raise AssertionError(f"metadata seed mismatch: expected {seed}, got {metadata.get('seed')}")


def validate_seed(seed: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        left = base / "left"
        right = base / "right"
        run_generator(left, "--seed", str(seed))
        run_generator(right, "--seed", str(seed))
        compare_dirs(left, right)
        assert_metadata(left, seed)


def validate_print_seed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "random"
        result = run_generator(output_dir, "--print-seed")
        seed_lines = [line for line in result.stdout.splitlines() if line.startswith("Generated seed:")]
        if not seed_lines:
            raise AssertionError("--print-seed did not print the generated seed")

        seed = int(seed_lines[0].split(":", 1)[1].strip())
        assert_metadata(output_dir, seed)


def main() -> None:
    for seed in SEEDS:
        validate_seed(seed)
    validate_print_seed()
    print("data_generator deterministic seed validation passed")


if __name__ == "__main__":
    main()
