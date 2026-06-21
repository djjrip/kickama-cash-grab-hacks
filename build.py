def subprocess_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    merged = os.environ.copy() if env is None else env.copy()
    merged.setdefault("PYTHONIOENCODING", TEXT_ENCODING)
    merged.setdefault("PGCLIENTENCODING", TEXT_ENCODING)  # For PostgreSQL
    merged.setdefault("MYSQL_CHARSET", "utf8mb4")  # For MySQL
    return merged


def run_text_process(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic UTF-8 text decoding."""
    kwargs.setdefault("text", True)
    kwargs.setdefault("env", subprocess_env())
    if kwargs.get("text") is not False:
        kwargs.setdefault("encoding", TEXT_ENCODING)
        kwargs.setdefault("errors", "replace")
    return subprocess.run(cmd, **kwargs)