import Tooltip, { InfoIcon } from '../common/Tooltip';

export default function AuditFooter({ queryId, timestamp, routingPath, onViewTrace }) {
  if (!queryId) return null;

  const shortId = queryId.length > 10 ? queryId.slice(0, 8) : queryId;
  const dateStr = timestamp
    ? new Date(timestamp).toLocaleDateString('en-GB') + ' ' +
      new Date(timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '—';

  const routingLabel = routingPath === 'METADATA' ? 'Metadata lookup' : 'Semantic search';

  return (
    <div className="rp-audit">
      <div className="item">
        <span className="k">Query ID</span>
        <Tooltip tip="Unique identifier for this query session. Use for audit lookup.">
          <span className="v" style={{ cursor: 'help' }}>{shortId}</span>
        </Tooltip>
        <InfoIcon tip="Every query recorded for compliance traceability per Annex 11 §8.1." />
      </div>
      <div className="item">
        <Tooltip tip="Time this query was executed and recorded.">
          <span className="v" style={{ cursor: 'help' }}>{dateStr}</span>
        </Tooltip>
      </div>
      <div className="item">
        <Tooltip tip={routingPath === 'METADATA' ? 'Direct lookup without AI generation.' : 'AI-generated answer from document content.'}>
          <span className="badge-pill" style={{ cursor: 'help' }}>{routingLabel}</span>
        </Tooltip>
      </div>
      <div className="item">
        <Tooltip tip="View full pipeline trace — sub-queries, retrieval, LLM call.">
          <button className="trace-link" onClick={onViewTrace}>View trace &rarr;</button>
        </Tooltip>
      </div>
      <div className="spacer" />
      <div className="item">
        <span className="k">audit log</span>
        <span className="v" style={{ color: 'var(--ok-text)' }}>&#9679; logged</span>
      </div>
    </div>
  );
}
