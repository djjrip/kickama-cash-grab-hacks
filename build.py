def subprocess_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Create environment dict for subprocess with proper encoding settings.
    
    Args:
        env: Optional base environment dict
    
    Returns:
        Environment dict with encoding settings
    """
    merged = os.environ.copy() if env is None else env.copy()
    merged.update({
        "PYTHONIOENCODING": TEXT_ENCODING,
        "PYTHONUTF8": "1",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8"
    })
    return merged