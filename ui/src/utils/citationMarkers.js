// Display rule for citation markers (K12). Same rule as api/lib/citation_markers.py.
// Checked against tests/fixtures/marker_cases.json by ui/test/citationMarkers.test.js.
//
// Rule (forms whose content has no dot):
//   [N]            unchanged
//   [N-M]          -> [N][N+1]...[M] when N and M are valid sources and 0 < M-N <= 3
//   [N(x)]         -> [N]            (clause suffix dropped)
//   [N, M]         -> [N][M]
//   [N(x), M(y)]   -> [N][M]
// Left unchanged: other forms; any item that is not a valid source number; a
// range that fails the check; forms containing a dot; brackets followed by '(' (links).

const GROUP = /\[([^\[\]]*)\](?!\()/g;
const ITEM = /^(\d+)(?:\s*-\s*(\d+))?(?:\(([a-z])\))?$/;

export function normaliseMarkers(text, validIndices) {
  if (!text) return text || '';
  const valid = new Set(validIndices || []);
  return text.replace(GROUP, (original, inner) => {
    if (inner.includes('.')) return original;
    const parts = [];
    for (const raw of inner.split(',')) {
      const m = ITEM.exec(raw.trim());
      if (!m) return original;
      if (m[2] !== undefined) {
        if (m[3] !== undefined) return original;
        const a = Number(m[1]);
        const b = Number(m[2]);
        if (!(valid.has(a) && valid.has(b) && b - a > 0 && b - a <= 3)) return original;
        for (let n = a; n <= b; n += 1) parts.push(n);
      } else {
        const n = Number(m[1]);
        if (!valid.has(n)) return original;
        parts.push(n);
      }
    }
    return parts.map((n) => '[' + n + ']').join('');
  });
}
