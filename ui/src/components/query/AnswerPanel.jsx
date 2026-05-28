export default function AnswerPanel({ answer, onCitationClick, activeCitation }) {
  if (!answer) return null;

  // Split answer text into segments, converting [N] markers to clickable spans
  const parts = [];
  let lastIndex = 0;
  const regex = /\[(\d+)\]/g;
  let match;

  while ((match = regex.exec(answer)) !== null) {
    // Text before this citation
    if (match.index > lastIndex) {
      parts.push({ type: 'text', key: `t-${lastIndex}`, text: answer.slice(lastIndex, match.index) });
    }
    const n = parseInt(match[1], 10);
    parts.push({ type: 'cite', key: `c-${match.index}`, n, active: activeCitation === n });
    lastIndex = match.index + match[0].length;
  }

  // Remaining text
  if (lastIndex < answer.length) {
    parts.push({ type: 'text', key: `t-${lastIndex}`, text: answer.slice(lastIndex) });
  }

  return (
    <div className="rp-answer">
      {parts.map((p) => {
        if (p.type === 'text') {
          // Split text into paragraphs
          return p.text.split('\n\n').map((para, i) =>
            para ? <p key={`${p.key}-p${i}`}>{para.split('\n').map((line, j) => j > 0 ? [<br key={`br-${j}`} />, line] : line)}</p> : null
          );
        }
        return (
          <button
            key={p.key}
            className={`rp-cite${p.active ? ' active' : ''}`}
            onClick={() => onCitationClick?.(p.n)}
          >
            [{p.n}]
          </button>
        );
      })}
      <div className="rp-disclaimer">
        AI-generated answer based on retrieved regulatory documents. Verify critical requirements against current source documents. Queries requiring legal interpretation should be referred to a qualified regulatory professional.
      </div>
    </div>
  );
}
