def run_text_process(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic UTF-8 text decoding.
    
    Args:
        cmd: Command to run as list of strings
        **kwargs: Additional arguments to pass to subprocess.run()
    
    Returns:
        CompletedProcess instance
    
    Raises:
        subprocess.CalledProcessError: If the process returns non-zero exit code
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", True)
    kwargs.setdefault("env", subprocess_env())
    
    if kwargs.get("text") is not False:
        kwargs.setdefault("encoding", TEXT_ENCODING)
        kwargs.setdefault("errors", "replace")
    
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.CalledProcessError as e:
        raise e
    except Exception as e:
        raise RuntimeError(f"Failed to run command {cmd}: {str(e)}") from e