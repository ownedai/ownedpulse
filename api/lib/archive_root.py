"""Archive root for ingestion subprocesses started by the API container."""

# Bind mount of data/regulatory_archive (docker-compose.yml, api service volumes).
ARCHIVE_ROOT_IN_CONTAINER = "/archive"


def with_archive_root(env) -> dict:
    """Return a copy of env with ARCHIVE_ROOT set to the bind-mounted archive when
    it is not already set. Without it, the pipeline writes into the container's
    writable layer, which install.sh discards when it recreates the container."""
    out = dict(env)
    if not out.get("ARCHIVE_ROOT"):
        out["ARCHIVE_ROOT"] = ARCHIVE_ROOT_IN_CONTAINER
    return out
