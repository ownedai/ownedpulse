import Tooltip, { InfoIcon } from '../common/Tooltip';

const AGENCIES = ['All', 'FDA', 'EMA', 'ICH'];
const AGENCY_TIPS = {
  FDA: 'U.S. Food & Drug Administration',
  EMA: 'European Medicines Agency',
  ICH: 'International Council for Harmonisation',
};
const DOC_TYPES = [
  { label: 'All', value: null },
  { label: 'Guidance', value: 'guidance' },
  { label: 'Press Release', value: 'press-release' },
  { label: 'Reflection Paper', value: 'reflection-paper' },
];
const DATE_RANGES = [
  { label: 'All', value: null },
  { label: 'Last 30d', value: '30d' },
  { label: 'Last 90d', value: '90d' },
  { label: 'Custom', value: 'custom' },
];

export default function FilterBar({
  filters = {},
  onChange,
  retrievalOpen = false,
  onToggleRetrieval,
  retrieval = { depth: 'Standard', k: 10, score: 0.60 },
}) {
  function setAgency(v) {
    onChange?.({ ...filters, agency: v === 'All' ? null : v });
  }

  function setDocType(v) {
    onChange?.({ ...filters, document_type: v });
  }

  function setDateRange(v) {
    if (v === '30d') {
      const d = new Date();
      d.setDate(d.getDate() - 30);
      onChange?.({ ...filters, date_from: d.toISOString().split('T')[0], date_to: null });
    } else if (v === '90d') {
      const d = new Date();
      d.setDate(d.getDate() - 90);
      onChange?.({ ...filters, date_from: d.toISOString().split('T')[0], date_to: null });
    } else {
      onChange?.({ ...filters, date_from: null, date_to: null });
    }
  }

  const activeAgency = filters.agency || 'All';
  const activeDocType = filters.document_type || null;
  const hasDateRange = !!(filters.date_from || filters.date_to);

  return (
    <div className="rp-filter">
      {/* Agency */}
      <div className="grp">
        <span className="grp-name">
          Agency
          <InfoIcon tip="Filter to documents from a specific regulatory agency" />
        </span>
        {AGENCIES.map((a) => (
          <Tooltip key={a} tip={a === 'All' ? 'No agency filter — search across all indexed regulators' : AGENCY_TIPS[a] || ''} placement="below">
            <button
              className={`pill${activeAgency === a ? ' on' : ''}`}
              onClick={() => setAgency(a)}
            >
              {a}
            </button>
          </Tooltip>
        ))}
      </div>

      {/* Document type */}
      <div className="grp">
        <span className="grp-name">
          Type
          <InfoIcon tip="Guidance is normative; press releases are informational" />
        </span>
        {DOC_TYPES.map((dt) => (
          <button
            key={dt.label}
            className={`pill${activeDocType === dt.value ? ' on' : ''}`}
            onClick={() => setDocType(dt.value)}
          >
            {dt.label}
          </button>
        ))}
      </div>

      {/* Date range */}
      <div className="grp">
        <span className="grp-name">
          Date
          <InfoIcon tip="Filter by document publication date, not ingestion date" />
        </span>
        {DATE_RANGES.map((dr) => (
          <button
            key={dr.label}
            className={`pill${(!hasDateRange && dr.value === null) || (hasDateRange && dr.value !== null) ? '' : ''}${(!hasDateRange && dr.value === null) ? ' on' : ''}`}
            onClick={() => setDateRange(dr.value)}
          >
            {dr.label}
          </button>
        ))}
      </div>

      {/* Retrieval settings toggle */}
      <div className="grp" style={{ borderLeft: '1px solid var(--shell-border-soft)', paddingLeft: 18 }}>
        <Tooltip tip="Controls how many search variations are generated. Deep produces more thorough results but takes longer." placement="below">
          <button
            className={`retrieval-toggle${retrievalOpen ? ' on' : ''}`}
            onClick={onToggleRetrieval}
          >
            Retrieval settings
            <span className="summary">{retrieval.depth} · K={retrieval.k} · {retrieval.score.toFixed(2)}</span>
            <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M3 4.5l3 3 3-3" />
            </svg>
          </button>
        </Tooltip>
      </div>

      <div className="spacer" />
    </div>
  );
}
