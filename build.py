def subprocess_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Create environment dict for subprocesses with proper encoding and sharding support."""
    merged = os.environ.copy()
    if env is not None:
        merged.update(env)
    merged.setdefault("PYTHONIOENCODING", TEXT_ENCODING)
    merged.setdefault("DB_SHARDING_ENABLED", "false")
    return merged