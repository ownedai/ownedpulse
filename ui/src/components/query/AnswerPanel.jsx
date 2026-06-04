import { Link } from 'react-router-dom';

function renderInline(text, activeCitation, onCitationClick) {
  // Tokenise: [N] citation markers, [text](url) markdown links, **bold**
  const parts = [];
  const regex = /\[(\d+)\]|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*/g;
  let lastIndex = 0;
  let match;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[1] !== undefined) {
      // [N] citation
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
    } else if (match[2] !== undefined) {
      // [text](url) link — internal if starts with /
      const label = match[2];
      const url = match[3];
      if (url.startsWith('/')) {
        parts.push(
          <Link key={`l-${match.index}`} to={url} style={{ color: 'var(--accent-l)', textDecoration: 'none' }}>
            {label}
          </Link>
        );
      } else {
        parts.push(
          <a key={`l-${match.index}`} href={url} target="_blank" rel="noopener noreferrer"
            style={{ color: 'var(--accent-l)', textDecoration: 'none' }}>
            {label}
          </a>
        );
      }
    } else if (match[4] !== undefined) {
      // **bold**
      parts.push(<strong key={`b-${match.index}`}>{match[4]}</strong>);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

export default function AnswerPanel({ answer, onCitationClick, activeCitation }) {
  if (!answer) return null;

  const normalised = answer
    .replace(/\n{1,2}(\[\d+\])\n([.,])/g, ' $1$2')
    .replace(/(\[\d+\])\s*\./g, '$1.')
    .replace(/\s*\.\s*(\[\d+\])/g, '$1.');

  const sections = normalised.split('\n\n').filter(p => p.trim());

  return (
    <div className="rp-answer">
      {sections.map((section, i) => {
        const lines = section.split('\n').filter(l => l.trim());
        // Numbered list: lines starting with "N."
        const isNumbered = lines.length > 1 && /^\d+\./.test(lines[0].trim());
        // Bullet list: lines starting with "- "
        const isBullet = lines.length > 1 && lines[0].trim().startsWith('- ');

        if (isNumbered) {
          return (
            <ol key={`s-${i}`} style={{ paddingLeft: 20, margin: '0 0 12px' }}>
              {lines.map((line, j) => {
                const content = line.replace(/^\d+\.\s*/, '');
                return (
                  <li key={j} style={{ marginBottom: 5, lineHeight: 1.6 }}>
                    {renderInline(content, activeCitation, onCitationClick)}
                  </li>
                );
              })}
            </ol>
          );
        }

        if (isBullet) {
          return (
            <ul key={`s-${i}`} style={{ paddingLeft: 20, margin: '0 0 12px' }}>
              {lines.map((line, j) => {
                const content = line.replace(/^-\s*/, '');
                return (
                  <li key={j} style={{ marginBottom: 5, lineHeight: 1.6 }}>
                    {renderInline(content, activeCitation, onCitationClick)}
                  </li>
                );
              })}
            </ul>
          );
        }

        return (
          <p key={`s-${i}`}>
            {renderInline(lines.join(' '), activeCitation, onCitationClick)}
          </p>
        );
      })}
      <div className="rp-disclaimer">
        AI-generated answer based on retrieved regulatory documents. Verify critical
        requirements against current source documents. Queries requiring legal
        interpretation should be referred to a qualified regulatory professional.
      </div>
    </div>
  );
}
