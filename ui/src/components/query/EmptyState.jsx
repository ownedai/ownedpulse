import Logo from '../common/Logo';
import QueryInput from './QueryInput';
import CorpusStatsBar from './CorpusStatsBar';

const EXAMPLE_QUERIES = [
  { agency: 'EMA', text: 'What are the Annex 11 requirements for audit trails?' },
  { agency: 'ICH', text: 'Summarise ICH Q9(R1) changes from the 2005 version.' },
  { agency: 'FDA', text: 'What FDA guidance applies to computerised system validation?' },
];

export default function EmptyState({ onSubmit, disabled, filters }) {
  return (
    <div className="rp-content">
      <div className="rp-content-inner">
        <div style={{ maxWidth: 760, margin: '0 auto' }}>
          <div className="crest">
            <Logo onLight showWordmark />
          </div>
          <h1 style={{
            fontSize: 28, fontWeight: 500, letterSpacing: '-0.015em',
            lineHeight: 1.2, margin: '0 0 10px', color: 'var(--doc-text)'
          }}>
            Query regulatory intelligence
          </h1>
          <p style={{
            fontSize: 15, lineHeight: 1.6, color: 'var(--doc-text-2)',
            margin: '0 0 32px', maxWidth: '56ch'
          }}>
            Search FDA, EMA, and ICH guidance documents. All processing on your infrastructure.
          </p>

          <QueryInput onSubmit={onSubmit} disabled={disabled} />

          <div className="ex-lbl" style={{ marginTop: 32 }}>Try these queries</div>
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
                  borderRadius: 2
                }}>
                  {eq.agency}
                </span>
                {eq.text}
              </button>
            ))}
          </div>
        </div>
      </div>

      <CorpusStatsBar />
    </div>
  );
}
