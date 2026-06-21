def subprocess_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Create a subprocess environment with UTF-8 encoding defaults.
    
    Args:
        env: Optional base environment to extend. Uses os.environ if None.
    
    Returns:
        A new environment dictionary with PYTHONIOENCODING set.
    """
    merged = os.environ.copy() if env is None else env.copy()
    merged["PYTHONIOENCODING"] = TEXT_ENCODING  # Force set rather than default
    return merged


def run_text_process(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic UTF-8 text decoding.
    
    Args:
        cmd: Command to execute as list of strings
        **kwargs: Additional arguments passed to subprocess.run()
    
    Returns:
        CompletedProcess instance with text output
    
    Raises:
        subprocess.CalledProcessError: If the process returns non-zero
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", TEXT_ENCODING)
    kwargs.setdefault("errors", "replace")
    kwargs.setdefault("env", subprocess_env(kwargs.get("env")))
    return subprocess.run(cmd, **kwargs)