def configure_text_encoding() -> None:
    """Use UTF-8 consistently for our console and captured child-process text."""
    os.environ.setdefault("PYTHONIOENCODING", TEXT_ENCODING)
    import json
    log_entry = {
        "timestamp": time.time(),
        "level": "INFO",
        "message": "Configuring text encoding",
        "encoding": TEXT_ENCODING
    }
    print(json.dumps(log_entry))
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=TEXT_ENCODING, errors="replace")
            log_entry["message"] = f"Successfully reconfigured {stream.name}"
            print(json.dumps(log_entry))
        except Exception as e:
            log_entry.update({
                "level": "ERROR",
                "message": f"Failed to reconfigure {stream.name}",
                "error": str(e)
            })
            print(json.dumps(log_entry))
            try:
                reconfigure(errors="replace")
                log_entry.update({
                    "level": "WARNING",
                    "message": f"Fallback reconfigured {stream.name} without encoding"
                })
                print(json.dumps(log_entry))
            except Exception as e:
                log_entry.update({
                    "level": "ERROR",
                    "message": f"Failed fallback reconfiguration of {stream.name}",
                    "error": str(e)
                })
                print(json.dumps(log_entry))