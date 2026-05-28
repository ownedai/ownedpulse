import { useState } from 'react';

export default function QueryExpansion({ subQueries }) {
  const [open, setOpen] = useState(false);

  if (!subQueries || subQueries.length === 0) return null;

  return (
    <div className="rp-expansion">
      <button
        className={`rp-expansion-head${open ? ' open' : ''}`}
        onClick={() => setOpen((v) => !v)}
      >
        Query expansion
        <span className="count">{subQueries.length} variations generated</span>
        <svg className="chev" width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M3 4.5l3 3 3-3" />
        </svg>
      </button>
      {open && (
        <div className="rp-expansion-body">
          {subQueries.map((q, i) => (
            <div key={i} className="sub">
              <span className="n">{i + 1}.</span>
              <span className="q">{q}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
