def run_text_process(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic UTF-8 text decoding.
    
    Enhanced with better error handling and timeout support for database operations.
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", 30)  # Default timeout for DB operations
    kwargs.setdefault("check", True)  # Raise exception on non-zero exit
    
    if kwargs.get("text") is not False:
        kwargs.setdefault("encoding", TEXT_ENCODING)
        kwargs.setdefault("errors", "replace")
    
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Process timed out after {kwargs['timeout']} seconds")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Process failed with exit code {e.returncode}") from e