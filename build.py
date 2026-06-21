def subprocess_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    merged = os.environ.copy()
    if env is not None:
        merged.update(env)
    merged.setdefault("PYTHONIOENCODING", TEXT_ENCODING)
    return merged