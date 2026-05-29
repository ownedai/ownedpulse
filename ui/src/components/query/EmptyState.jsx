const EXAMPLE_QUERIES = [
  { agency: 'EMA', text: 'What are the Annex 11 requirements for audit trails?' },
  { agency: 'ICH', text: 'Summarise ICH Q9(R1) changes from the 2005 version.' },
  { agency: 'FDA', text: 'What FDA guidance applies to computerised system validation?' },
];

export default function EmptyState({ onSubmit, disabled }) {
  return (
    <div className="rp-empty-state">
      <div className="rp-empty-suggestions">
        <div className="ex-lbl">Try these queries</div>
        <div className="ex-chips">
          {EXAMPLE_QUERIES.map((eq, i) => (
            <button
              key={i}
              className="ex-chip"
              onClick={() => onSubmit?.(eq.text)}
              disabled={disabled}
            >
              <span style={{
                fontFamily: 'var(--mono)', fontSize: '9.5px', letterSpacing: '0.08em',
                textTransform: 'uppercase', color: 'var(--doc-text-2)',
                padding: '1px 5px', border: '1px solid var(--doc-border-strong)',
                borderRadius: 2,
              }}>
                {eq.agency}
              </span>
              {eq.text}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
