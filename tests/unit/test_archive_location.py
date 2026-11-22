"""C31: the registry archive_path follows the archive root the archiver uses."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "rss"))

from archive_location import registry_archive_path, DEFAULT_ARCHIVE_ROOT  # noqa: E402


def test_root_from_env_is_used():
    assert registry_archive_path("FDA", "fda_drugs-x-abc", "/archive") == "/archive/fda/fda_drugs-x-abc"


def test_unset_root_falls_back_to_the_config_default():
    assert DEFAULT_ARCHIVE_ROOT == "/mnt/data/regulatory_archive"
    assert registry_archive_path("EMA", "ema-y", None) == "/mnt/data/regulatory_archive/ema/ema-y"


def test_no_authority_matches_the_archiver_layout():
    assert registry_archive_path("", "doc-z", "/archive") == "/archive/doc-z"


def test_trailing_slash_on_root_is_ignored():
    assert registry_archive_path("ICH", "d", "/archive/") == "/archive/ich/d"
