def run_text_process(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic UTF-8 text decoding."""
    kwargs.setdefault("text", True)
    kwargs.setdefault("env", subprocess_env())
    kwargs.setdefault("check", True)
    if kwargs.get("text") is not False:
        kwargs.setdefault("encoding", TEXT_ENCODING)
        kwargs.setdefault("errors", "replace")
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command '{' '.join(cmd)}' failed with code {e.returncode}") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"Command not found: {cmd[0]}") from e