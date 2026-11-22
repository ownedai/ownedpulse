"""Merge keys into a registry metadata_json value without dropping other keys."""


def merge_metadata(existing, updates: dict) -> dict:
    """Return the existing metadata with `updates` applied.

    Keys in `updates` replace their old values; every other existing key is kept.
    `existing` may be None or a non-dict and is then treated as empty.
    """
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(updates)
    return merged
