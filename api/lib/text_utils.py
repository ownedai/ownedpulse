"""Shared text normalisation utilities."""
import re

TITLE_SUFFIX_PATTERNS = [
    re.compile(r'\s*\|\s*European\s+Medicines\s+Agency(\s*\(\s*EMA\s*\))?\s*$', re.IGNORECASE),
    re.compile(r'\s*\|\s*EMA(\s*\(\s*European\s+Medicines\s+Agency\s*\))?\s*$', re.IGNORECASE),
    re.compile(r'\s*\|\s*FDA\s*$', re.IGNORECASE),
    re.compile(r'\s*\|\s*ICH\s*$', re.IGNORECASE),
]


def strip_title_suffix(title: str) -> str:
    """Remove known agency suffixes from document titles."""
    if not title:
        return title
    for pat in TITLE_SUFFIX_PATTERNS:
        title = pat.sub("", title)
    return title.strip()


def normalise_agency(agency: str) -> str:
    """Normalise EU-Commission to EMA for display."""
    if agency == "EU-Commission":
        return "EMA"
    return agency


# A citation marker is either a lone index "[4]" or a group "[4, 10]", and the
# generator sometimes emits the decimal form "[4.1]" which is normalised to
# "[4]" before this runs. The client renders the grouped form (QueryPage.jsx),
# so parsing must accept the same shapes or chunks cited only in a group are
# recorded as not cited.
CITATION_GROUP_RE = re.compile(r'\[(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\]')


def parse_cited_indices(answer: str, num_chunks: int) -> set[int]:
    """Return the chunk indices the answer cites, including grouped markers.

    Accepts "[4]", "[4, 10]" and the decimal form "[4.1]", taking the integer
    part of a decimal. Indices outside 1..num_chunks are ignored.
    """
    cited: set[int] = set()
    if not answer:
        return cited
    for match in CITATION_GROUP_RE.finditer(answer):
        for part in match.group(1).split(","):
            try:
                n = int(part.strip().split(".")[0])
            except ValueError:
                continue
            if 1 <= n <= num_chunks:
                cited.add(n)
    return cited
