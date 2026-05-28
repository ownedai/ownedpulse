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
      onChange?.({ ...filters, date_from: d.toISOString().split('T')[0], date_to: null, _datePreset: '30d' });
    } else if (v === '90d') {
      const d = new Date();
      d.setDate(d.getDate() - 90);
      onChange?.({ ...filters, date_from: d.toISOString().split('T')[0], date_to: null, _datePreset: '90d' });
    } else if (v === 'custom') {
      onChange?.({ ...filters, date_from: null, date_to: null, _datePreset: 'custom' });
    } else {
      onChange?.({ ...filters, date_from: null, date_to: null, _datePreset: null });
    }
  }

  // Convert ISO → dd.mm.yyyy for display
  function isoToEu(iso) {
    if (!iso) return '';
    const [y, m, d] = iso.split('-');
    if (!y || !m || !d) return iso;
    return `${d}.${m}.${y}`;
  }

  // Convert dd.mm.yyyy → ISO for API; returns null on invalid
  function euToIso(eu) {
    const trimmed = eu.trim();
    if (!trimmed) return null;
    const m = trimmed.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
    if (!m) return trimmed; // return as-is if not matching format (user still typing)
    return `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
  }

  function setDateFrom(v) {
    onChange?.({ ...filters, date_from: euToIso(v) });
  }

  function setDateTo(v) {
    onChange?.({ ...filters, date_to: euToIso(v) });
  }

  const activeAgency = filters.agency || 'All';
  const activeDocType = filters.document_type || null;
  const datePreset = filters._datePreset || null;
  const hasCustomDate = datePreset === 'custom';
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
        {DATE_RANGES.map((dr) => {
          const isActive = dr.value === null ? !datePreset : datePreset === dr.value;
          return (
            <button
              key={dr.label}
              className={`pill${isActive ? ' on' : ''}`}
              onClick={() => setDateRange(dr.value)}
            >
              {dr.label}
            </button>
          );
        })}
      </div>

      {/* Custom date inputs */}
      {hasCustomDate && (
        <div className="grp" style={{ gap: 6 }}>
          <span className="grp-name">From</span>
          <input
            type="text"
            value={isoToEu(filters.date_from)}
            onChange={(e) => setDateFrom(e.target.value)}
            placeholder="dd.mm.yyyy"
            className="rp-date-input"
          />
          <span className="grp-name">To</span>
          <input
            type="text"
            value={isoToEu(filters.date_to)}
            onChange={(e) => setDateTo(e.target.value)}
            placeholder="dd.mm.yyyy"
            className="rp-date-input"
          />
        </div>
      )}

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
