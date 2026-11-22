"""Registry archive_path for a feed item, built from the archive root the archiver uses."""

# Default of scripts/ingestion/config.py when ARCHIVE_ROOT is unset (container layer only).
DEFAULT_ARCHIVE_ROOT = "/mnt/data/regulatory_archive"


def registry_archive_path(authority: str, doc_id: str, archive_root=None) -> str:
    """Same layout as archive.py: <root>/<authority lowercased>/<doc_id>.
    With no authority the archiver writes <root>/<doc_id>, so this does too."""
    root = (archive_root or DEFAULT_ARCHIVE_ROOT).rstrip("/")
    if authority:
        return f"{root}/{authority.lower()}/{doc_id}"
    return f"{root}/{doc_id}"
