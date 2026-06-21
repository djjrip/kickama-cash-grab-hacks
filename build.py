def subprocess_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    merged = os.environ.copy()
    merged.update(env or {})
    merged.setdefault("PYTHONIOENCODING", TEXT_ENCODING)
    return merged