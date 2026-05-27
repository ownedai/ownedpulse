import Badge from '../common/Badge';

export default function CitationCard({ citation, highlighted, onClick, onViewSource }) {
  return (
    <div
      onClick={onClick}
      className={`bg-white border rounded-lg p-4 transition-all cursor-pointer ${
        highlighted
          ? 'border-accent-light ring-2 ring-accent-light/20 shadow-sm'
          : 'border-slate-200 hover:border-slate-300'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-bold text-accent-light bg-accent-bg rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0">
              {citation.index}
            </span>
            <h4 className="text-sm font-semibold text-slate-800 truncate">{citation.title}</h4>
          </div>
          <div className="flex items-center gap-2 text-xs text-secondary ml-7">
            <Badge type="agency" value={citation.agency} />
            {citation.document_version && (
              <span>v{citation.document_version}</span>
            )}
            {citation.publication_date && (
              <span>{citation.publication_date}</span>
            )}
            {citation.clause_id && (
              <span>Clause {citation.clause_id}</span>
            )}
          </div>
          {citation.superseded && (
            <div className="ml-7 mt-1.5">
              <Badge type="superseded" value={`Superseded${citation.superseded_by ? ` by ${citation.superseded_by}` : ''}`} />
            </div>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onViewSource(); }}
          className="text-xs font-medium text-accent-light hover:text-accent-hover flex-shrink-0"
        >
          View source →
        </button>
      </div>
      <div className="mt-2 ml-7">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-light rounded-full transition-all"
              style={{ width: `${Math.min((citation.score || 0) * 100, 100)}%` }}
            />
          </div>
          <span className="text-[10px] text-slate-400 w-8 text-right">
            {Math.round((citation.score || 0) * 100)}%
          </span>
        </div>
      </div>
    </div>
  );
}
