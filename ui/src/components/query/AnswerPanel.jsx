function renderInline(text, activeCitation, onCitationClick) {
  const parts = [];
  let lastIndex = 0;
  const regex = /\[(\d+)\]/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const n = parseInt(match[1], 10);
    parts.push(
      <button
        key={`c-${match.index}`}
        className={`rp-cite${activeCitation === n ? ' active' : ''}`}
        onClick={() => onCitationClick?.(n)}
      >
        [{n}]
      </button>
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

export default function AnswerPanel({ answer, onCitationClick, activeCitation }) {
  if (!answer) return null;

  const normalised = answer
    .replace(/\n{1,2}(\[\d+\])\n([.,])/g, ' $1$2')
    .replace(/(\[\d+\])\s*\./g,  '$1.')
    .replace(/\s*\.\s*(\[\d+\])/g, '$1.');

  const paragraphs = normalised.split('\n\n').filter(p => p.trim());

  return (
    <div className="rp-answer">
      {paragraphs.map((para, i) => (
        <p key={`p-${i}`}>
          {renderInline(para.replace(/\n/g, ' '), activeCitation, onCitationClick)}
        </p>
      ))}
      <div className="rp-disclaimer">
        AI-generated answer based on retrieved regulatory documents. Verify critical
        requirements against current source documents. Queries requiring legal
        interpretation should be referred to a qualified regulatory professional.
      </div>
    </div>
  );
}
