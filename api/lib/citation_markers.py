"""Display rule for citation markers (K12). Used by the PDF export.

The UI has the same rule in ui/src/utils/citationMarkers.js. Both are checked
against tests/fixtures/marker_cases.json.

Rule (forms whose content has no dot):
  [N]              unchanged
  [N-M]            -> [N][N+1]...[M] when N and M are valid sources and 0 < M-N <= 3
  [N(x)]           -> [N]              (clause suffix dropped)
  [N, M]           -> [N][M]
  [N(x), M(y)]     -> [N][M]
Left unchanged: any other form; any item that is not a valid source number
(the whole bracket is kept, so a group with one bad item is not partly rewritten);
a range that fails the check; forms containing a dot ([N.M], [11.10(d)]); and
brackets followed directly by '(' (markdown links).
"""
import re

_GROUP = re.compile(r"\[([^\[\]]*)\](?!\()")
_ITEM = re.compile(r"(\d+)(?:\s*-\s*(\d+))?(?:\(([a-z])\))?")


def normalise_markers(text, valid_indices):
    valid = set(valid_indices)

    def _repl(m):
        original = m.group(0)
        inner = m.group(1)
        if "." in inner:
            return original
        parts = []
        for raw in inner.split(","):
            im = _ITEM.fullmatch(raw.strip())
            if not im:
                return original
            if im.group(2) is not None:
                if im.group(3) is not None:
                    return original
                a, b = int(im.group(1)), int(im.group(2))
                if not (a in valid and b in valid and 0 < b - a <= 3):
                    return original
                parts.extend(range(a, b + 1))
            else:
                n = int(im.group(1))
                if n not in valid:
                    return original
                parts.append(n)
        return "".join("[%d]" % n for n in parts)

    return _GROUP.sub(_repl, text or "")
