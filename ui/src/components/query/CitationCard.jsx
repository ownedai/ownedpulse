import Tooltip from '../common/Tooltip';

const AGENCY_TIPS = {
  FDA: 'U.S. Food & Drug Administration',
  EMA: 'European Medicines Agency',
  ICH: 'International Council for Harmonisation',
};

export default function CitationCard({ citation, isActive, onClick, onViewSource }) {
  const { index, document_title, issuing_body, document_version, clause_id, publication_date, score, cited_by_llm, superseded, superseded_by } = citation;

  const agency = issuing_body || 'Unknown';
  const version = document_version || '—';
  const clause = clause_id || 'Not available';
  const date = publication_date
    ? new Date(publication_date).toLocaleDateString('en-GB')
    : 'Not available';

  let state = 'active';
  if (superseded) state = 'superseded';
  else if (!cited_by_llm) state = 'dimmed';

  const classes = ['rp-cit'];
  if (state === 'active') classes.push('active');
  if (state === 'dimmed') classes.push('dimmed');
  if (state === 'superseded') classes.push('superseded');
  if (isActive) classes.push('active');

  return (
    <div className={classes.join(' ')} onClick={onClick}>
      <div className="num">[{index}]</div>
      <div className="body">
        <div className="title-row">
          <Tooltip tip={AGENCY_TIPS[agency] || agency} placement="below">
            <span className="agency-tag">{agency}</span>
          </Tooltip>
          <div className="title">{document_title}</div>
          {superseded ? (
            <Tooltip tip="This document version has been superseded. Verify currency before relying on this source.">
              <span className="badge warn">Superseded</span>
            </Tooltip>
          ) : cited_by_llm ? (
            <Tooltip tip="This source was cited by the AI in its answer.">
              <span className="badge matched">Matched</span>
            </Tooltip>
          ) : (
            <Tooltip tip="Retrieved but not used by the AI in its answer.">
              <span className="badge notcited">Not cited</span>
            </Tooltip>
          )}
        </div>
        <div className="meta">
          <span><span className="k">version</span><span className="v">{version}</span></span>
          <span><span className="k">clause</span><span className="v clause">{clause}</span></span>
          <span><span className="k">published</span><span className="v">{date}</span></span>
        </div>
        {superseded && superseded_by && (
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--err-text)', marginTop: 6 }}>
            &rarr; current version: <span style={{ textDecoration: 'underline' }}>{superseded_by}</span>
          </div>
        )}
      </div>
      <div className="right">
        <Tooltip tip={`Semantic similarity. Minimum threshold: 0.60.`}>
          <div className="rp-score">
            <div className="bar"><div className="fill" style={{ width: (score * 100) + '%' }} /></div>
            <span className="v">{score?.toFixed(2)}</span>
          </div>
        </Tooltip>
        <button className="view-src" onClick={(e) => { e.stopPropagation(); onViewSource?.(); }}>
          View source
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M5 3h4v4M4 8l5-5" />
          </svg>
        </button>
      </div>
    </div>
  );
}
