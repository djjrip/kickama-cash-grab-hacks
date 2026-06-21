#!/usr/bin/env python3

import argparse
import datetime
import getpass
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
DIAGNOSTIC_DIR = ROOT / "diagnostic"
DIAGNOSTIC_CHUNK_SIZE = 40 * 1024 * 1024
ENCRYPTLY_BLOCKER_MESSAGE = "encryptly could not create an archive. You may have timed out; try launching it in the background and waiting for it to finish with no timeout due to a bug in encryptly."
TEXT_ENCODING = "utf-8"


def configure_text_encoding() -> None:
    """Use UTF-8 consistently for our console and captured child-process text."""
    os.environ.setdefault("PYTHONIOENCODING", TEXT_ENCODING)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=TEXT_ENCODING, errors="replace")
        except Exception:
            try:
                reconfigure(errors="replace")
            except Exception:
                pass


def subprocess_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    merged = os.environ.copy() if env is None else env.copy()
    merged.setdefault("PYTHONIOENCODING", TEXT_ENCODING)
    return merged


def run_text_process(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic UTF-8 text decoding."""
    kwargs.setdefault("text", True)
    if kwargs.get("text") is not False:
        kwargs.setdefault("encoding", TEXT_ENCODING)
        kwargs.setdefault("errors", "replace")
    if kwargs.get("env") is not None:
        kwargs["env"] = subprocess_env(kwargs["env"])
    return subprocess.run(cmd, **kwargs)


configure_text_encoding()


def current_commit_id() -> str:
    """Return the first 4 bytes (8 hex chars) of HEAD for stable per-commit diagnostics."""
    try:
        result = run_text_process(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        commit = result.stdout.strip()
        if result.returncode == 0 and len(commit) >= 8:
            return commit[:8]
    except Exception:
        pass
    return "00000000"


def diagnostic_paths_for_commit() -> tuple[Path, Path, str]:
    """Return stable diagnostic artifact paths under diagnostic/ for the current commit."""
    DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
    commit_id = current_commit_id()
    logd_path = DIAGNOSTIC_DIR / f"build-{commit_id}.logd"
    metadata_path = DIAGNOSTIC_DIR / f"build-{commit_id}.json"
    return logd_path, metadata_path, commit_id


def split_diagnostic_logd(logd_path: Path, chunk_size: int = DIAGNOSTIC_CHUNK_SIZE) -> list[Path]:
    """Split an oversized .logd into numbered .logd chunks and remove the original."""
    if logd_path.stat().st_size <= chunk_size:
        return [logd_path]

    chunks: list[Path] = []
    stem = logd_path.stem
    with logd_path.open("rb") as source:
        index = 1
        while True:
            data = source.read(chunk_size)
            if not data:
                break
            chunk_path = logd_path.with_name(f"{stem}-part{index:03d}.logd")
            chunk_path.write_bytes(data)
            chunks.append(chunk_path)
            index += 1

    logd_path.unlink()
    return chunks


@dataclass
class Module:
    name: str
    language: str
    dir: Path
    build_cmd: list[str]
    clean_cmd: list[str]
    build_dir: Optional[Path] = None
    env: Optional[dict[str, str]] = None

MODULES = [
    Module(
        name="backend",
        language="Rust",
        dir=ROOT / "backend",
        build_cmd=["cargo", "build"],
        clean_cmd=["cargo", "clean"],
        build_dir=ROOT / "backend" / "target",
        env={"CARGO_TERM_COLOR": "always"},
    ),
    Module(
        name="frontend",
        language="TypeScript",
        dir=ROOT / "frontend",
        build_cmd=["npm", "run", "build"],
        clean_cmd=["rm", "-rf", "node_modules", "dist"],
        build_dir=ROOT / "frontend" / "dist",
        env={"NODE_ENV": "production"},
    ),
    Module(
        name="market",
        language="Go",
        dir=ROOT / "market",
        build_cmd=["go", "build", "-o", "market", "."],
        clean_cmd=["rm", "-f", "market"],
        build_dir=ROOT / "market" / "market",
    ),
    Module(
        name="frailbox",
        language="C",
        dir=ROOT / "frailbox",
        build_cmd=["make"],
        clean_cmd=["make", "distclean"],
        build_dir=ROOT / "frailbox" / "frailbox",
    ),
    Module(
        name="engine",
        language="C++",
        dir=ROOT / "frailbox" / "engine",
        build_cmd=["cmake", "--build", "build"],
        clean_cmd=["rm", "-rf", "build"],
        build_dir=ROOT / "frailbox" / "engine" / "build" / "trial-engine",
    ),
    Module(
        name="compliance",
        language="Java",
        dir=ROOT / "compliance",
        build_cmd=["javac", "-d", "build", "ComplianceAuditor.java"],
        clean_cmd=["rm", "-rf", "build"],
        build_dir=ROOT / "compliance" / "build",
    ),
    Module(
        name="v2-market-stream",
        language="Ruby",
        dir=ROOT / "v2" / "services",
        build_cmd=["ruby", "-c", "market_stream.rb"],
        clean_cmd=["echo", "Ruby has no build artifacts to clean"],
        build_dir=None,
    ),
    Module(
        name="nfc-scanner",
        language="Lua",
        dir=ROOT / "frailbox" / "nfc",
        build_cmd=["luac", "-p", "scanner.lua"],
        clean_cmd=["echo", "Lua has no build artifacts to clean"],
        build_dir=None,
    ),
    Module(
        name="openapi-haskell",
        language="Haskell",
        dir=ROOT / "docs" / "openapi",
        build_cmd=["ghc", "-fno-code", "Types.hs", "Server.hs", "Validate.hs", "Generate.hs"],
        clean_cmd=["rm", "-f", "*.hi", "*.o", "*.hie"],
        build_dir=None,
    ),
    Module(
        name="openapi-tools",
        language="Lua",
        dir=ROOT / "tools",
        build_cmd=["luac", "-p", "openapi_diff.lua", "openapi_mock.lua", "openapi_pact.lua"],
        clean_cmd=["echo", "Nothing to clean"],
        build_dir=None,
    ),
]

ENCRYPTLY_DIR = ROOT / "tools" / "encryptly"
ENCRYPTLY_BINARIES = {
    "linux-x64": ENCRYPTLY_DIR / "linux-x64" / "encryptly",
    "linux-arm64": ENCRYPTLY_DIR / "linux-arm64" / "encryptly",
    "macos-arm64": ENCRYPTLY_DIR / "macos-arm64" / "encryptly",
    "macos-x64": ENCRYPTLY_DIR / "macos-x64" / "encryptly",
    "windows-x64": ENCRYPTLY_DIR / "windows-x64" / "encryptly.exe",
    "windows-arm64": ENCRYPTLY_DIR / "windows-arm64" / "encryptly.exe",
}
LEGACY_ENCRYPTLY_BIN = ENCRYPTLY_DIR / "encryptly"


def _normalize_arch(machine: str) -> Optional[str]:
    machine = machine.lower()
    if machine in {"x86_64", "amd64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return None


def _normalize_os() -> Optional[str]:
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return None


def detect_encryptly_platform() -> Optional[str]:
    os_name = _normalize_os()
    arch = _normalize_arch(platform.machine())
    if os_name is None or arch is None:
        return None
    return f"{os_name}-{arch}"


def get_encryptly_bin() -> Optional[Path]:
    target = detect_encryptly_platform()
    if target is not None:
        binary = ENCRYPTLY_BINARIES.get(target)
        if binary is not None and binary.exists():
            return binary

    if LEGACY_ENCRYPTLY_BIN.exists():
        return LEGACY_ENCRYPTLY_BIN

    return None


def encryptly_platform_help() -> str:
    detected = detect_encryptly_platform() or "unsupported"
    available = ", ".join(sorted(ENCRYPTLY_BINARIES))
    return f"detected {detected}; available: {available}"


def check_encryptly_runs(timeout: int = 600) -> tuple[bool, str]:
    """Verify encryptly can create a diagnostic bundle before doing any build work."""
    encryptly_bin = get_encryptly_bin()
    if encryptly_bin is None:
        return False, f"encryptly binary not found ({encryptly_platform_help()})"

    workspace = Path.home() / ".cache" / "tent-of-trials" / "encryptly-preflight"
    safe_dir = workspace / "safe"
    output_dir = workspace / "out"
    logd_path = output_dir / "preflight.logd"
    try:
        shutil.rmtree(workspace, ignore_errors=True)
        safe_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        (safe_dir / "preflight.txt").write_text("encryptly preflight, if it fails, increase your timeout\n", encoding="utf-8")
        result = run_text_process(
            [
                str(encryptly_bin),
                "pack",
                str(logd_path),
                "--include",
                str(safe_dir),
                "--max-file-size",
                "32000",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            output = result.stderr.strip() or result.stdout.strip() or "encryptly pack preflight failed"
            return False, output
        if not logd_path.exists():
            return False, "encryptly preflight completed without creating a .logd"
        return True, "encryptly preflight passed"
    except subprocess.TimeoutExpired:
        return False, f"encryptly preflight TIMEOUT ({timeout}s)"
    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    GRAY = "\033[90m"

def color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{code}{text}{Colors.RESET}"


def _json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def log_event(event: str, level: str = "info", message: str = "", **fields) -> None:
    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": level,
        "event": event,
    }
    if message:
        record["message"] = message
    record.update({key: _json_safe(value) for key, value in fields.items() if value is not None})
    sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
    sys.stdout.flush()


def check_prerequisites() -> list[str]:
    required = {
        "cargo": "Rust",
        "npm": "Node.js",
        "go": "Go",
        "gcc": "C (GCC)",
        "g++": "C++ (GCC)",
        "cmake": "CMake",
        "make": "Make",
        "python3": "Python",
        "javac": "Java (JDK)",
        "ruby": "Ruby",
        "luac": "Lua",
        "ghc": "GHC (Haskell)",
    }

    missing = []
    for cmd, label in required.items():
        if shutil.which(cmd) is None:
            missing.append(f"{label} ({cmd})")

    return missing

def build_module(
    module: Module,
    release: bool = False,
    verbose: bool = False,
) -> tuple[bool, float, str]:

    log_event(
        "module_build_started",
        message=f"Building {module.name}",
        module=module.name,
        language=module.language,
    )

    env = os.environ.copy()
    if module.env:
        env.update(module.env)

    start = time.time()

    if module.name == "frontend":
        node_modules = module.dir / "node_modules"
        if not node_modules.exists():
            log_event("dependency_install_started", message="npm install", module=module.name)
            try:
                install_result = run_text_process(
                    ["npm", "install"],
                    cwd=str(module.dir),
                    capture_output=not verbose,
                    text=True,
                    timeout=120,
                    env={k: v for k, v in env.items() if k != "NODE_ENV"},
                )
                if install_result.returncode != 0:
                    return False, time.time() - start, f"npm install failed:\n{install_result.stderr}"
            except subprocess.TimeoutExpired:
                return False, time.time() - start, "npm install TIMEOUT (120s)"

    if module.name == "engine":

        build_type = "Release" if release else "Debug"
        try:
            cfg_result = run_text_process(
                ["cmake", "-S", ".", "-B", "build",
                 f"-DCMAKE_BUILD_TYPE={build_type}"],
                cwd=str(module.dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return False, time.time() - start, "CMake configure TIMEOUT (120s)"
        except FileNotFoundError as e:
            return False, 0, f"Command not found: {e}"
        if cfg_result.returncode != 0:
            output_lines = []
            if cfg_result.stdout:
                output_lines.append(cfg_result.stdout.strip())
            if cfg_result.stderr:
                output_lines.append(cfg_result.stderr.strip())
            output = "\n".join(output_lines)
            return False, time.time() - start, (
                f"CMake configure failed:\n{output}")
        if verbose:
            log_event("cmake_configured", message="cmake configured", module=module.name)
        cmd = ["cmake", "--build", "build"]
        if release:
            cmd.append("--config")
            cmd.append("Release")
    else:
        cmd = list(module.build_cmd)
        if release and module.name == "backend":
            cmd.append("--release")

    try:
        result = run_text_process(
            cmd,
            cwd=str(module.dir),
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, time.time() - start, "BUILD TIMEOUT (300s)"
    except FileNotFoundError as e:
        return False, 0, f"Command not found: {e}"

    elapsed = time.time() - start
    output_lines = []

    if result.stdout:
        output_lines.append(result.stdout.strip())
    if result.stderr:
        output_lines.append(result.stderr.strip())

    output = "\n".join(output_lines)
    success = result.returncode == 0

    return success, elapsed, output

def clean_module(module: Module, verbose: bool = False) -> bool:
    log_event("module_clean_started", message=f"Cleaning {module.name}", module=module.name)
    try:
        run_text_process(
            module.clean_cmd,
            cwd=str(module.dir),
            capture_output=not verbose,
            text=True,
            timeout=60,
            env=os.environ.copy(),
        )
        return True
    except Exception as e:
        log_event("module_clean_failed", level="error", message="Clean failed", module=module.name, error=str(e))
        return False

def verify_binary(module: Module) -> Optional[str]:
    if module.build_dir is None:
        return None
    path = module.build_dir
    if module.name == "backend":

        target = path / "debug" / module.name
        if not target.exists():
            target = path / "release" / module.name
        if target.exists():
            return str(target)
    if path.exists():
        return str(path)
    return None

def run_cmd(cmd: list[str], **kwargs) -> tuple[bool, str]:
    try:
        result = run_text_process(
            cmd, capture_output=True, text=True, check=False, **kwargs
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return result.returncode == 0, output.strip()
    except Exception as e:
        return False, str(e)


def collect_system_info() -> str:
    lines = [
        "Tent of Trials - System Diagnostic Snapshot",
        "=" * 50,
        f"generated_at: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        f"hostname: {platform.node()}",
        f"user: {getpass.getuser()}",
        f"python: {sys.version}",
        f"platform: {platform.platform()}",
        f"processor: {platform.processor() or 'unknown'}",
        f"cpu_count: {os.cpu_count()}",
        "",
        "--- uname ---",
    ]
    ok, out = run_cmd(["uname", "-a"])
    lines.append(out if ok else "unavailable")

    lines.extend(["", "--- /etc/os-release ---"])
    try:
        lines.append((Path("/etc/os-release")).read_text(encoding="utf-8", errors="replace").strip())
    except Exception as e:
        lines.append(f"unavailable: {e}")

    lines.extend(["", "--- memory ---"])
    ok, out = run_cmd(["free", "-h"])
    lines.append(out if ok else "unavailable")

    lines.extend(["", "--- disk ---"])
    ok, out = run_cmd(["df", "-h"])
    lines.append(out if ok else "unavailable")

    lines.extend(["", "--- build environment ---"])
    for key in ["SHELL", "LANG", "TERM", "XDG_SESSION_TYPE", "DISPLAY", "EDITOR"]:
        value = os.environ.get(key)
        if value:
            lines.append(f"{key}={value}")

    lines.append("")
    return "\n".join(lines)


def build_diagnostic_report(
    results: list[tuple[str, bool, float, str, Optional[str]]],
    commit_id: str,
    logd_relpaths: Optional[list[str]] = None,
    password: Optional[str] = None,
    logd_error: Optional[str] = None,
    chunked: bool = False,
    message_blocker: Optional[str] = None,
) -> dict:
    diagnostic_logd: Optional[str | list[str]]
    if not logd_relpaths:
        diagnostic_logd = None
    elif len(logd_relpaths) == 1:
        diagnostic_logd = logd_relpaths[0]
    else:
        diagnostic_logd = logd_relpaths

    decrypt_target = logd_relpaths[0] if logd_relpaths and len(logd_relpaths) == 1 else None
    if logd_relpaths and len(logd_relpaths) > 1:
        decrypt_target = str((DIAGNOSTIC_DIR / f"build-{commit_id}.logd").relative_to(ROOT))

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit": commit_id,
        "diagnostic_logd": diagnostic_logd,
        "diagnostic_logd_error": logd_error,
        "message_blocker": message_blocker,
        "chunked": chunked,
        "chunk_size_bytes": DIAGNOSTIC_CHUNK_SIZE if chunked else None,
        "password": password,
        "decrypt_command": (
            f"encryptly unpack {decrypt_target} <outdir> --password {password}"
            if decrypt_target and password else None
        ),
        "total_modules": len(results),
        "passed": sum(1 for _, s, _, _, _ in results if s),
        "failed": sum(1 for _, s, _, _, _ in results if not s),
        "modules": [
            {
                "name": name,
                "status": "PASS" if success else "FAIL",
                "elapsed_seconds": round(elapsed, 3),
                "artifact": binary,
                "output": output,
            }
            for name, success, elapsed, output, binary in results
        ],
        "pr_note": (
            (f"Include the encrypted diagnostic logd artifact(s): {', '.join(logd_relpaths)}. " if logd_relpaths else "Encrypted diagnostic logd artifact was not created; include this JSON report showing why. ")
            + "The encrypted .logd is the required diagnostic content for PR review; this JSON file is metadata. "
            + "Maintainers may ask you to remove these diagnostic artifacts before merging."
        ),
    }
    return report


def write_diagnostic_report(metadata_path: Path, report: dict) -> None:
    metadata_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    log_event(
        "diagnostic_metadata_created",
        message="Diagnostic metadata created",
        path=str(metadata_path.relative_to(ROOT)),
    )


def commit_diagnostic_artifacts(paths: list[Path], commit_id: str) -> bool:
    """Commit diagnostic files as soon as they are produced."""
    existing = [path for path in paths if path.exists()]
    if not existing:
        log_event(
            "diagnostic_artifacts_missing",
            level="error",
            message="No diagnostic artifacts found to commit",
        )
        return False

    relpaths = [str(path.relative_to(ROOT)) for path in existing]
    status = run_text_process(
        ["git", "status", "--porcelain", "--", *relpaths],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if status.returncode != 0:
        log_event(
            "diagnostic_git_status_failed",
            level="error",
            message="Could not inspect diagnostic git status",
            stderr=status.stderr.strip(),
        )
        return False
    if not status.stdout.strip():
        log_event(
            "diagnostic_artifacts_already_committed",
            message="Diagnostic artifacts already committed",
            paths=relpaths,
        )
        return True

    add = run_text_process(
        ["git", "add", "--", *relpaths],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if add.returncode != 0:
        log_event(
            "diagnostic_git_add_failed",
            level="error",
            message="Could not stage diagnostic artifacts",
            stderr=add.stderr.strip(),
            paths=relpaths,
        )
        return False

    commit = run_text_process(
        ["git", "commit", "-m", f"Add build diagnostics for {commit_id}", "--", *relpaths],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if commit.returncode != 0:
        output = commit.stderr.strip() or commit.stdout.strip()
        log_event(
            "diagnostic_git_commit_failed",
            level="error",
            message="Could not commit diagnostic artifacts",
            output=output,
            paths=relpaths,
        )
        return False

    log_event("diagnostic_artifacts_committed", message="Diagnostic artifacts committed", paths=relpaths)
    return True


def generate_logd(
    results: list[tuple[str, bool, float, str, Optional[str]]],
    verbose: bool = False,
) -> bool:
    logd_path, metadata_path, commit_id = diagnostic_paths_for_commit()
    display_logd = logd_path.relative_to(ROOT)
    log_event(
        "diagnostic_finalize_started",
        message="Finalizing diagnostics",
        path=str(display_logd),
        commit=commit_id,
    )

    # Always write the JSON report first. The encrypted .logd is useful, but the
    # report is required even when the build failed before compilation started or
    # when encryptly itself is unavailable.
    write_diagnostic_report(metadata_path, build_diagnostic_report(results, commit_id))

    encryptly_bin = get_encryptly_bin()
    if encryptly_bin is None:
        error = f"encryptly binary not found ({encryptly_platform_help()}); cannot create {display_logd}"
        log_event("encryptly_missing", level="error", message=error, path=str(display_logd))
        write_diagnostic_report(
            metadata_path,
            build_diagnostic_report(
                results,
                commit_id,
                logd_error=error,
                message_blocker=ENCRYPTLY_BLOCKER_MESSAGE,
            ),
        )
        log_event("encryptly_blocker", level="error", message=ENCRYPTLY_BLOCKER_MESSAGE)
        commit_diagnostic_artifacts([metadata_path], commit_id)
        return False

    # Workspace must live under $HOME because encryptly refuses paths outside home.
    home = Path.home()
    workspace = home / ".cache" / "tent-of-trials" / "logd-workspace"
    safe_dir = workspace / "safe"

    try:
        shutil.rmtree(workspace, ignore_errors=True)
        safe_dir.mkdir(parents=True, exist_ok=True)

        (safe_dir / "system-info.txt").write_text(
            collect_system_info(), encoding="utf-8"
        )

        summary_lines = [
            "Tent of Trials - Build Summary",
            "=" * 50,
            f"generated_at: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            f"total_modules: {len(results)}",
            f"passed: {sum(1 for _, s, _, _, _ in results if s)}",
            f"failed: {sum(1 for _, s, _, _, _ in results if not s)}",
            "",
            "module results:",
        ]
        for name, success, elapsed, _, binary in results:
            summary_lines.append(
                f"  {name}: {'PASS' if success else 'FAIL'} ({elapsed:.2f}s)"
                f"{f' [{binary}]' if binary else ''}"
            )
        (safe_dir / "build-summary.txt").write_text(
            "\n".join(summary_lines), encoding="utf-8"
        )

        log_lines = []
        for name, success, elapsed, output, binary in results:
            log_lines.append(
                f"\n{'=' * 50}\n{name} ({'PASS' if success else 'FAIL'}, {elapsed:.2f}s)\n"
                f"{'=' * 50}"
            )
            if binary:
                log_lines.append(f"artifact: {binary}")
            if output:
                log_lines.append(output)
        (safe_dir / "build.log").write_text("\n".join(log_lines), encoding="utf-8")

        sr = run_text_process(
            [
                str(encryptly_bin),
                "pack",
                str(logd_path),
                "--include",
                str(workspace),
                "--max-file-size",
                "61440",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=1500,
        )
        if sr.returncode != 0:
            error = sr.stderr.strip() or sr.stdout.strip() or "encryptly pack failed"
            log_event(
                "diagnostic_logd_creation_failed",
                level="error",
                message="Diagnostic log creation failed",
                path=str(logd_path.relative_to(ROOT)),
                error=error,
            )
            if logd_path.exists():
                logd_path.unlink()
            write_diagnostic_report(
                metadata_path,
                build_diagnostic_report(
                    results,
                    commit_id,
                    logd_error=error,
                    message_blocker=ENCRYPTLY_BLOCKER_MESSAGE,
                ),
            )
            log_event("encryptly_blocker", level="error", message=ENCRYPTLY_BLOCKER_MESSAGE)
            commit_diagnostic_artifacts([metadata_path], commit_id)
            return False

        safe_pw = sr.stdout.strip()
        logd_files = split_diagnostic_logd(logd_path)
        logd_relpaths = [str(path.relative_to(ROOT)) for path in logd_files]
        decrypt_target = logd_relpaths[0] if len(logd_relpaths) == 1 else str(logd_path.relative_to(ROOT))
        write_diagnostic_report(
            metadata_path,
            build_diagnostic_report(
                results,
                commit_id,
                logd_relpaths=logd_relpaths,
                password=safe_pw,
                chunked=len(logd_files) > 1,
            ),
        )

        for path in logd_files:
            size_kb = path.stat().st_size / 1024.0
            log_event(
                "diagnostic_logd_created",
                message="Diagnostic log created",
                path=str(path.relative_to(ROOT)),
                size_kb=round(size_kb, 1),
            )
        if len(logd_files) > 1:
            log_event(
                "diagnostic_logd_split",
                message="Split oversized diagnostic log",
                chunks=len(logd_files),
                chunk_size_mib=DIAGNOSTIC_CHUNK_SIZE // (1024 * 1024),
            )
        if not commit_diagnostic_artifacts([metadata_path, *logd_files], commit_id):
            return False

        if safe_pw:
            log_event(
                "diagnostic_password_created",
                message="Password required to decrypt the diagnostic log",
                password=safe_pw,
                diagnostic_logd=decrypt_target,
                metadata_path=str(metadata_path.relative_to(ROOT)),
            )
            if len(logd_files) > 1:
                log_event(
                    "diagnostic_reassemble_required",
                    message="Reassemble diagnostic chunks in order before unpacking",
                    chunks=logd_relpaths,
                    output=str(logd_path.relative_to(ROOT)),
                )
            log_event(
                "diagnostic_unpack_command",
                message="encryptly unpack command",
                command=f"encryptly unpack {decrypt_target} <outdir> --password {safe_pw}",
            )
        return True

    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def print_summary(results: list[tuple[str, bool, float, str, Optional[str]]]):
    total = len(results)
    passed = sum(1 for _, s, _, _, _ in results if s)
    failed = total - passed
    total_time = sum(t for _, _, t, _, _ in results)

    log_event(
        "build_summary_started",
        message="Build Summary",
        total_modules=total,
        passed=passed,
        failed=failed,
        elapsed_seconds=round(total_time, 3),
    )

    for name, success, elapsed, output, binary in results:
        fields = {
            "module": name,
            "status": "PASS" if success else "FAIL",
            "elapsed_seconds": round(elapsed, 3),
            "artifact": binary,
        }
        if not success and output:
            fields["last_output"] = output.strip().split("\n")[-5:]
        log_event(
            "module_build_result",
            level="info" if success else "error",
            message=f"{name} {'PASS' if success else 'FAIL'}",
            **fields,
        )

    log_event(
        "build_summary_completed",
        message="Build summary completed",
        total_modules=total,
        passed=passed,
        failed=failed,
        elapsed_seconds=round(total_time, 3),
    )

def main():
    parser = argparse.ArgumentParser(
        description="Tent of Trials  -  Multi-Language Build System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 build.py                    Build all modules
  python3 build.py -m backend         Build only backend
  python3 build.py -m frontend,market Build frontend and market
  python3 build.py --clean            Clean all artifacts
  python3 build.py --release          Release build (Rust only)
  python3 build.py --verbose          Verbose output

Diagnostic bundle:
  python3 build.py
        """,
    )
    parser.add_argument(
        "-m", "--module",
        help="Module(s) to build (comma-separated, or 'all')",
        default="all",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Clean build artifacts instead of building",
    )
    parser.add_argument(
        "--release", action="store_true",
        help="Build in release mode (Rust backend)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show detailed build output",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available modules and exit",
    )

    args = parser.parse_args()

    log_event(
        "build_started",
        message="Tent of Trials build started",
        working_directory=str(ROOT),
        module=args.module,
        clean=args.clean,
        release=args.release,
        verbose=args.verbose,
    )

    if args.list:
        for m in MODULES:
            log_event(
                "module_available",
                message=f"{m.name} ({m.language})",
                module=m.name,
                language=m.language,
                directory=str(m.dir.relative_to(ROOT)),
                build_command=m.build_cmd,
            )
        return 0

    log_event("prerequisite_check_started", message="Checking prerequisites")
    missing = check_prerequisites()
    if missing:
        for m in missing:
            log_event("prerequisite_missing", level="warning", message=m, tool=m)

        msg = "Not all modules will build. That's fine."
        log_event("prerequisite_check_warning", level="warning", message=msg, missing=missing)
    else:
        log_event("prerequisite_check_passed", message="All prerequisites found")
    if args.module == "all":
        selected = MODULES
    else:
        names = [n.strip() for n in args.module.split(",")]
        selected = [m for m in MODULES if m.name in names]
        not_found = set(names) - {m.name for m in MODULES}
        if not_found:
            log_event(
                "unknown_modules",
                level="error",
                message="Unknown modules requested",
                modules=sorted(not_found),
                available=[m.name for m in MODULES],
            )
            return 1

    if not selected:
        log_event("no_modules_selected", level="warning", message="No modules selected")
        return 0

    if args.clean:
        log_event("clean_started", message="Cleaning build artifacts", modules=[m.name for m in selected])
        for module in selected:
            clean_module(module, args.verbose)

        diagnostic_artifacts = [ROOT / "build.logd"]
        if DIAGNOSTIC_DIR.exists():
            diagnostic_artifacts.extend(DIAGNOSTIC_DIR.glob("build-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].logd"))
            diagnostic_artifacts.extend(DIAGNOSTIC_DIR.glob("build-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-part*.logd"))
            diagnostic_artifacts.extend(DIAGNOSTIC_DIR.glob("build-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].json"))
            diagnostic_artifacts.extend(DIAGNOSTIC_DIR.glob("build-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-metadata.json"))
        for artifact in diagnostic_artifacts:
            if artifact.exists():
                if artifact.is_dir():
                    shutil.rmtree(artifact)
                else:
                    artifact.unlink()
                log_event(
                    "build_artifact_removed",
                    message="Removed build artifact",
                    path=str(artifact.relative_to(ROOT)),
                )
        log_event("clean_completed", message="Clean complete")
        return 0

    log_event("encryptly_check_started", message="Checking encryptly diagnostics")
    encryptly_start = time.time()
    encryptly_ok, encryptly_message = check_encryptly_runs()
    if not encryptly_ok:
        elapsed = time.time() - encryptly_start
        blocker = f"{ENCRYPTLY_BLOCKER_MESSAGE} {encryptly_message}"
        log_event(
            "encryptly_check_failed",
            level="error",
            message="encryptly cannot run",
            blocker=blocker,
            elapsed_seconds=round(elapsed, 3),
        )
        results = [("encryptly-preflight", False, elapsed, blocker, None)]
        generate_logd(results, args.verbose)
        return 1
    log_event("encryptly_check_passed", message="encryptly runs")

    log_event(
        "modules_build_started",
        message="Building selected modules",
        module_count=len(selected),
        release=args.release,
        modules=[m.name for m in selected],
    )

    results: list[tuple[str, bool, float, str, Optional[str]]] = []

    for module in selected:
        success, elapsed, output = build_module(module, args.release, args.verbose)
        binary = verify_binary(module) if success else None
        results.append((module.name, success, elapsed, output, binary))

    print_summary(results)

    diagnostics_ok = generate_logd(results, args.verbose)

    return 0 if diagnostics_ok and all(r[1] for r in results) else 1

if __name__ == "__main__":
    sys.exit(main())
